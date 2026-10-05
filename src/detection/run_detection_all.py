from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

import cv2
import numpy as np
import torch
import yaml


ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )


from src.calibration import CameraProjector
from src.detection.detector import VehicleDetector
from src.tracking import (
    GlobalObservation,
    GlobalTracker,
    LocalTracker,
    TrackState,
)
from src.video.sync_reader import SynchronizedVideoReader


CONFIG_PATH = (
    ROOT
    / "config"
    / "detection.yaml"
)

TRACKING_CONFIG_PATH = (
    ROOT
    / "config"
    / "tracking.yaml"
)

GLOBAL_TRACKING_CONFIG_PATH = (
    ROOT
    / "config"
    / "global_tracking.yaml"
)

BEV_MAP_PATH = (
    ROOT
    / "data"
    / "maps"
    / "map.png"
)

WINDOW_NAME = (
    "AX Parking - Global Tracking + BEV"
)


CAMERA_COLORS = {
    "cam01": (0, 0, 255),
    "cam02": (0, 165, 255),
    "cam03": (0, 255, 255),
    "cam05": (0, 255, 0),
    "cam06": (255, 255, 0),
    "cam07": (255, 0, 0),
    "cam08": (255, 0, 255),
}


STATE_COLORS = {
    TrackState.UNKNOWN: (
        110,
        110,
        110,
    ),
    TrackState.ACTIVE: (
        0,
        255,
        0,
    ),
    TrackState.STOPPED: (
        0,
        255,
        255,
    ),
    TrackState.PARKED: (
        255,
        0,
        255,
    ),
}


# =========================================================
# Cached YOLO detection
# =========================================================


@dataclass
class CachedDetection:
    x1: float
    y1: float
    x2: float
    y2: float

    class_name: str
    confidence: float


class DetectionCacheReader:
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

        self.file: TextIO | None = None
        self.line_number = 0

    def open(
        self,
    ) -> None:
        if self.file is not None:
            return

        self.file = self.path.open(
            "r",
            encoding="utf-8",
        )

        self.line_number = 0

    def close(
        self,
    ) -> None:
        if self.file is None:
            return

        self.file.close()
        self.file = None

    @staticmethod
    def _make_detection(
        data: dict,
    ) -> CachedDetection:
        return CachedDetection(
            x1=float(
                data["x1"]
            ),
            y1=float(
                data["y1"]
            ),
            x2=float(
                data["x2"]
            ),
            y2=float(
                data["y2"]
            ),
            class_name=str(
                data["class_name"]
            ),
            confidence=float(
                data["confidence"]
            ),
        )

    def read_frame(
        self,
        expected_frame_index: int,
        camera_ids: list[str],
    ) -> list[
        list[CachedDetection]
    ]:
        if self.file is None:
            raise RuntimeError(
                "DetectionCacheReader is not open."
            )

        line = self.file.readline()

        if not line:
            raise EOFError(
                "Reached the end of detection cache."
            )

        self.line_number += 1

        try:
            frame_data = json.loads(
                line
            )

        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Invalid JSON in detection cache "
                f"at line {self.line_number}: "
                f"{exc}"
            ) from exc

        cached_frame_index = int(
            frame_data.get(
                "frame_index",
                -1,
            )
        )

        if (
            cached_frame_index
            !=
            expected_frame_index
        ):
            raise RuntimeError(
                "Video/cache frame mismatch.\n"
                f"Video frame : {expected_frame_index}\n"
                f"Cache frame : {cached_frame_index}\n"
                f"Cache line  : {self.line_number}"
            )

        cameras = frame_data.get(
            "cameras",
            {},
        )

        all_detections = []

        for camera_id in camera_ids:
            camera_data = cameras.get(
                camera_id,
                [],
            )

            detections = [
                self._make_detection(
                    detection_data
                )
                for detection_data
                in camera_data
            ]

            all_detections.append(
                detections
            )

        return all_detections


# =========================================================
# Runtime structures
# =========================================================


