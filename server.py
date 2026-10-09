from __future__ import annotations

import asyncio
import copy
import json
import math
import threading

from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import yaml

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from starlette.types import (
    ASGIApp,
    Receive,
    Scope,
    Send,
)

from src.calibration import CameraProjector

from src.tracking import (
    GlobalObservation,
    GlobalTracker,
    LocalTracker,
    TrackState,
)


ROOT = Path(__file__).resolve().parent

WEB_DIR = (
    ROOT
    /
    "web"
)

VIDEO_DIR = (
    ROOT
    /
    "data"
    /
    "videos"
)

MAP_DIR = (
    ROOT
    /
    "data"
    /
    "maps"
)

PARKING_DIR = (
    ROOT
    /
    "data"
    /
    "parking"
)


DETECTION_CONFIG_PATH = (
    ROOT
    /
    "config"
    /
    "detection.yaml"
)

TRACKING_CONFIG_PATH = (
    ROOT
    /
    "config"
    /
    "tracking.yaml"
)

GLOBAL_TRACKING_CONFIG_PATH = (
    ROOT
    /
    "config"
    /
    "global_tracking.yaml"
)

DETECTION_CACHE_PATH = (
    ROOT
    /
    "data"
    /
    "detections"
    /
    "scene1"
    /
    "detections.jsonl"
)


CHECKPOINT_INTERVAL_SEC = 10.0


# =========================================================
# Quiet asyncio errors
# =========================================================


def quiet_asyncio_exception_handler(
    loop: asyncio.AbstractEventLoop,
    context: dict,
) -> None:

    """
    Windows에서 브라우저가 MP4 Range 연결을 먼저 끊을 때
    ProactorEventLoop가 출력하는 WinError 10054만 무시한다.

    그 외 asyncio 오류는 기존 기본 handler로 전달한다.
    """

    exception = context.get(
        "exception"
    )

    if (
        isinstance(
            exception,
            ConnectionResetError,
        )
        and
        getattr(
            exception,
            "winerror",
            None,
        )
        ==
        10054
    ):

        return

    # 일부 환경에서는 같은 오류가 OSError 계열로 들어올 수 있다.
    if (
        isinstance(
            exception,
            OSError,
        )
        and
        getattr(
            exception,
            "winerror",
            None,
        )
        ==
        10054
    ):

        return

    loop.default_exception_handler(
        context
    )


@asynccontextmanager
async def lifespan(
    app: FastAPI,
):

    loop = (
        asyncio.get_running_loop()
    )

    loop.set_exception_handler(
        quiet_asyncio_exception_handler
    )

    yield


# =========================================================
# Quiet shutdown middleware
# =========================================================


class QuietCancelledErrorMiddleware:

    """
    Ctrl+C 종료 중 브라우저의 MP4 요청이나
    API 요청이 취소되면서 발생하는 CancelledError를
    정상 종료로 처리한다.
    """

    def __init__(
        self,
        app: ASGIApp,
    ):

        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:

        try:

            await self.app(
                scope,
                receive,
                send,
            )

        except asyncio.CancelledError:

            return


# =========================================================
# FastAPI
# =========================================================


app = FastAPI(
    title="AX Parking",
    lifespan=lifespan,
)


app.add_middleware(
    QuietCancelledErrorMiddleware
)


app.mount(
    "/web",
    StaticFiles(
        directory=WEB_DIR
    ),
    name="web",
)


app.mount(
    "/media",
    StaticFiles(
        directory=VIDEO_DIR
    ),
    name="media",
)


app.mount(
    "/map",
    StaticFiles(
        directory=MAP_DIR
    ),
    name="map",
)


app.mount(
    "/parking",
    StaticFiles(
        directory=PARKING_DIR
    ),
    name="parking",
)


# =========================================================
# Helpers
# =========================================================


def load_yaml(
    path: Path,
) -> dict:

    if not path.exists():

        return {}

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:

        data = yaml.safe_load(
            file
        )

    if data is None:

        return {}

    return data


# =========================================================
# Cached YOLO
# =========================================================


