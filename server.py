from __future__ import annotations

import asyncio
import copy
import itertools
import json
import math
import threading

from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import cv2
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
from src.mosaic import MosaicVideo, default_title, load_video
from src.view_mode import VIEW_MODES_FILENAME, ViewModes

from src.tracking.parking_log import ParkingLog
from src.tracking import (
    EntryGate,
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

GATE_CONFIG_PATH = ROOT / "config" / "gate.yaml"



# 탐색 시 입구에서 발급한 ID를 잃지 않도록 추적 상태를 주기적으로 저장한다.
TRACKING_CHECKPOINT_INTERVAL_FRAMES = 300


PARKING_EVENT_LABELS = {
    "PARKED": "주차",
    "LOST": "주차(추정)",
    "LEFT": "출발",
}


def format_parking_event(
    event: dict,
) -> str:

    minutes, seconds = divmod(event["time"], 60.0)

    text = (
        f"[PARKING] {int(minutes):02d}:{seconds:06.3f} "
        f"G{event['global_id']:03d} [{event['plate']}] "
        f"{PARKING_EVENT_LABELS.get(event['type'], event['type'])} "
        f"{event['zone']}구역 -> {event['zone']} "
        f"{event['count']}/{event['capacity']}"
    )

    if event["type"] == "LOST":

        text += (
            f" (마지막 위치 ({event['x']:.0f}, {event['y']:.0f})"
            f" 기준 가장 가까운 구역)"
        )

    return text


class FrameRequestCancelled(Exception):
    """더 최근의 frame 요청이 들어와 계산을 중단함."""


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


def load_json_file(
    path: Path,
) -> dict:

    if not path.exists():

        print(f"[WARN] {path} not found")

        return {}

    with path.open("r", encoding="utf-8") as file:

        return json.load(file)


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

    # 축소 모드 프레임에서 전체 화면 좌표로 바꾼 경우의 원래 검출 (화면 표시용).
    raw: CachedDetection | None = None


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
        scene: MosaicVideo,
    ):

        self.lock = (
            threading.RLock()
        )

        # 원본은 모자이크 영상 1개 (data/videos/raw/<title>.mp4).
        # 카메라 = config/mosaic.yaml 의 칸, 좌표 = 잘라낸 칸 기준 픽셀.
        self.scene = scene

        self.cache_path = (
            scene.detections_dir
            /
            "detections.jsonl"
        )

        self.cache = (
            DetectionCacheStore(
                self.cache_path
            )
        )

        self.camera_ids = (
            scene.camera_ids
        )

        # 축소 모드(좌우 검은 띠) 프레임 기록. tracking은 전체 화면 좌표를 쓴다.
        self.view_modes = ViewModes.load(
            scene.detections_dir / VIEW_MODES_FILENAME
        )

        if self.view_modes is None:
            print(
                f"[WARN] {VIEW_MODES_FILENAME} not found. "
                "Letterboxed frames are tracked in raw coordinates. "
                f"Run: python scripts/detect_view_modes.py {scene.name}"
            )

        (
            self.mosaic_width,
            self.mosaic_height,
        ) = self._read_mosaic_size()

        # 웹 오버레이가 bbox를 칸 위치로 옮겨 그릴 때 사용.
        self.crop_rects = (
            scene.crop_rects(
                self.mosaic_width,
                self.mosaic_height,
            )
        )

        # reload_config()에서 calibration 파일을 읽어 채운다.
        self.projectors: dict[
            str,
            CameraProjector,
        ] = {}

        self.tracking_config: dict = {}

        self.global_tracking_config: dict = {}
        self.gate_config: dict = {}

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

        self.seek_warmup_frames = 0  # info API의 기존 필드 유지
        self.checkpoints: dict[int, tuple] = {}

        # 콘솔에 출력한 마지막 주차 기록 프레임 (재계산 시 중복 출력 방지)
        self.parking_printed_frame = -1

        # frame 요청마다 번호를 붙이고, 처리 중에 더 최근 요청이 들어오면
        # 이전 요청은 계산을 중단한다 (재생바를 여러 번 옮긴 경우 마지막만 처리).
        self.request_counter = itertools.count(1)

        self.latest_request = 0

        self.current_frame = -1

        self.last_result: (
            dict
            |
            None
        ) = None

        self.reload_config()

    def _read_mosaic_size(
        self,
    ) -> tuple[int, int]:

        capture = cv2.VideoCapture(
            str(
                self.scene.video_path
            )
        )

        if not capture.isOpened():

            raise RuntimeError(
                "Failed to open mosaic video: "
                f"{self.scene.video_path}"
            )

        width = int(
            capture.get(
                cv2.CAP_PROP_FRAME_WIDTH
            )
        )

        height = int(
            capture.get(
                cv2.CAP_PROP_FRAME_HEIGHT
            )
        )

        capture.release()

        return (
            width,
            height,
        )

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

            self.gate_config = load_yaml(GATE_CONFIG_PATH)

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

            self._reset_runtime()

    def _reset_runtime(
        self,
    ) -> None:

        self.local_trackers = (
            self._create_local_trackers()
        )
        # 구역별 주차 대수 / 주차 기록 (data/maps/zones.json)
        self.parking_log = ParkingLog(
            load_json_file(MAP_DIR / "zones.json").get("zones", []),
            lost_after_sec=float(
                self.global_tracking_config.get("parking_lost_after_sec", 10.0)
            ),
            exit_camera_ids=(self.gate_config["camera_id"],),
        )

        gate_rect = self.crop_rects[self.gate_config["camera_id"]]
        self.entry_gate = EntryGate(
            self.gate_config,
            camera_size=(gate_rect[2] - gate_rect[0], gate_rect[3] - gate_rect[1]),
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
        self.checkpoints.clear()

    def _save_checkpoint(self) -> None:
        self.checkpoints[self.current_frame] = copy.deepcopy((
            self.local_trackers,
            self.global_tracker,
            self.entry_gate,
            self.parking_log,
            self.last_result,
        ))

    def _restore_checkpoint(self, frame_index: int) -> None:
        (self.local_trackers, self.global_tracker, self.entry_gate,
         self.parking_log, self.last_result) = copy.deepcopy(
            self.checkpoints[frame_index])
        self.current_frame = frame_index

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
                    camera_id,
                    calibration_dir=(
                        self.scene.calibration_dir
                    ),
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

            self._reset_runtime()

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
                unknown_motion_gap_sec=float(config.get("unknown_motion_gap_sec", 0.25)),

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
            last_position_match_distance_px=float(
                config.get("last_position_match_distance_px", 200.0)
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
            probe_handoff_grace_sec=float(config.get("probe_handoff_grace_sec", 2.0)),

            overlap_match_distance_px=float(config.get("overlap_match_distance_px", 120.0)),
            overlap_window_sec=float(config.get("overlap_window_sec", 0.5)),
            overlap_score_bonus=float(config.get("overlap_score_bonus", 0.15)),
            handoff_confirmation_frames=int(config.get("handoff_confirmation_frames", 3)),
            entry_camera_id=self.entry_gate.camera_id,

            bev_motion_window_sec=float(config.get("bev_motion_window_sec", 1.0)),
            bev_motion_min_px=float(config.get("bev_motion_min_px", 30.0)),
            bev_motion_min_straightness=float(
                config.get("bev_motion_min_straightness", 0.8)),
            bev_motion_max_angle_deg=float(config.get("bev_motion_max_angle_deg", 45.0)),
            bev_motion_max_speed_ratio=float(
                config.get("bev_motion_max_speed_ratio", 2.5)),

            print_events=False,
        )

    # =====================================================
    # Checkpoints
    # =====================================================

    # =====================================================
    # Detection conversion
    # =====================================================

    def _to_full_view(
        self,
        detection: CachedDetection,
    ) -> CachedDetection:

        return CachedDetection(
            x1=self.view_modes.to_full_x(detection.x1),
            y1=detection.y1,
            x2=self.view_modes.to_full_x(detection.x2),
            y2=detection.y2,
            class_name=detection.class_name,
            confidence=detection.confidence,
            raw=detection,
        )

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
        entry_eligible: bool = False,
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
            entry_eligible=entry_eligible,
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

        if track.occluded:
            return False

        # 후보 GID가 있으면 이미지 움직임 판정과 관계없이 BEV 위치를 계속 모은다.
        # (카메라 쪽으로 다가오는 먼 차량은 이미지에서 거의 움직이지 않는다)
        if (
            self.global_tracker is not None
            and self.global_tracker.get_provisional_global_id(
                track.camera_id,
                track.local_id,
            ) is not None
        ):

            return True

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

            if (
                self.view_modes is not None
                and self.view_modes.letterboxed(camera_id, frame_index)
            ):
                detections = [
                    self._to_full_view(detection)
                    for detection in detections
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

                entry_eligible = self.entry_gate.observe(track, timestamp)

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
                        entry_eligible,
                    )
                )

                bev_item = {

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

                if track.has_moved:

                    confirmed_observations.append(
                        observation
                    )

                    bev_items.append(bev_item)

                elif should_probe:

                    probe_observations.append(
                        (observation, track, bev_item)
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

            # 후보 GID가 있는 UNKNOWN 차량이 BEV에서 꾸준히 움직이고
            # 속도 벡터가 그 GID와 비슷하면 ACTIVE를 기다리지 않고 확정 매칭으로 넘긴다.
            # 이미 GID를 받은 UNKNOWN 차량도 계속 관측을 보낸다.
            for observation, track, bev_item in probe_observations:

                candidate_id = self.global_tracker.probe_existing(
                    observation
                )

                if candidate_id is None:
                    continue

                if (
                    self.global_tracker.get_global_id(*observation.local_key)
                    is not None
                    or (
                        # 완전히 정지한 차량은 BEV 좌표가 튀어도 이어받지 않는다.
                        track.moving_candidate_since is not None
                        and self.global_tracker.bev_motion_matches(
                            observation.local_key,
                            candidate_id,
                        )
                    )
                ):

                    confirmed_observations.append(observation)
                    bev_items.append(bev_item)

            assignments = (
                self.global_tracker.update(

                    observations=(
                        confirmed_observations
                    ),

                    timestamp=timestamp,
                )
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
        # 4-1. Parking Log (구역별 주차 대수)
        # -------------------------------------------------

        new_parking_events = self.parking_log.update(
            frame_index,
            timestamp,
            bev_items,
        )

        # 재생바를 뒤로 옮겨 다시 계산할 때는 같은 기록을 다시 출력하지 않는다.
        for event in new_parking_events:

            if event["frame"] > self.parking_printed_frame:

                print(format_parking_event(event))

                self.parking_printed_frame = event["frame"]

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

                # 화면에는 영상에 실제로 찍힌 좌표로 그린다.
                detection = (
                    tracked.detection.raw
                    or tracked.detection
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

            "parking":
                self.parking_log.snapshot(),
        }

        self.current_frame = (
            frame_index
        )

        self.last_result = (
            result
        )

        return result

    # =====================================================
    # Public Frame Access
    # =====================================================

    def get_frame(
        self,
        target_frame: int,
    ) -> dict:

        # lock 밖에서 번호를 갱신해야
        # 처리 중인 이전 요청이 바로 알아채고 중단한다.
        request_id = next(
            self.request_counter
        )

        self.latest_request = request_id

        with self.lock:

            return self._advance_to(
                target_frame,
                request_id,
            )

    def get_frames(
        self,
        start_frame: int,
        count: int,
    ) -> list[dict]:
        """
        start_frame부터 연속된 count개 프레임 결과.
        재생 중 웹이 프레임마다 요청하지 않고 한 번에 미리 받아 둔다.
        """

        request_id = next(
            self.request_counter
        )

        self.latest_request = request_id

        with self.lock:

            start_frame = max(0, int(start_frame))
            end_frame = min(
                start_frame + max(1, int(count)),
                self.cache.frame_count,
            )

            return [
                self._advance_to(frame_index, request_id)
                for frame_index in range(start_frame, end_frame)
            ]

    def _advance_to(
        self,
        target_frame: int,
        request_id: int,
    ) -> dict:

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

        # 앞으로 이동할 때는 빠진 프레임도 계산해 입구 ID를 보존한다.
        # 뒤로 이동할 때는 가장 가까운 이전 체크포인트부터 재계산한다.
        if target_frame < self.current_frame:
            previous_checkpoints = self.checkpoints.copy()
            checkpoint_frame = max(
                (frame for frame in previous_checkpoints if frame <= target_frame),
                default=None,
            )
            if checkpoint_frame is None:
                self._reset_runtime()
                self.checkpoints = previous_checkpoints
            else:
                self._restore_checkpoint(checkpoint_frame)

        result = None

        for frame_index in range(
            self.current_frame + 1,
            target_frame + 1,
        ):

            if (
                self.latest_request
                !=
                request_id
            ):

                raise FrameRequestCancelled(
                    f"frame {target_frame} request superseded"
                )

            result = (
                self._process_frame(
                    frame_index
                )
            )

            if frame_index % TRACKING_CHECKPOINT_INTERVAL_FRAMES == 0:
                self._save_checkpoint()

        if result is None:
            return self.last_result

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

            "seek_warmup_frames":
                int(
                    self.seek_warmup_frames
                ),

            "global_tracking":
                bool(
                    self.global_enabled
                ),

            "global_probe_motion_sec":
                float(
                    self.global_probe_motion_sec
                ),

            "scene":
                self.scene_info(),
        }

    def scene_info(
        self,
    ) -> dict:
        """
        웹 재생용 모자이크 정보.
        rect는 모자이크 픽셀 좌표 [x1, y1, x2, y2].
        """

        video_url = (
            "/media/"
            +
            self.scene.video_path
            .relative_to(VIDEO_DIR)
            .as_posix()
        )

        return {

            "name":
                self.scene.name,

            "video_url":
                video_url,

            "width":
                self.mosaic_width,

            "height":
                self.mosaic_height,

            "rows":
                self.scene.rows,

            "cols":
                self.scene.cols,

            "cameras": [
                {
                    "id":
                        camera_id,

                    "rect":
                        list(
                            self.crop_rects[
                                camera_id
                            ]
                        ),
                }
                for camera_id
                in self.camera_ids
            ],
        }


# =========================================================
# Engine
# =========================================================


# 처리할 원본 영상은 config/detection.yaml 의 video 값(영상 제목)으로 정한다.
VIDEO_TITLE = default_title()

if not VIDEO_TITLE:

    raise RuntimeError(
        "Set 'video' (raw video title) in "
        f"{DETECTION_CONFIG_PATH}"
    )

tracking_engine = (
    TrackingEngine(
        load_video(
            VIDEO_TITLE
        )
    )
)

DETECTION_CACHE_PATH = (
    tracking_engine.cache_path
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

    except FrameRequestCancelled as exc:

        # 웹은 이미 더 최근 frame을 요청했으므로 이 응답은 쓰지 않는다.
        raise HTTPException(
            status_code=409,
            detail=str(
                exc
            ),
        ) from exc

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(
                exc
            ),
        ) from exc


@app.get(
    "/api/tracking/frames/{start_frame}"
)
def tracking_frames(
    start_frame: int,
    count: int = 30,
):

    try:

        return tracking_engine.get_frames(
            start_frame,
            min(max(count, 1), 120),
        )

    except FrameRequestCancelled as exc:

        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
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


@app.get(
    "/api/gate-log"
)
def gate_log():
    """
    차단기 입출차 기록 (data/gate_logs/<title>.json).

    이벤트마다 frame(영상 프레임 번호)이 있으며,
    웹은 화면에 표시된 프레임까지의 기록만 보여 주는 방식으로 영상과 동기화한다.
    파일이 없으면 빈 기록을 돌려준다. 요청마다 다시 읽으므로 수정 즉시 반영된다.
    """

    path = (
        tracking_engine.scene.gate_log_path
    )

    if not path.exists():

        return {
            "video":
                tracking_engine.scene.name,

            "gate":
                None,

            "events":
                [],
        }

    try:

        with path.open(
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(
                file
            )

    except (OSError, json.JSONDecodeError) as exc:

        raise HTTPException(
            status_code=500,
            detail=(
                f"Failed to read gate log: {exc}"
            ),
        ) from exc

    data["events"] = sorted(
        data.get(
            "events",
            [],
        ),
        key=lambda event: int(
            event["frame"]
        ),
    )

    return data


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
        f"Video           : "
        f"{info['scene']['name']} "
        f"({info['scene']['video_url']})"
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