@dataclass
class TimingStats:
    count: int = 0

    read_total_ms: float = 0.0
    queue_wait_total_ms: float = 0.0
    detection_total_ms: float = 0.0

    local_tracking_total_ms: float = 0.0
    projection_total_ms: float = 0.0
    global_tracking_total_ms: float = 0.0

    draw_total_ms: float = 0.0
    grid_total_ms: float = 0.0
    display_total_ms: float = 0.0

    consumer_loop_total_ms: float = 0.0

    started_at: float = 0.0

    def start(
        self,
    ) -> None:
        self.started_at = (
            time.perf_counter()
        )

    def add(
        self,
        read_ms: float,
        queue_wait_ms: float,
        detection_ms: float,
        local_tracking_ms: float,
        projection_ms: float,
        global_tracking_ms: float,
        draw_ms: float,
        grid_ms: float,
        display_ms: float,
        consumer_loop_ms: float,
    ) -> None:
        self.count += 1

        self.read_total_ms += read_ms
        self.queue_wait_total_ms += queue_wait_ms
        self.detection_total_ms += detection_ms

        self.local_tracking_total_ms += (
            local_tracking_ms
        )

        self.projection_total_ms += (
            projection_ms
        )

        self.global_tracking_total_ms += (
            global_tracking_ms
        )

        self.draw_total_ms += draw_ms
        self.grid_total_ms += grid_ms
        self.display_total_ms += display_ms

        self.consumer_loop_total_ms += (
            consumer_loop_ms
        )

    def average(
        self,
        total: float,
    ) -> float:
        if self.count == 0:
            return 0.0

        return (
            total
            /
            self.count
        )

    @property
    def elapsed_seconds(
        self,
    ) -> float:
        if self.started_at <= 0.0:
            return 0.0

        return (
            time.perf_counter()
            -
            self.started_at
        )

    @property
    def throughput(
        self,
    ) -> float:
        elapsed = (
            self.elapsed_seconds
        )

        if elapsed <= 0.0:
            return 0.0

        return (
            self.count
            /
            elapsed
        )


@dataclass
class BEVDetection:
    camera_id: str
    local_id: int

    state: TrackState

    class_name: str
    confidence: float

    image_x: float
    image_y: float

    bev_x: float
    bev_y: float

    stopped_seconds: float

    global_id: int | None = None


# =========================================================
# Arguments
# =========================================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "AX Parking detection/tracking pipeline."
        )
    )

    parser.add_argument(
        "--source",
        choices=[
            "live",
            "cache",
        ],
        default="live",
        help=(
            "live = run YOLO, "
            "cache = use preprocessed detections"
        ),
    )

    parser.add_argument(
        "--cache",
        type=str,
        default=None,
        help=(
            "Optional path to detections.jsonl."
        ),
    )

    return parser.parse_args()


# =========================================================
# Config
# =========================================================


def load_yaml(
    path: Path,
) -> dict:
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


def load_config() -> dict:
    return load_yaml(
        CONFIG_PATH
    )


def load_tracking_config() -> dict:
    config = load_yaml(
        TRACKING_CONFIG_PATH
    )

    return config.get(
        "local_tracking",
        {},
    )


def load_global_tracking_config() -> dict:
    if not GLOBAL_TRACKING_CONFIG_PATH.exists():
        return {}

    config = load_yaml(
        GLOBAL_TRACKING_CONFIG_PATH
    )

    return config.get(
        "global_tracking",
        {},
    )


def detect_scene_name(
    config: dict,
) -> str:
    videos = config.get(
        "videos",
        [],
    )

    if not videos:
        return "scene"

    video_path = videos[0].get(
        "path",
        "",
    )

    if not video_path:
        return "scene"

    scene_name = Path(
        video_path
    ).parent.name

    if not scene_name:
        return "scene"

    return scene_name


def resolve_cache_path(
    args: argparse.Namespace,
    config: dict,
) -> Path:
    if args.cache:
        path = Path(
            args.cache
        )

        if not path.is_absolute():
            path = (
                ROOT
                /
                path
            )

        return path

    scene_name = (
        detect_scene_name(
            config
        )
    )

    return (
        ROOT
        / "data"
        / "detections"
        / scene_name
        / "detections.jsonl"
    )


# =========================================================
# BEV
# =========================================================


def load_bev_map() -> np.ndarray:
    bev_map = cv2.imread(
        str(
            BEV_MAP_PATH
        ),
        cv2.IMREAD_COLOR,
    )

    if bev_map is None:
        raise RuntimeError(
            "Failed to load BEV map: "
            f"{BEV_MAP_PATH}"
        )

    return bev_map


def load_projectors(
    camera_ids: list[str],
) -> dict[
    str,
    CameraProjector,
]:
    projectors = {}

    print()
    print(
        "======================================"
    )
    print(
        "CAMERA CALIBRATION"
    )
    print(
        "======================================"
    )

    for camera_id in camera_ids:
        try:
            projectors[
                camera_id
            ] = CameraProjector(
                camera_id
            )

            print(
                f"{camera_id}: loaded"
            )

        except Exception as exc:
            print(
                f"{camera_id}: unavailable"
            )

            print(
                f"  {exc}"
            )

    print(
        "======================================"
    )
    print()

    return projectors


# =========================================================
# Local Tracking
# =========================================================