@dataclass
class CachedDetection:

    x1: float
    y1: float
    x2: float
    y2: float

    class_name: str

    confidence: float


class DetectionCacheStore:

    def __init__(
        self,
        path: Path,
    ):

        self.path = path

        if not self.path.exists():

            raise FileNotFoundError(
                "Detection cache not found:\n"
                f"{self.path}"
            )

        self.offsets: list[int] = []

        self._build_index()

        self.file = self.path.open(
            "rb"
        )

    def _build_index(
        self,
    ) -> None:

        self.offsets.clear()

        with self.path.open(
            "rb"
        ) as file:

            while True:

                offset = (
                    file.tell()
                )

                line = (
                    file.readline()
                )

                if not line:

                    break

                self.offsets.append(
                    offset
                )

    @property
    def frame_count(
        self,
    ) -> int:

        return len(
            self.offsets
        )

    def read_frame(
        self,
        frame_index: int,
    ) -> dict:

        if (
            frame_index < 0
            or
            frame_index
            >=
            self.frame_count
        ):

            raise IndexError(
                "Cache frame out of range: "
                f"{frame_index}"
            )

        self.file.seek(
            self.offsets[
                frame_index
            ]
        )

        line = (
            self.file.readline()
        )

        if not line:

            raise RuntimeError(
                "Failed to read detection cache "
                f"frame {frame_index}"
            )

        frame_data = (
            json.loads(
                line.decode(
                    "utf-8"
                )
            )
        )

        cached_frame_index = int(
            frame_data.get(
                "frame_index",
                -1,
            )
        )

        if (
            cached_frame_index
            !=
            frame_index
        ):

            raise RuntimeError(
                "Detection cache is not sequential.\n"
                f"Requested frame : {frame_index}\n"
                f"Cached frame    : {cached_frame_index}"
            )

        return frame_data


# =========================================================
# Tracking Engine
# =========================================================