def create_local_trackers(
    camera_ids: list[str],
    config: dict,
) -> dict[
    str,
    LocalTracker,
]:
    trackers = {}

    for camera_id in camera_ids:
        trackers[
            camera_id
        ] = LocalTracker(
            camera_id=camera_id,

            # ---------------------------------------------
            # Association
            # ---------------------------------------------

            match_distance_px=float(
                config.get(
                    "match_distance_px",
                    60.0,
                )
            ),

            match_distance_bbox_ratio=float(
                config.get(
                    "match_distance_bbox_ratio",
                    0.45,
                )
            ),

            match_iou_threshold=float(
                config.get(
                    "match_iou_threshold",
                    0.10,
                )
            ),

            # ---------------------------------------------
            # Motion detection
            # ---------------------------------------------

            motion_window_sec=float(
                config.get(
                    "motion_window_sec",
                    0.8,
                )
            ),

            min_motion_px=float(
                config.get(
                    "min_motion_px",
                    10.0,
                )
            ),

            motion_bbox_ratio=float(
                config.get(
                    "motion_bbox_ratio",
                    0.050,
                )
            ),

            smoothing_window=int(
                config.get(
                    "smoothing_window",
                    7,
                )
            ),

            # ---------------------------------------------
            # UNKNOWN -> ACTIVE
            # ---------------------------------------------

            unknown_to_active_sec=float(
                config.get(
                    "unknown_to_active_sec",
                    0.50,
                )
            ),

            # ---------------------------------------------
            # ACTIVE -> STOPPED
            # ---------------------------------------------

            active_to_stopped_sec=float(
                config.get(
                    "active_to_stopped_sec",
                    1.00,
                )
            ),

            # ---------------------------------------------
            # STOPPED -> ACTIVE
            # ---------------------------------------------

            stopped_motion_multiplier=float(
                config.get(
                    "stopped_motion_multiplier",
                    2.0,
                )
            ),

            stopped_to_active_sec=float(
                config.get(
                    "stopped_to_active_sec",
                    0.70,
                )
            ),

            # ---------------------------------------------
            # STOPPED -> PARKED
            # ---------------------------------------------

            parked_after_sec=float(
                config.get(
                    "parked_after_sec",
                    10.0,
                )
            ),

            stop_anchor_min_px=float(
                config.get(
                    "stop_anchor_min_px",
                    12.0,
                )
            ),

            stop_anchor_bbox_ratio=float(
                config.get(
                    "stop_anchor_bbox_ratio",
                    0.060,
                )
            ),

            # ---------------------------------------------
            # PARKED -> ACTIVE
            # ---------------------------------------------

            parked_motion_multiplier=float(
                config.get(
                    "parked_motion_multiplier",
                    2.8,
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
                    20.0,
                )
            ),

            parked_exit_bbox_ratio=float(
                config.get(
                    "parked_exit_bbox_ratio",
                    0.12,
                )
            ),

            # ---------------------------------------------
            # Track management
            # ---------------------------------------------

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

            print_transitions=bool(
                config.get(
                    "print_transitions",
                    True,
                )
            ),
        )

    return trackers


def print_tracking_config(
    config: dict,
) -> None:
    print()
    print(
        "======================================"
    )
    print(
        "LOCAL TRACKING CONFIG"
    )
    print(
        "======================================"
    )

    keys = [
        "match_distance_px",
        "match_distance_bbox_ratio",
        "match_iou_threshold",
        "motion_window_sec",
        "min_motion_px",
        "motion_bbox_ratio",
        "smoothing_window",
        "unknown_to_active_sec",
        "active_to_stopped_sec",
        "stopped_motion_multiplier",
        "stopped_to_active_sec",
        "parked_after_sec",
        "stop_anchor_min_px",
        "stop_anchor_bbox_ratio",
        "parked_motion_multiplier",
        "parked_to_active_sec",
        "parked_exit_min_px",
        "parked_exit_bbox_ratio",
        "max_missing_sec",
        "nominal_fps",
    ]

    for key in keys:
        print(
            f"{key:<30}: "
            f"{config.get(key)}"
        )

    print(
        "======================================"
    )
    print()


def update_local_tracking(
    camera_ids: list[str],
    all_detections,
    trackers: dict[
        str,
        LocalTracker,
    ],
    timestamp: float,
):
    all_tracked = []

    for (
        camera_id,
        detections,
    ) in zip(
        camera_ids,
        all_detections,
    ):
        tracked = (
            trackers[
                camera_id
            ].update(
                detections=detections,
                timestamp=timestamp,
            )
        )

        all_tracked.append(
            tracked
        )

    return all_tracked


# =========================================================
# BEV projection
# =========================================================


def project_tracked_detections(
    camera_ids: list[str],
    all_tracked,
    projectors: dict[
        str,
        CameraProjector,
    ],
    timestamp: float,
) -> list[
    list[BEVDetection]
]:
    all_bev_detections = []

    for (
        camera_id,
        tracked_detections,
    ) in zip(
        camera_ids,
        all_tracked,
    ):
        camera_results = []

        projector = (
            projectors.get(
                camera_id
            )
        )

        if projector is None:
            all_bev_detections.append(
                camera_results
            )
            continue

        for tracked in (
            tracked_detections
        ):
            track = (
                tracked.track
            )

            if not track.has_moved:
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

            camera_results.append(
                BEVDetection(
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
                    image_x=(
                        track.ground_x
                    ),
                    image_y=(
                        track.ground_y
                    ),
                    bev_x=bev_x,
                    bev_y=bev_y,
                    stopped_seconds=(
                        track.stopped_duration(
                            timestamp
                        )
                    ),
                )
            )

        all_bev_detections.append(
            camera_results
        )

    return all_bev_detections