class TrackingEngine:

    def __init__(
        self,
        cache_path: Path,
    ):

        self.lock = (
            threading.RLock()
        )

        self.cache = (
            DetectionCacheStore(
                cache_path
            )
        )

        self.detection_config = (
            load_yaml(
                DETECTION_CONFIG_PATH
            )
        )

        self.camera_ids = [

            str(
                video[
                    "camera_id"
                ]
            )

            for video
            in self.detection_config.get(
                "videos",
                [],
            )
        ]

        if not self.camera_ids:

            raise RuntimeError(
                "No cameras configured "
                "in detection.yaml"
            )

        # reload_config()에서 calibration 파일을 읽어 채운다.
        self.projectors: dict[
            str,
            CameraProjector,
        ] = {}

        self.tracking_config: dict = {}

        self.global_tracking_config: dict = {}

        self.local_trackers: dict[
            str,
            LocalTracker,
        ] = {}

        self.global_tracker: (
            GlobalTracker
            |
            None
        ) = None

        self.global_enabled = False

        self.nominal_fps = 30.0

        # UNKNOWN에서 움직임 후보가 시작된 뒤
        # 이 시간이 지나면 Global Re-ID probe 시작.
        self.global_probe_motion_sec = 0.35

        self.checkpoint_interval_frames = (
            300
        )

        self.current_frame = -1

        self.last_result: (
            dict
            |
            None
        ) = None

        self.checkpoints: dict[
            int,
            tuple[
                dict[
                    str,
                    LocalTracker,
                ],
                GlobalTracker | None,
            ],
        ] = {}

        self.reload_config()

    # =====================================================
    # Config
    # =====================================================

    def reload_config(
        self,
    ) -> None:

        with self.lock:

            # calibration을 수정한 뒤 웹의 Reload로도 반영되도록
            # tracking 설정과 함께 다시 읽는다.
            self._load_projectors()

            tracking_root = (
                load_yaml(
                    TRACKING_CONFIG_PATH
                )
            )

            self.tracking_config = (
                tracking_root.get(
                    "local_tracking",
                    {},
                )
            )

            global_root = (
                load_yaml(
                    GLOBAL_TRACKING_CONFIG_PATH
                )
            )

            self.global_tracking_config = (
                global_root.get(
                    "global_tracking",
                    {},
                )
            )

            self.nominal_fps = float(
                self.tracking_config.get(
                    "nominal_fps",
                    30.0,
                )
            )

            self.global_probe_motion_sec = (
                float(
                    self.global_tracking_config.get(
                        "probe_motion_sec",
                        0.35,
                    )
                )
            )

            self.checkpoint_interval_frames = (
                max(
                    1,
                    int(
                        round(
                            CHECKPOINT_INTERVAL_SEC
                            *
                            self.nominal_fps
                        )
                    ),
                )
            )

            self._reset_runtime(
                clear_checkpoints=True
            )

    def _reset_runtime(
        self,
        clear_checkpoints: bool,
    ) -> None:

        self.local_trackers = (
            self._create_local_trackers()
        )

        self.global_enabled = bool(
            self.global_tracking_config.get(
                "enabled",
                True,
            )
        )

        if self.global_enabled:

            self.global_tracker = (
                self._create_global_tracker()
            )

        else:

            self.global_tracker = None

        self.current_frame = -1

        self.last_result = None

        if clear_checkpoints:

            self.checkpoints.clear()

    def _load_projectors(
        self,
    ) -> None:

        projectors: dict[
            str,
            CameraProjector,
        ] = {}

        for camera_id in (
            self.camera_ids
        ):

            try:

                projectors[
                    camera_id
                ] = CameraProjector(
                    camera_id
                )

            except Exception as error:

                # calibration이 없거나 깨진 카메라는
                # BEV 투영에서 제외되므로 이유를 알린다.
                print(
                    f"[WARN] {camera_id}: "
                    f"calibration not loaded, "
                    f"BEV projection disabled "
                    f"({error})"
                )

        self.projectors = projectors

    def reset(
        self,
    ) -> None:

        with self.lock:

            self._reset_runtime(
                clear_checkpoints=True
            )

    # =====================================================
    # Local Tracker
    # =====================================================

    def _create_local_trackers(
        self,
    ) -> dict[
        str,
        LocalTracker,
    ]:

        config = (
            self.tracking_config
        )

        trackers = {}

        for camera_id in (
            self.camera_ids
        ):

            trackers[
                camera_id
            ] = LocalTracker(

                camera_id=camera_id,

                match_distance_px=float(
                    config.get(
                        "match_distance_px",
                        55.0,
                    )
                ),

                match_distance_bbox_ratio=float(
                    config.get(
                        "match_distance_bbox_ratio",
                        0.40,
                    )
                ),

                match_iou_threshold=float(
                    config.get(
                        "match_iou_threshold",
                        0.12,
                    )
                ),

                motion_window_sec=float(
                    config.get(
                        "motion_window_sec",
                        0.8,
                    )
                ),

                min_motion_px=float(
                    config.get(
                        "min_motion_px",
                        16.0,
                    )
                ),

                motion_bbox_ratio=float(
                    config.get(
                        "motion_bbox_ratio",
                        0.080,
                    )
                ),

                smoothing_window=int(
                    config.get(
                        "smoothing_window",
                        9,
                    )
                ),

                unknown_to_active_sec=float(
                    config.get(
                        "unknown_to_active_sec",
                        1.20,
                    )
                ),

                active_to_stopped_sec=float(
                    config.get(
                        "active_to_stopped_sec",
                        0.80,
                    )
                ),

                stopped_motion_multiplier=float(
                    config.get(
                        "stopped_motion_multiplier",
                        2.5,
                    )
                ),

                stopped_to_active_sec=float(
                    config.get(
                        "stopped_to_active_sec",
                        1.00,
                    )
                ),

                parked_after_sec=float(
                    config.get(
                        "parked_after_sec",
                        5.0,
                    )
                ),

                stop_anchor_min_px=float(
                    config.get(
                        "stop_anchor_min_px",
                        14.0,
                    )
                ),

                stop_anchor_bbox_ratio=float(
                    config.get(
                        "stop_anchor_bbox_ratio",
                        0.10,
                    )
                ),

                parked_motion_multiplier=float(
                    config.get(
                        "parked_motion_multiplier",
                        3.0,
                    )
                ),

                parked_to_active_sec=float(
                    config.get(
                        "parked_to_active_sec",
                        1.20,
                    )
                ),

                parked_exit_min_px=float(
                    config.get(
                        "parked_exit_min_px",
                        28.0,
                    )
                ),

                parked_exit_bbox_ratio=float(
                    config.get(
                        "parked_exit_bbox_ratio",
                        0.16,
                    )
                ),

                max_missing_sec=float(
                    config.get(
                        "max_missing_sec",
                        1.5,
                    )
                ),

                nominal_fps=float(
                    config.get(
                        "nominal_fps",
                        30.0,
                    )
                ),

                print_transitions=False,
            )

        return trackers

    # =====================================================
    # Global Tracker
    # =====================================================

    def _create_global_tracker(
        self,
    ) -> GlobalTracker:

        config = (
            self.global_tracking_config
        )

        return GlobalTracker(

            max_reid_gap_sec=float(
                config.get(
                    "max_reid_gap_sec",
                    3.0,
                )
            ),

            base_match_distance_px=float(
                config.get(
                    "base_match_distance_px",
                    80.0,
                )
            ),

            max_match_distance_px=float(
                config.get(
                    "max_match_distance_px",
                    300.0,
                )
            ),

            max_speed_px_per_sec=float(
                config.get(
                    "max_speed_px_per_sec",
                    180.0,
                )
            ),

            time_weight=float(
                config.get(
                    "time_weight",
                    0.10,
                )
            ),

            class_mismatch_penalty=float(
                config.get(
                    "class_mismatch_penalty",
                    0.20,
                )
            ),

            max_match_score=float(
                config.get(
                    "max_match_score",
                    0.95,
                )
            ),

            retention_sec=float(
                config.get(
                    "retention_sec",
                    120.0,
                )
            ),

            motion_history_sec=float(
                config.get(
                    "motion_history_sec",
                    0.8,
                )
            ),

            prediction_weight=float(
                config.get(
                    "prediction_weight",
                    0.55,
                )
            ),

            direction_weight=float(
                config.get(
                    "direction_weight",
                    0.25,
                )
            ),

            speed_weight=float(
                config.get(
                    "speed_weight",
                    0.10,
                )
            ),

            direction_soft_limit_deg=float(
                config.get(
                    "direction_soft_limit_deg",
                    60.0,
                )
            ),

            direction_hard_limit_deg=float(
                config.get(
                    "direction_hard_limit_deg",
                    120.0,
                )
            ),

            min_direction_speed_px_per_sec=float(
                config.get(
                    "min_direction_speed_px_per_sec",
                    15.0,
                )
            ),

            provisional_confirm_count=int(
                config.get(
                    "provisional_confirm_count",
                    3,
                )
            ),

            min_score_margin=float(
                config.get(
                    "min_score_margin",
                    0.15,
                )
            ),

            probe_retention_sec=float(
                config.get(
                    "probe_retention_sec",
                    3.0,
                )
            ),

            print_events=False,
        )

    # =====================================================
    # Checkpoints
    # =====================================================

    def _save_checkpoint(
        self,
        frame_index: int,
    ) -> None:

        self.checkpoints[
            frame_index
        ] = (

            copy.deepcopy(
                self.local_trackers
            ),

            copy.deepcopy(
                self.global_tracker
            ),
        )

    def _restore_for_frame(
        self,
        target_frame: int,
    ) -> None:

        # 체크포인트는 해당 frame을 처리한 뒤의 상태다.
        # target과 같은 checkpoint를 사용하면
        # 같은 frame이 두 번 반영되므로 작은 checkpoint만 사용.
        available = [

            frame_index

            for frame_index
            in self.checkpoints.keys()

            if (
                frame_index
                <
                target_frame
            )
        ]

        if not available:

            self._reset_runtime(
                clear_checkpoints=False
            )

            return

        checkpoint_frame = max(
            available
        )

        (
            local_trackers,
            global_tracker,
        ) = self.checkpoints[
            checkpoint_frame
        ]

        self.local_trackers = (
            copy.deepcopy(
                local_trackers
            )
        )

        self.global_tracker = (
            copy.deepcopy(
                global_tracker
            )
        )

        self.current_frame = (
            checkpoint_frame
        )

        self.last_result = None

    # =====================================================
    # Detection conversion
    # =====================================================

    @staticmethod
    def _make_detection(
        data: dict,
    ) -> CachedDetection:

        return CachedDetection(

            x1=float(
                data[
                    "x1"
                ]
            ),

            y1=float(
                data[
                    "y1"
                ]
            ),

            x2=float(
                data[
                    "x2"
                ]
            ),

            y2=float(
                data[
                    "y2"
                ]
            ),

            class_name=str(
                data[
                    "class_name"
                ]
            ),

            confidence=float(
                data[
                    "confidence"
                ]
            ),
        )

    @staticmethod
    def _make_global_observation(
        camera_id: str,
        track,
        bev_x: float,
        bev_y: float,
        timestamp: float,
    ) -> GlobalObservation:

        return GlobalObservation(

            camera_id=camera_id,

            local_id=(
                track.local_id
            ),

            state=(
                track.state
            ),

            class_name=(
                track.class_name
            ),

            confidence=(
                track.confidence
            ),

            bev_x=bev_x,

            bev_y=bev_y,

            timestamp=timestamp,
        )

    def _should_probe_unknown(
        self,
        track,
        timestamp: float,
    ) -> bool:

        if (
            track.state
            !=
            TrackState.UNKNOWN
        ):

            return False

        if track.has_moved:

            return False

        if (
            track.moving_candidate_since
            is None
        ):

            return False

        moving_candidate_duration = (
            timestamp
            -
            track.moving_candidate_since
        )

        return (
            moving_candidate_duration
            >=
            self.global_probe_motion_sec
        )

    # =====================================================
    # Frame Processing
    # =====================================================

    def _process_frame(
        self,
        frame_index: int,
    ) -> dict:

        frame_data = (
            self.cache.read_frame(
                frame_index
            )
        )

        timestamp = float(
            frame_data.get(
                "timestamp",
                frame_index
                /
                self.nominal_fps,
            )
        )

        cached_cameras = (
            frame_data.get(
                "cameras",
                {},
            )
        )

        all_tracked: dict[
            str,
            list,
        ] = {}

        # -------------------------------------------------
        # 1. Local Tracking
        # -------------------------------------------------

        for camera_id in (
            self.camera_ids
        ):

            detection_data = (
                cached_cameras.get(
                    camera_id,
                    [],
                )
            )

            detections = [

                self._make_detection(
                    item
                )

                for item
                in detection_data
            ]

            tracked = (

                self.local_trackers[
                    camera_id
                ].update(

                    detections=detections,

                    timestamp=timestamp,
                )
            )

            all_tracked[
                camera_id
            ] = tracked

        # -------------------------------------------------
        # 2. BEV Projection
        # -------------------------------------------------

        confirmed_observations = []

        probe_observations = []

        bev_items = []

        for camera_id in (
            self.camera_ids
        ):

            projector = (
                self.projectors.get(
                    camera_id
                )
            )

            if projector is None:

                continue

            for tracked in (
                all_tracked[
                    camera_id
                ]
            ):

                track = (
                    tracked.track
                )

                should_probe = (
                    self._should_probe_unknown(
                        track,
                        timestamp,
                    )
                )

                if (
                    not track.has_moved
                    and
                    not should_probe
                ):

                    continue

                try:

                    bev_x, bev_y = (
                        projector.project(

                            track.ground_x,

                            track.ground_y,
                        )
                    )

                except Exception:

                    continue

                if (
                    not math.isfinite(
                        bev_x
                    )
                    or
                    not math.isfinite(
                        bev_y
                    )
                ):

                    continue

                observation = (
                    self._make_global_observation(

                        camera_id,

                        track,

                        bev_x,

                        bev_y,

                        timestamp,
                    )
                )

                if track.has_moved:

                    confirmed_observations.append(
                        observation
                    )

                    bev_items.append(
                        {

                            "camera_id":
                                camera_id,

                            "local_id":
                                track.local_id,

                            "global_id":
                                None,

                            "state":
                                track.state.value,

                            "class_name":
                                track.class_name,

                            "confidence":
                                float(
                                    track.confidence
                                ),

                            "x":
                                float(
                                    bev_x
                                ),

                            "y":
                                float(
                                    bev_y
                                ),

                            "stopped_seconds":
                                float(
                                    track.stopped_duration(
                                        timestamp
                                    )
                                ),
                        }
                    )

                elif should_probe:

                    probe_observations.append(
                        observation
                    )

        # -------------------------------------------------
        # 3. Confirmed Global Tracking
        # -------------------------------------------------

        assignments = {}

        if (
            self.global_enabled
            and
            self.global_tracker
            is not None
        ):

            assignments = (
                self.global_tracker.update(

                    observations=(
                        confirmed_observations
                    ),

                    timestamp=timestamp,
                )
            )

            for observation in (
                probe_observations
            ):

                self.global_tracker.probe_existing(
                    observation
                )

        # -------------------------------------------------
        # 4. BEV Global IDs
        # -------------------------------------------------

        for item in bev_items:

            local_key = (
                item[
                    "camera_id"
                ],
                item[
                    "local_id"
                ],
            )

            global_id = (
                assignments.get(
                    local_key
                )
            )

            if (
                global_id is None
                and
                self.global_tracker
                is not None
            ):

                global_id = (
                    self.global_tracker.get_global_id(
                        *local_key
                    )
                )

            item[
                "global_id"
            ] = global_id

        # -------------------------------------------------
        # 5. Camera Overlay Result
        # -------------------------------------------------

        cameras_result = {}

        for camera_id in (
            self.camera_ids
        ):

            camera_result = []

            for tracked in (
                all_tracked[
                    camera_id
                ]
            ):

                detection = (
                    tracked.detection
                )

                track = (
                    tracked.track
                )

                global_id = None

                provisional_global_id = None

                if (
                    self.global_tracker
                    is not None
                ):

                    global_id = (
                        self.global_tracker.get_global_id(

                            camera_id,

                            track.local_id,
                        )
                    )

                    provisional_global_id = (
                        self.global_tracker.get_provisional_global_id(

                            camera_id,

                            track.local_id,
                        )
                    )

                camera_result.append(
                    {

                        "x1":
                            float(
                                detection.x1
                            ),

                        "y1":
                            float(
                                detection.y1
                            ),

                        "x2":
                            float(
                                detection.x2
                            ),

                        "y2":
                            float(
                                detection.y2
                            ),

                        "local_id":
                            int(
                                track.local_id
                            ),

                        "global_id":
                            (
                                int(
                                    global_id
                                )
                                if global_id
                                is not None
                                else None
                            ),

                        "provisional_global_id":
                            (
                                int(
                                    provisional_global_id
                                )
                                if provisional_global_id
                                is not None
                                else None
                            ),

                        "state":
                            track.state.value,

                        "has_moved":
                            bool(
                                track.has_moved
                            ),

                        "class_name":
                            track.class_name,

                        "confidence":
                            float(
                                track.confidence
                            ),

                        "ground_x":
                            float(
                                track.ground_x
                            ),

                        "ground_y":
                            float(
                                track.ground_y
                            ),

                        "stopped_seconds":
                            float(
                                track.stopped_duration(
                                    timestamp
                                )
                            ),
                    }
                )

            cameras_result[
                camera_id
            ] = camera_result

        result = {

            "frame_index":
                int(
                    frame_index
                ),

            "timestamp":
                float(
                    timestamp
                ),

            "fps":
                float(
                    self.nominal_fps
                ),

            "cameras":
                cameras_result,

            "bev":
                bev_items,
        }

        self.current_frame = (
            frame_index
        )

        self.last_result = (
            result
        )

        if (
            frame_index
            %
            self.checkpoint_interval_frames
            ==
            0
        ):

            self._save_checkpoint(
                frame_index
            )

        return result

    # =====================================================
    # Public Frame Access
    # =====================================================

    def get_frame(
        self,
        target_frame: int,
    ) -> dict:

        with self.lock:

            target_frame = max(
                0,
                min(
                    int(
                        target_frame
                    ),
                    self.cache.frame_count
                    -
                    1,
                ),
            )

            if (
                target_frame
                ==
                self.current_frame
                and
                self.last_result
                is not None
            ):

                return (
                    self.last_result
                )

            if (
                target_frame
                <
                self.current_frame
            ):

                self._restore_for_frame(
                    target_frame
                )

            result = None

            for frame_index in range(
                self.current_frame + 1,
                target_frame + 1,
            ):

                result = (
                    self._process_frame(
                        frame_index
                    )
                )

            if result is None:

                result = (
                    self._process_frame(
                        target_frame
                    )
                )

            return result

    def info(
        self,
    ) -> dict:

        return {

            "camera_ids":
                self.camera_ids,

            "fps":
                float(
                    self.nominal_fps
                ),

            "frame_count":
                int(
                    self.cache.frame_count
                ),

            "duration":
                float(
                    self.cache.frame_count
                    /
                    self.nominal_fps
                ),

            "current_frame":
                int(
                    self.current_frame
                ),

            "checkpoint_interval_frames":
                int(
                    self.checkpoint_interval_frames
                ),

            "global_tracking":
                bool(
                    self.global_enabled
                ),

            "global_probe_motion_sec":
                float(
                    self.global_probe_motion_sec
                ),
        }


# =========================================================
# Engine
# =========================================================


tracking_engine = (
    TrackingEngine(
        DETECTION_CACHE_PATH
    )
)


# =========================================================
# Routes
# =========================================================


@app.get("/")
def index():

    return FileResponse(
        WEB_DIR
        /
        "index.html"
    )


@app.get("/api/health")
def health():

    return {
        "status": "ok"
    }


@app.get(
    "/api/tracking/info"
)
def tracking_info():

    return (
        tracking_engine.info()
    )


@app.get(
    "/api/tracking/frame/{frame_index}"
)
def tracking_frame(
    frame_index: int,
):

    try:

        return (
            tracking_engine.get_frame(
                frame_index
            )
        )

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(
                exc
            ),
        ) from exc


@app.post(
    "/api/tracking/reset"
)
def tracking_reset():

    tracking_engine.reset()

    return {
        "status": "ok",
        **tracking_engine.info(),
    }


@app.post(
    "/api/tracking/reload"
)
def tracking_reload():

    tracking_engine.reload_config()

    return {
        "status": "ok",
        **tracking_engine.info(),
    }


# =========================================================
# Startup
# =========================================================


def print_startup_info() -> None:

    info = (
        tracking_engine.info()
    )

    try:

        relative_cache_path = (
            DETECTION_CACHE_PATH.relative_to(
                ROOT
            )
        )

    except ValueError:

        relative_cache_path = (
            DETECTION_CACHE_PATH
        )

    global_status = (
        "enabled"
        if info[
            "global_tracking"
        ]
        else
        "disabled"
    )

    print()

    print(
        "========================================"
    )

    print(
        "AX PARKING WEB SERVER"
    )

    print(
        "========================================"
    )

    print(
        f"Cameras         : "
        f"{len(info['camera_ids'])}"
    )

    print(
        f"Detection cache : "
        f"{relative_cache_path}"
    )

    print(
        f"Cached frames   : "
        f"{info['frame_count']}"
    )

    print(
        f"Tracking FPS    : "
        f"{info['fps']:.1f}"
    )

    print(
        f"Global tracking : "
        f"{global_status}"
    )

    print(
        f"Global probe    : "
        f"{info['global_probe_motion_sec']:.2f}s"
    )

    print()

    print(
        "Web             : "
        "http://127.0.0.1:8000"
    )

    print(
        "========================================"
    )

    print(
        "Press Ctrl+C to stop."
    )

    print()


# =========================================================
# Main
# =========================================================


if __name__ == "__main__":

    import uvicorn

    print_startup_info()

    try:

        uvicorn.run(

            app,

            host="127.0.0.1",

            port=8000,

            log_level="warning",

            access_log=False,
        )

    except KeyboardInterrupt:

        pass