# =========================================================
# Global tracking
# =========================================================


def create_global_tracker(
    config: dict,
) -> GlobalTracker:
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
                0.25,
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
                1.25,
            )
        ),

        retention_sec=float(
            config.get(
                "retention_sec",
                120.0,
            )
        ),

        print_events=bool(
            config.get(
                "print_events",
                True,
            )
        ),
    )


def update_global_tracking(
    all_bev_detections: list[
        list[BEVDetection]
    ],
    global_tracker: GlobalTracker,
    timestamp: float,
) -> None:
    observations = []

    for camera_detections in (
        all_bev_detections
    ):
        for detection in (
            camera_detections
        ):
            observations.append(
                GlobalObservation(
                    camera_id=(
                        detection.camera_id
                    ),
                    local_id=(
                        detection.local_id
                    ),
                    state=(
                        detection.state
                    ),
                    class_name=(
                        detection.class_name
                    ),
                    confidence=(
                        detection.confidence
                    ),
                    bev_x=(
                        detection.bev_x
                    ),
                    bev_y=(
                        detection.bev_y
                    ),
                    timestamp=timestamp,
                )
            )

    assignments = (
        global_tracker.update(
            observations=observations,
            timestamp=timestamp,
        )
    )

    for camera_detections in (
        all_bev_detections
    ):
        for detection in (
            camera_detections
        ):
            detection.global_id = (
                assignments.get(
                    (
                        detection.camera_id,
                        detection.local_id,
                    )
                )
            )


# =========================================================
# Drawing
# =========================================================


def draw_tracked_detections(
    frame: np.ndarray,
    camera_id: str,
    tracked_detections,
    timestamp: float,
    show_unknown: bool,
    show_confidence: bool,
    line_width: int,
    global_tracker: GlobalTracker,
) -> None:
    for tracked in tracked_detections:
        detection = (
            tracked.detection
        )

        track = (
            tracked.track
        )

        if (
            track.state
            ==
            TrackState.UNKNOWN
            and
            not show_unknown
        ):
            continue

        color = (
            STATE_COLORS[
                track.state
            ]
        )

        x1 = int(
            detection.x1
        )

        y1 = int(
            detection.y1
        )

        x2 = int(
            detection.x2
        )

        y2 = int(
            detection.y2
        )

        cv2.rectangle(
            frame,
            (
                x1,
                y1,
            ),
            (
                x2,
                y2,
            ),
            color,
            line_width,
        )

        ground_x = int(
            round(
                track.ground_x
            )
        )

        ground_y = int(
            round(
                track.ground_y
            )
        )

        cv2.circle(
            frame,
            (
                ground_x,
                ground_y,
            ),
            5,
            color,
            -1,
            cv2.LINE_AA,
        )

        global_id = (
            global_tracker.get_global_id(
                camera_id,
                track.local_id,
            )
        )

        if global_id is None:
            id_label = (
                f"L{track.local_id:03d}"
            )
        else:
            id_label = (
                f"G{global_id:03d} "
                f"/ L{track.local_id:03d}"
            )

        label = (
            f"{id_label} "
            f"{track.state.value}"
        )

        if (
            track.state
            in (
                TrackState.STOPPED,
                TrackState.PARKED,
            )
        ):
            label += (
                f" "
                f"{track.stopped_duration(timestamp):.1f}s"
            )

        if show_confidence:
            label += (
                f" "
                f"{track.class_name} "
                f"{track.confidence:.2f}"
            )

        cv2.putText(
            frame,
            label,
            (
                x1,
                max(
                    20,
                    y1 - 7,
                ),
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.50,
            color,
            2,
            cv2.LINE_AA,
        )


def draw_bev_detections(
    bev_map: np.ndarray,
    all_bev_detections: list[
        list[BEVDetection]
    ],
) -> np.ndarray:
    output = (
        bev_map.copy()
    )

    height, width = (
        output.shape[:2]
    )

    total = 0
    active = 0
    stopped = 0
    parked = 0

    global_ids = set()

    for camera_detections in (
        all_bev_detections
    ):
        for detection in (
            camera_detections
        ):
            x = int(
                round(
                    detection.bev_x
                )
            )

            y = int(
                round(
                    detection.bev_y
                )
            )

            if (
                x < 0
                or
                x >= width
                or
                y < 0
                or
                y >= height
            ):
                continue

            total += 1

            if (
                detection.global_id
                is not None
            ):
                global_ids.add(
                    detection.global_id
                )

            if (
                detection.state
                ==
                TrackState.ACTIVE
            ):
                active += 1

            elif (
                detection.state
                ==
                TrackState.STOPPED
            ):
                stopped += 1

            elif (
                detection.state
                ==
                TrackState.PARKED
            ):
                parked += 1

            state_color = (
                STATE_COLORS[
                    detection.state
                ]
            )

            camera_color = (
                CAMERA_COLORS.get(
                    detection.camera_id,
                    (
                        255,
                        255,
                        255,
                    ),
                )
            )

            cv2.circle(
                output,
                (
                    x,
                    y,
                ),
                11,
                camera_color,
                -1,
                cv2.LINE_AA,
            )

            cv2.circle(
                output,
                (
                    x,
                    y,
                ),
                7,
                state_color,
                -1,
                cv2.LINE_AA,
            )

            if (
                detection.global_id
                is None
            ):
                global_label = (
                    "G---"
                )
            else:
                global_label = (
                    f"G{detection.global_id:03d}"
                )

            label = (
                f"{global_label} "
                f"{detection.camera_id.upper()}"
                f"-L{detection.local_id:03d} "
                f"{detection.state.value}"
            )

            if (
                detection.state
                in (
                    TrackState.STOPPED,
                    TrackState.PARKED,
                )
            ):
                label += (
                    f" "
                    f"{detection.stopped_seconds:.1f}s"
                )

            cv2.putText(
                output,
                label,
                (
                    x + 11,
                    y - 8,
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.43,
                state_color,
                1,
                cv2.LINE_AA,
            )

    info = (
        f"Global {len(global_ids)} | "
        f"Observations {total} | "
        f"ACTIVE {active} | "
        f"STOPPED {stopped} | "
        f"PARKED {parked}"
    )

    cv2.putText(
        output,
        info,
        (
            15,
            30,
        ),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (
            255,
            255,
            255,
        ),
        2,
        cv2.LINE_AA,
    )

    return output


# =========================================================
# Grid
# =========================================================


def fit_frame(
    frame: np.ndarray,
    target_width: int,
    target_height: int,
) -> np.ndarray:
    height, width = (
        frame.shape[:2]
    )

    scale = min(
        target_width / width,
        target_height / height,
    )

    new_width = max(
        1,
        int(
            width
            *
            scale
        ),
    )

    new_height = max(
        1,
        int(
            height
            *
            scale
        ),
    )

    resized = cv2.resize(
        frame,
        (
            new_width,
            new_height,
        ),
        interpolation=cv2.INTER_AREA,
    )

    canvas = np.zeros(
        (
            target_height,
            target_width,
            3,
        ),
        dtype=np.uint8,
    )

    x = (
        target_width
        -
        new_width
    ) // 2

    y = (
        target_height
        -
        new_height
    ) // 2

    canvas[
        y:y + new_height,
        x:x + new_width,
    ] = resized

    return canvas


def make_placeholder(
    width: int,
    height: int,
) -> np.ndarray:
    return np.zeros(
        (
            height,
            width,
            3,
        ),
        dtype=np.uint8,
    )


def compose_grid(
    frames: list[np.ndarray],
    camera_ids: list[str],
    raw_counts: list[int],
    tracked_counts: list[int],
    bev_frame: np.ndarray,
    frame_index: int,
    timestamp: float,
    detection_ms: float,
    source_mode: str,
    display_width: int,
    display_height: int,
    columns: int,
) -> np.ndarray:
    all_frames = list(
        frames
    )

    all_frames.append(
        bev_frame
    )

    rows = math.ceil(
        len(
            all_frames
        )
        /
        columns
    )

    header_height = 34

    cell_width = (
        display_width
        //
        columns
    )

    cell_height = (
        display_height
        //
        rows
    )

    tiles = []

    for index, frame in enumerate(
        all_frames
    ):
        content_height = (
            cell_height
            -
            header_height
        )

        content = fit_frame(
            frame,
            cell_width,
            content_height,
        )

        header = np.zeros(
            (
                header_height,
                cell_width,
                3,
            ),
            dtype=np.uint8,
        )

        if (
            index
            <
            len(
                camera_ids
            )
        ):
            title = (
                f"{camera_ids[index]} | "
                f"det {raw_counts[index]} | "
                f"tracked {tracked_counts[index]}"
            )

        else:
            title = (
                "BEV MAP | GLOBAL TRACKING"
            )

        cv2.putText(
            header,
            title,
            (
                8,
                23,
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.52,
            (
                255,
                255,
                255,
            ),
            1,
            cv2.LINE_AA,
        )

        tiles.append(
            np.vstack(
                [
                    header,
                    content,
                ]
            )
        )

    while (
        len(
            tiles
        )
        <
        rows
        *
        columns
    ):
        tiles.append(
            make_placeholder(
                cell_width,
                cell_height,
            )
        )

    grid_rows = []

    for row_index in range(
        rows
    ):
        start = (
            row_index
            *
            columns
        )

        end = (
            start
            +
            columns
        )

        grid_rows.append(
            np.hstack(
                tiles[
                    start:end
                ]
            )
        )

    grid = np.vstack(
        grid_rows
    )

    source_label = (
        "YOLO"
        if source_mode == "live"
        else "CACHE"
    )

    info = (
        f"frame {frame_index} | "
        f"time {timestamp:.2f}s | "
        f"{source_label} {detection_ms:.2f} ms | "
        f"Q/ESC: quit"
    )

    cv2.putText(
        grid,
        info,
        (
            15,
            grid.shape[0] - 15,
        ),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (
            255,
            255,
            255,
        ),
        2,
        cv2.LINE_AA,
    )

    return grid


# =========================================================
# Performance
# =========================================================


def print_gpu_memory() -> None:
    if not torch.cuda.is_available():
        return

    allocated = (
        torch.cuda.memory_allocated()
        /
        1024**3
    )

    reserved = (
        torch.cuda.memory_reserved()
        /
        1024**3
    )

    peak_allocated = (
        torch.cuda.max_memory_allocated()
        /
        1024**3
    )

    peak_reserved = (
        torch.cuda.max_memory_reserved()
        /
        1024**3
    )

    print(
        "GPU memory | "
        f"allocated={allocated:.2f} GB | "
        f"reserved={reserved:.2f} GB | "
        f"peak allocated={peak_allocated:.2f} GB | "
        f"peak reserved={peak_reserved:.2f} GB"
    )


def print_stats(
    stats: TimingStats,
    camera_count: int,
    source_mode: str,
) -> None:
    if stats.count == 0:
        return

    sets_per_second = (
        stats.throughput
    )

    camera_frames_per_second = (
        sets_per_second
        *
        camera_count
    )

    detection_name = (
        "YOLO inference"
        if source_mode == "live"
        else "Cache read"
    )

    print()
    print(
        "======================================"
    )
    print(
        "PIPELINE PERFORMANCE"
    )
    print(
        "======================================"
    )

    print(
        f"Source              : "
        f"{source_mode}"
    )

    print(
        f"Samples             : "
        f"{stats.count}"
    )

    print(
        f"Video read/thread   : "
        f"{stats.average(stats.read_total_ms):8.2f} ms"
    )

    print(
        f"Queue wait/main     : "
        f"{stats.average(stats.queue_wait_total_ms):8.2f} ms"
    )

    print(
        f"{detection_name:<20}: "
        f"{stats.average(stats.detection_total_ms):8.2f} ms"
    )

    print(
        f"Local tracking      : "
        f"{stats.average(stats.local_tracking_total_ms):8.2f} ms"
    )

    print(
        f"BEV projection      : "
        f"{stats.average(stats.projection_total_ms):8.2f} ms"
    )

    print(
        f"Global tracking     : "
        f"{stats.average(stats.global_tracking_total_ms):8.2f} ms"
    )

    print(
        f"Drawing             : "
        f"{stats.average(stats.draw_total_ms):8.2f} ms"
    )

    print(
        f"Grid compose        : "
        f"{stats.average(stats.grid_total_ms):8.2f} ms"
    )

    print(
        f"imshow/waitKey      : "
        f"{stats.average(stats.display_total_ms):8.2f} ms"
    )

    print(
        f"Consumer loop       : "
        f"{stats.average(stats.consumer_loop_total_ms):8.2f} ms"
    )

    print(
        "--------------------------------------"
    )

    print(
        f"Real sets/s         : "
        f"{sets_per_second:.2f}"
    )

    print(
        f"Camera frames/s     : "
        f"{camera_frames_per_second:.2f}"
    )

    print(
        "======================================"
    )


# =========================================================
# Main
# =========================================================


def main() -> None:
    args = parse_args()

    config = (
        load_config()
    )

    tracking_config = (
        load_tracking_config()
    )

    global_tracking_config = (
        load_global_tracking_config()
    )

    pipeline_config = (
        config.get(
            "pipeline",
            {},
        )
    )

    profile_config = (
        config.get(
            "profile",
            {},
        )
    )

    display_config = (
        config.get(
            "display",
            {},
        )
    )

    queue_size = int(
        pipeline_config.get(
            "queue_size",
            2,
        )
    )

    print_interval = int(
        profile_config.get(
            "print_interval",
            100,
        )
    )

    show = bool(
        display_config.get(
            "show",
            False,
        )
    )

    render = bool(
        display_config.get(
            "render",
            False,
        )
    )

    show_confidence = bool(
        display_config.get(
            "show_confidence",
            True,
        )
    )

    line_width = int(
        display_config.get(
            "line_width",
            2,
        )
    )

    columns = int(
        display_config.get(
            "grid_columns",
            4,
        )
    )

    display_width = int(
        display_config.get(
            "width",
            1600,
        )
    )

    display_height = int(
        display_config.get(
            "height",
            850,
        )
    )

    show_unknown = bool(
        tracking_config.get(
            "show_unknown",
            False,
        )
    )

    global_enabled = bool(
        global_tracking_config.get(
            "enabled",
            True,
        )
    )

    # -----------------------------------------------------
    # Detection source
    # -----------------------------------------------------

    detector = None
    cache_reader = None
    cache_path = None

    if args.source == "live":
        detector = VehicleDetector(
            CONFIG_PATH
        )

    else:
        cache_path = (
            resolve_cache_path(
                args,
                config,
            )
        )

        cache_reader = (
            DetectionCacheReader(
                cache_path
            )
        )

        cache_reader.open()

    print()
    print(
        "======================================"
    )
    print(
        "PIPELINE MODE"
    )
    print(
        "======================================"
    )

    print(
        f"Detection source : "
        f"{args.source}"
    )

    if cache_path is not None:
        print(
            f"Detection cache  : "
            f"{cache_path}"
        )

    print(
        f"Render enabled   : "
        f"{render}"
    )

    print(
        f"Display enabled  : "
        f"{show}"
    )

    print(
        f"Global tracking  : "
        f"{global_enabled}"
    )

    print(
        "======================================"
    )

    print_tracking_config(
        tracking_config
    )

    # -----------------------------------------------------
    # Video
    # -----------------------------------------------------

    reader = (
        SynchronizedVideoReader(
            video_configs=(
                config[
                    "videos"
                ]
            ),
            root=ROOT,
            queue_size=queue_size,
        )
    )

    reader.print_info()

    # -----------------------------------------------------
    # Tracking
    # -----------------------------------------------------

    bev_map = (
        load_bev_map()
    )

    projectors = (
        load_projectors(
            reader.camera_ids
        )
    )

    local_trackers = (
        create_local_trackers(
            camera_ids=(
                reader.camera_ids
            ),
            config=(
                tracking_config
            ),
        )
    )

    global_tracker = (
        create_global_tracker(
            global_tracking_config
        )
    )

    stats = (
        TimingStats()
    )

    if (
        torch.cuda.is_available()
        and
        args.source == "live"
    ):
        torch.cuda.reset_peak_memory_stats()

    if show and render:
        cv2.namedWindow(
            WINDOW_NAME,
            cv2.WINDOW_NORMAL,
        )

        cv2.resizeWindow(
            WINDOW_NAME,
            display_width,
            display_height,
        )

    reader.start()
    stats.start()

    try:
        while True:
            consumer_start = (
                time.perf_counter()
            )

            queue_wait_start = (
                time.perf_counter()
            )

            frame_set = (
                reader.get()
            )

            queue_wait_ms = (
                (
                    time.perf_counter()
                    -
                    queue_wait_start
                )
                *
                1000.0
            )

            if frame_set is None:
                break

            # =================================================
            # Detection
            # =================================================

            detection_start = (
                time.perf_counter()
            )

            if args.source == "live":
                if detector is None:
                    raise RuntimeError(
                        "Detector is not initialized."
                    )

                all_detections = (
                    detector.detect_batch(
                        frame_set.frames
                    )
                )

                if torch.cuda.is_available():
                    torch.cuda.synchronize()

            else:
                if cache_reader is None:
                    raise RuntimeError(
                        "Cache reader is not initialized."
                    )

                try:
                    all_detections = (
                        cache_reader.read_frame(
                            expected_frame_index=(
                                frame_set.frame_index
                            ),
                            camera_ids=(
                                reader.camera_ids
                            ),
                        )
                    )

                except EOFError:
                    print()
                    print(
                        "Detection cache reached EOF."
                    )
                    break

            detection_ms = (
                (
                    time.perf_counter()
                    -
                    detection_start
                )
                *
                1000.0
            )

            # =================================================
            # Local tracking
            # =================================================

            start = (
                time.perf_counter()
            )

            all_tracked = (
                update_local_tracking(
                    camera_ids=(
                        reader.camera_ids
                    ),
                    all_detections=(
                        all_detections
                    ),
                    trackers=(
                        local_trackers
                    ),
                    timestamp=(
                        frame_set.timestamp
                    ),
                )
            )

            local_tracking_ms = (
                (
                    time.perf_counter()
                    -
                    start
                )
                *
                1000.0
            )

            # =================================================
            # BEV
            # =================================================

            start = (
                time.perf_counter()
            )

            all_bev_detections = (
                project_tracked_detections(
                    camera_ids=(
                        reader.camera_ids
                    ),
                    all_tracked=(
                        all_tracked
                    ),
                    projectors=(
                        projectors
                    ),
                    timestamp=(
                        frame_set.timestamp
                    ),
                )
            )

            projection_ms = (
                (
                    time.perf_counter()
                    -
                    start
                )
                *
                1000.0
            )

            # =================================================
            # Global tracking
            # =================================================

            start = (
                time.perf_counter()
            )

            if global_enabled:
                update_global_tracking(
                    all_bev_detections=(
                        all_bev_detections
                    ),
                    global_tracker=(
                        global_tracker
                    ),
                    timestamp=(
                        frame_set.timestamp
                    ),
                )

            global_tracking_ms = (
                (
                    time.perf_counter()
                    -
                    start
                )
                *
                1000.0
            )

            # =================================================
            # Render
            # =================================================

            draw_ms = 0.0
            grid_ms = 0.0
            display_ms = 0.0

            key = 255

            if render:
                start = (
                    time.perf_counter()
                )

                display_frames = []
                raw_counts = []
                tracked_counts = []

                for (
                    camera_id,
                    frame,
                    detections,
                    tracked_detections,
                ) in zip(
                    reader.camera_ids,
                    frame_set.frames,
                    all_detections,
                    all_tracked,
                ):
                    output = (
                        frame.copy()
                    )

                    draw_tracked_detections(
                        frame=output,
                        camera_id=camera_id,
                        tracked_detections=(
                            tracked_detections
                        ),
                        timestamp=(
                            frame_set.timestamp
                        ),
                        show_unknown=(
                            show_unknown
                        ),
                        show_confidence=(
                            show_confidence
                        ),
                        line_width=(
                            line_width
                        ),
                        global_tracker=(
                            global_tracker
                        ),
                    )

                    display_frames.append(
                        output
                    )

                    raw_counts.append(
                        len(
                            detections
                        )
                    )

                    tracked_counts.append(
                        sum(
                            1
                            for tracked
                            in tracked_detections
                            if tracked.track.has_moved
                        )
                    )

                bev_output = (
                    draw_bev_detections(
                        bev_map=(
                            bev_map
                        ),
                        all_bev_detections=(
                            all_bev_detections
                        ),
                    )
                )

                draw_ms = (
                    (
                        time.perf_counter()
                        -
                        start
                    )
                    *
                    1000.0
                )

                start = (
                    time.perf_counter()
                )

                display_frame = (
                    compose_grid(
                        frames=(
                            display_frames
                        ),
                        camera_ids=(
                            reader.camera_ids
                        ),
                        raw_counts=(
                            raw_counts
                        ),
                        tracked_counts=(
                            tracked_counts
                        ),
                        bev_frame=(
                            bev_output
                        ),
                        frame_index=(
                            frame_set.frame_index
                        ),
                        timestamp=(
                            frame_set.timestamp
                        ),
                        detection_ms=(
                            detection_ms
                        ),
                        source_mode=(
                            args.source
                        ),
                        display_width=(
                            display_width
                        ),
                        display_height=(
                            display_height
                        ),
                        columns=(
                            columns
                        ),
                    )
                )

                grid_ms = (
                    (
                        time.perf_counter()
                        -
                        start
                    )
                    *
                    1000.0
                )

                if show:
                    start = (
                        time.perf_counter()
                    )

                    cv2.imshow(
                        WINDOW_NAME,
                        display_frame,
                    )

                    key = (
                        cv2.waitKey(1)
                        &
                        0xFF
                    )

                    display_ms = (
                        (
                            time.perf_counter()
                            -
                            start
                        )
                        *
                        1000.0
                    )

            consumer_loop_ms = (
                (
                    time.perf_counter()
                    -
                    consumer_start
                )
                *
                1000.0
            )

            stats.add(
                read_ms=(
                    frame_set.read_time_ms
                ),
                queue_wait_ms=(
                    queue_wait_ms
                ),
                detection_ms=(
                    detection_ms
                ),
                local_tracking_ms=(
                    local_tracking_ms
                ),
                projection_ms=(
                    projection_ms
                ),
                global_tracking_ms=(
                    global_tracking_ms
                ),
                draw_ms=(
                    draw_ms
                ),
                grid_ms=(
                    grid_ms
                ),
                display_ms=(
                    display_ms
                ),
                consumer_loop_ms=(
                    consumer_loop_ms
                ),
            )

            if (
                stats.count
                %
                print_interval
                ==
                0
            ):
                print_stats(
                    stats,
                    len(
                        reader.cameras
                    ),
                    args.source,
                )

            if key in (
                ord("q"),
                27,
            ):
                break

    except KeyboardInterrupt:
        print()
        print(
            "Interrupted by user."
        )

    finally:
        reader.stop()

        if cache_reader is not None:
            cache_reader.close()

        cv2.destroyAllWindows()

    print()
    print(
        "7-camera detection/tracking pipeline finished."
    )

    print_stats(
        stats,
        len(
            reader.cameras
        ),
        args.source,
    )

    if args.source == "live":
        print_gpu_memory()


if __name__ == "__main__":
    main()