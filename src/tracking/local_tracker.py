from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np


class TrackState(str, Enum):
    UNKNOWN = "UNKNOWN"
    ACTIVE = "ACTIVE"
    STOPPED = "STOPPED"
    PARKED = "PARKED"


@dataclass
class PositionSample:
    timestamp: float
    x: float
    y: float


@dataclass
class LocalTrack:
    local_id: int
    camera_id: str

    bbox: tuple[
        float,
        float,
        float,
        float,
    ]

    class_name: str
    confidence: float

    first_seen: float
    last_seen: float

    state: TrackState = TrackState.UNKNOWN

    # 한 번이라도 확실하게 실제 이동이 확인되었는지.
    has_moved: bool = False

    # 마지막 ACTIVE 이동이 확정된 시각.
    last_moving_at: float | None = None

    # 연속 정지가 시작된 시각.
    stopped_since: float | None = None

    # 움직임이 시작됐을 가능성이 있는 시각.
    moving_candidate_since: float | None = None

    # ACTIVE 차량이 정지하기 시작했을 가능성이 있는 시각.
    stationary_candidate_since: float | None = None

    # STOPPED 상태에서 연속 정지를 확인하기 위한 기준 위치.
    stop_anchor_x: float | None = None
    stop_anchor_y: float | None = None

    # PARKED 확정 위치.
    parked_anchor_x: float | None = None
    parked_anchor_y: float | None = None

    raw_history: deque[PositionSample] = field(
        default_factory=deque
    )

    smoothed_history: deque[PositionSample] = field(
        default_factory=deque
    )

    @property
    def label(
        self,
    ) -> str:
        return (
            f"{self.camera_id.upper()}"
            f"-L{self.local_id:03d}"
        )

    @property
    def x1(
        self,
    ) -> float:
        return self.bbox[0]

    @property
    def y1(
        self,
    ) -> float:
        return self.bbox[1]

    @property
    def x2(
        self,
    ) -> float:
        return self.bbox[2]

    @property
    def y2(
        self,
    ) -> float:
        return self.bbox[3]

    @property
    def width(
        self,
    ) -> float:
        return max(
            1.0,
            self.x2 - self.x1,
        )

    @property
    def height(
        self,
    ) -> float:
        return max(
            1.0,
            self.y2 - self.y1,
        )

    @property
    def diagonal(
        self,
    ) -> float:
        return math.hypot(
            self.width,
            self.height,
        )

    @property
    def raw_ground_x(
        self,
    ) -> float:
        return (
            self.x1
            +
            self.x2
        ) / 2.0

    @property
    def raw_ground_y(
        self,
    ) -> float:
        return self.y2

    @property
    def ground_x(
        self,
    ) -> float:
        if self.smoothed_history:
            return (
                self.smoothed_history[-1].x
            )

        return self.raw_ground_x

    @property
    def ground_y(
        self,
    ) -> float:
        if self.smoothed_history:
            return (
                self.smoothed_history[-1].y
            )

        return self.raw_ground_y

    def stopped_duration(
        self,
        timestamp: float,
    ) -> float:
        if self.stopped_since is None:
            return 0.0

        return max(
            0.0,
            timestamp - self.stopped_since,
        )


@dataclass
class TrackedDetection:
    detection: Any
    track: LocalTrack


@dataclass
class DetectionCandidate:
    index: int

    bbox: tuple[
        float,
        float,
        float,
        float,
    ]

    ground_x: float
    ground_y: float

    class_name: str
    confidence: float

    detection: Any


class LocalTracker:
    def __init__(
        self,
        camera_id: str,

        match_distance_px: float = 80.0,
        match_distance_bbox_ratio: float = 0.60,
        match_iou_threshold: float = 0.10,

        motion_window_sec: float = 0.8,
        min_motion_px: float = 7.0,
        motion_bbox_ratio: float = 0.035,

        smoothing_window: int = 7,

        unknown_to_active_sec: float = 0.35,
        stopped_to_active_sec: float = 0.50,
        parked_to_active_sec: float = 1.00,

        stopped_motion_multiplier: float = 1.6,
        parked_motion_multiplier: float = 2.2,

        parked_after_sec: float = 10.0,

        max_missing_sec: float = 1.5,

        print_transitions: bool = True,

        # 신규 값.
        active_to_stopped_sec: float = 1.0,

        stop_anchor_min_px: float = 12.0,
        stop_anchor_bbox_ratio: float = 0.06,

        parked_exit_min_px: float = 20.0,
        parked_exit_bbox_ratio: float = 0.12,

        nominal_fps: float = 30.0,
    ):
        self.camera_id = camera_id

        self.match_distance_px = float(
            match_distance_px
        )

        self.match_distance_bbox_ratio = float(
            match_distance_bbox_ratio
        )

        self.match_iou_threshold = float(
            match_iou_threshold
        )

        self.motion_window_sec = float(
            motion_window_sec
        )

        self.min_motion_px = float(
            min_motion_px
        )

        self.motion_bbox_ratio = float(
            motion_bbox_ratio
        )

        self.smoothing_window = max(
            1,
            int(
                smoothing_window
            ),
        )

        self.unknown_to_active_sec = float(
            unknown_to_active_sec
        )

        self.stopped_to_active_sec = float(
            stopped_to_active_sec
        )

        self.parked_to_active_sec = float(
            parked_to_active_sec
        )

        self.stopped_motion_multiplier = float(
            stopped_motion_multiplier
        )

        self.parked_motion_multiplier = float(
            parked_motion_multiplier
        )

        self.parked_after_sec = float(
            parked_after_sec
        )

        self.max_missing_sec = float(
            max_missing_sec
        )

        self.print_transitions = bool(
            print_transitions
        )

        self.active_to_stopped_sec = float(
            active_to_stopped_sec
        )

        self.stop_anchor_min_px = float(
            stop_anchor_min_px
        )

        self.stop_anchor_bbox_ratio = float(
            stop_anchor_bbox_ratio
        )

        self.parked_exit_min_px = float(
            parked_exit_min_px
        )

        self.parked_exit_bbox_ratio = float(
            parked_exit_bbox_ratio
        )

        self.nominal_fps = max(
            1.0,
            float(
                nominal_fps
            ),
        )

        self.tracks: dict[
            int,
            LocalTrack,
        ] = {}

        self.next_local_id = 1

    # =====================================================
    # Detection geometry
    # =====================================================

    @staticmethod
    def _bbox_from_detection(
        detection,
    ) -> tuple[
        float,
        float,
        float,
        float,
    ]:
        return (
            float(
                detection.x1
            ),
            float(
                detection.y1
            ),
            float(
                detection.x2
            ),
            float(
                detection.y2
            ),
        )

    @staticmethod
    def _bbox_diagonal(
        bbox: tuple[
            float,
            float,
            float,
            float,
        ],
    ) -> float:
        x1, y1, x2, y2 = bbox

        width = max(
            1.0,
            x2 - x1,
        )

        height = max(
            1.0,
            y2 - y1,
        )

        return math.hypot(
            width,
            height,
        )

    @staticmethod
    def _ground_point(
        bbox: tuple[
            float,
            float,
            float,
            float,
        ],
    ) -> tuple[
        float,
        float,
    ]:
        x1, _, x2, y2 = bbox

        return (
            (
                x1
                +
                x2
            )
            /
            2.0,
            y2,
        )

    @staticmethod
    def _iou(
        bbox_a: tuple[
            float,
            float,
            float,
            float,
        ],
        bbox_b: tuple[
            float,
            float,
            float,
            float,
        ],
    ) -> float:
        ax1, ay1, ax2, ay2 = bbox_a
        bx1, by1, bx2, by2 = bbox_b

        ix1 = max(
            ax1,
            bx1,
        )

        iy1 = max(
            ay1,
            by1,
        )

        ix2 = min(
            ax2,
            bx2,
        )

        iy2 = min(
            ay2,
            by2,
        )

        intersection_width = max(
            0.0,
            ix2 - ix1,
        )

        intersection_height = max(
            0.0,
            iy2 - iy1,
        )

        intersection = (
            intersection_width
            *
            intersection_height
        )

        area_a = max(
            0.0,
            ax2 - ax1,
        ) * max(
            0.0,
            ay2 - ay1,
        )

        area_b = max(
            0.0,
            bx2 - bx1,
        ) * max(
            0.0,
            by2 - by1,
        )

        union = (
            area_a
            +
            area_b
            -
            intersection
        )

        if union <= 0.0:
            return 0.0

        return (
            intersection
            /
            union
        )

    def _make_candidates(
        self,
        detections,
    ) -> list[
        DetectionCandidate
    ]:
        candidates = []

        for index, detection in enumerate(
            detections
        ):
            bbox = (
                self._bbox_from_detection(
                    detection
                )
            )

            ground_x, ground_y = (
                self._ground_point(
                    bbox
                )
            )

            candidates.append(
                DetectionCandidate(
                    index=index,
                    bbox=bbox,
                    ground_x=ground_x,
                    ground_y=ground_y,
                    class_name=(
                        detection.class_name
                    ),
                    confidence=float(
                        detection.confidence
                    ),
                    detection=detection,
                )
            )

        return candidates

    # =====================================================
    # Local association
    # =====================================================

    def _match_threshold(
        self,
        track: LocalTrack,
        candidate: DetectionCandidate,
        timestamp: float,
    ) -> float:
        track_diagonal = (
            track.diagonal
        )

        candidate_diagonal = (
            self._bbox_diagonal(
                candidate.bbox
            )
        )

        max_diagonal = max(
            track_diagonal,
            candidate_diagonal,
        )

        # 기존 설정에서 허용하는 최대 거리.
        configured_threshold = max(
            self.match_distance_px,
            (
                max_diagonal
                *
                self.match_distance_bbox_ratio
            ),
        )

        # 정상적인 30fps 연속 프레임에서는 차량 중심이
        # 한 프레임에 수십 px씩 순간 이동하지 않는다.
        #
        # YOLO 누락 때문에 몇 프레임 비었다면
        # gap에 비례해서 허용 거리를 늘린다.
        time_gap = max(
            0.0,
            timestamp - track.last_seen,
        )

        estimated_gap_frames = max(
            1.0,
            time_gap
            *
            self.nominal_fps,
        )

        # 너무 긴 gap에서 다른 차량과 연결되는 것을 막기 위해
        # 최대 8프레임 정도까지만 확장한다.
        estimated_gap_frames = min(
            8.0,
            estimated_gap_frames,
        )

        per_frame_distance = max(
            25.0,
            max_diagonal * 0.20,
        )

        temporal_threshold = (
            per_frame_distance
            *
            estimated_gap_frames
        )

        return min(
            configured_threshold,
            temporal_threshold,
        )

    def _build_matches(
        self,
        candidates: list[
            DetectionCandidate
        ],
        timestamp: float,
    ) -> list[
        tuple[
            int,
            int,
        ]
    ]:
        possible_matches = []

        for track_id, track in (
            self.tracks.items()
        ):
            for candidate in candidates:
                distance = math.hypot(
                    track.raw_ground_x
                    -
                    candidate.ground_x,
                    track.raw_ground_y
                    -
                    candidate.ground_y,
                )

                iou = self._iou(
                    track.bbox,
                    candidate.bbox,
                )

                threshold = (
                    self._match_threshold(
                        track,
                        candidate,
                        timestamp,
                    )
                )

                # IoU도 없고 중심도 멀다면 즉시 제외.
                if (
                    distance > threshold
                    and
                    iou
                    <
                    self.match_iou_threshold
                ):
                    continue

                track_diagonal = (
                    track.diagonal
                )

                candidate_diagonal = (
                    self._bbox_diagonal(
                        candidate.bbox
                    )
                )

                max_diagonal = max(
                    track_diagonal,
                    candidate_diagonal,
                )

                time_gap = max(
                    0.0,
                    timestamp - track.last_seen,
                )

                gap_frames = max(
                    1.0,
                    time_gap
                    *
                    self.nominal_fps,
                )

                gap_frames = min(
                    8.0,
                    gap_frames,
                )

                # IoU가 거의 없는 상태에서 갑자기 옆 차량으로
                # Local ID가 튀는 것을 방지하는 추가 guard.
                hard_jump_threshold = (
                    max(
                        30.0,
                        max_diagonal * 0.28,
                    )
                    *
                    gap_frames
                )

                if (
                    iou < 0.02
                    and
                    distance
                    >
                    hard_jump_threshold
                ):
                    continue

                normalized_distance = (
                    distance
                    /
                    max(
                        threshold,
                        1.0,
                    )
                )

                # IoU가 클수록 cost 감소.
                cost = (
                    normalized_distance
                    -
                    (
                        iou
                        *
                        0.65
                    )
                )

                possible_matches.append(
                    (
                        cost,
                        track_id,
                        candidate.index,
                    )
                )

        possible_matches.sort(
            key=lambda item: item[0]
        )

        matched_tracks = set()
        matched_detections = set()

        matches = []

        for (
            _,
            track_id,
            detection_index,
        ) in possible_matches:
            if track_id in matched_tracks:
                continue

            if (
                detection_index
                in
                matched_detections
            ):
                continue

            matched_tracks.add(
                track_id
            )

            matched_detections.add(
                detection_index
            )

            matches.append(
                (
                    track_id,
                    detection_index,
                )
            )

        return matches

    # =====================================================
    # State helpers
    # =====================================================

    def _change_state(
        self,
        track: LocalTrack,
        new_state: TrackState,
        timestamp: float,
    ) -> None:
        old_state = (
            track.state
        )

        if old_state == new_state:
            return

        track.state = new_state

        if self.print_transitions:
            print(
                f"[{track.label}] "
                f"{old_state.value} "
                f"-> "
                f"{new_state.value} "
                f"at {timestamp:.2f}s"
            )

    def _clear_stop_state(
        self,
        track: LocalTrack,
    ) -> None:
        track.stopped_since = None

        track.stationary_candidate_since = None

        track.stop_anchor_x = None
        track.stop_anchor_y = None

    def _set_stop_anchor(
        self,
        track: LocalTrack,
        timestamp: float,
    ) -> None:
        track.stop_anchor_x = (
            track.ground_x
        )

        track.stop_anchor_y = (
            track.ground_y
        )

        track.stopped_since = (
            timestamp
        )

    def _stop_anchor_threshold(
        self,
        track: LocalTrack,
    ) -> float:
        return max(
            self.stop_anchor_min_px,
            (
                track.diagonal
                *
                self.stop_anchor_bbox_ratio
            ),
        )

    def _parked_exit_threshold(
        self,
        track: LocalTrack,
    ) -> float:
        return max(
            self.parked_exit_min_px,
            (
                track.diagonal
                *
                self.parked_exit_bbox_ratio
            ),
        )

    def _distance_from_stop_anchor(
        self,
        track: LocalTrack,
    ) -> float:
        if (
            track.stop_anchor_x is None
            or
            track.stop_anchor_y is None
        ):
            return 0.0

        return math.hypot(
            track.ground_x
            -
            track.stop_anchor_x,
            track.ground_y
            -
            track.stop_anchor_y,
        )

    def _distance_from_parked_anchor(
        self,
        track: LocalTrack,
    ) -> float:
        if (
            track.parked_anchor_x is None
            or
            track.parked_anchor_y is None
        ):
            return 0.0

        return math.hypot(
            track.ground_x
            -
            track.parked_anchor_x,
            track.ground_y
            -
            track.parked_anchor_y,
        )

    # =====================================================
    # Position smoothing
    # =====================================================

    def _append_position(
        self,
        track: LocalTrack,
        timestamp: float,
        x: float,
        y: float,
    ) -> None:
        track.raw_history.append(
            PositionSample(
                timestamp=timestamp,
                x=x,
                y=y,
            )
        )

        while (
            len(
                track.raw_history
            )
            >
            self.smoothing_window
        ):
            track.raw_history.popleft()

        xs = np.array(
            [
                sample.x
                for sample
                in track.raw_history
            ],
            dtype=np.float64,
        )

        ys = np.array(
            [
                sample.y
                for sample
                in track.raw_history
            ],
            dtype=np.float64,
        )

        smoothed_x = float(
            np.median(
                xs
            )
        )

        smoothed_y = float(
            np.median(
                ys
            )
        )

        track.smoothed_history.append(
            PositionSample(
                timestamp=timestamp,
                x=smoothed_x,
                y=smoothed_y,
            )
        )

        keep_after = (
            timestamp
            -
            max(
                self.motion_window_sec
                *
                3.0,
                3.0,
            )
        )

        while (
            len(
                track.smoothed_history
            )
            >
            2
            and
            track.smoothed_history[0].timestamp
            <
            keep_after
        ):
            track.smoothed_history.popleft()

    # =====================================================
    # Motion
    # =====================================================

    def _motion_distance(
        self,
        track: LocalTrack,
        timestamp: float,
    ) -> float:
        if (
            len(
                track.smoothed_history
            )
            <
            2
        ):
            return 0.0

        target_time = (
            timestamp
            -
            self.motion_window_sec
        )

        reference = (
            track.smoothed_history[0]
        )

        for sample in (
            track.smoothed_history
        ):
            if (
                sample.timestamp
                >=
                target_time
            ):
                reference = sample
                break

        current = (
            track.smoothed_history[-1]
        )

        return math.hypot(
            current.x
            -
            reference.x,
            current.y
            -
            reference.y,
        )

    def _base_motion_threshold(
        self,
        track: LocalTrack,
    ) -> float:
        bbox_threshold = (
            track.diagonal
            *
            self.motion_bbox_ratio
        )

        return max(
            self.min_motion_px,
            bbox_threshold,
        )

    def _state_motion_threshold(
        self,
        track: LocalTrack,
    ) -> float:
        threshold = (
            self._base_motion_threshold(
                track
            )
        )

        if (
            track.state
            ==
            TrackState.STOPPED
        ):
            threshold *= (
                self.stopped_motion_multiplier
            )

        elif (
            track.state
            ==
            TrackState.PARKED
        ):
            threshold *= (
                self.parked_motion_multiplier
            )

        return threshold

    def _history_ready(
        self,
        track: LocalTrack,
    ) -> bool:
        if (
            len(
                track.smoothed_history
            )
            <
            2
        ):
            return False

        history_duration = (
            track.smoothed_history[-1].timestamp
            -
            track.smoothed_history[0].timestamp
        )

        return (
            history_duration
            >=
            self.motion_window_sec
            *
            0.70
        )

    # =====================================================
    # State machine
    # =====================================================

    def _update_unknown_state(
        self,
        track: LocalTrack,
        timestamp: float,
        moving: bool,
    ) -> None:
        if not moving:
            track.moving_candidate_since = None
            return

        if (
            track.moving_candidate_since
            is None
        ):
            track.moving_candidate_since = (
                timestamp
            )
            return

        duration = (
            timestamp
            -
            track.moving_candidate_since
        )

        if (
            duration
            <
            self.unknown_to_active_sec
        ):
            return

        track.has_moved = True

        track.last_moving_at = (
            timestamp
        )

        track.moving_candidate_since = None

        self._clear_stop_state(
            track
        )

        track.parked_anchor_x = None
        track.parked_anchor_y = None

        self._change_state(
            track,
            TrackState.ACTIVE,
            timestamp,
        )

    def _update_active_state(
        self,
        track: LocalTrack,
        timestamp: float,
        moving: bool,
    ) -> None:
        if moving:
            track.last_moving_at = (
                timestamp
            )

            track.stationary_candidate_since = None
            track.stopped_since = None

            return

        # 첫 정지 후보.
        if (
            track.stationary_candidate_since
            is None
        ):
            track.stationary_candidate_since = (
                timestamp
            )

            return

        stationary_duration = (
            timestamp
            -
            track.stationary_candidate_since
        )

        if (
            stationary_duration
            <
            self.active_to_stopped_sec
        ):
            return

        # STOPPED로 확정.
        track.stopped_since = (
            track.stationary_candidate_since
        )

        track.stop_anchor_x = (
            track.ground_x
        )

        track.stop_anchor_y = (
            track.ground_y
        )

        track.moving_candidate_since = None

        self._change_state(
            track,
            TrackState.STOPPED,
            timestamp,
        )

    def _update_stopped_state(
        self,
        track: LocalTrack,
        timestamp: float,
        moving: bool,
    ) -> None:
        if moving:
            # 매우 중요:
            # ACTIVE 복귀가 아직 확정되지 않았더라도
            # 움직임 증거가 나온 순간 PARKED 누적 시간은 폐기.
            track.stopped_since = None

            track.stop_anchor_x = None
            track.stop_anchor_y = None

            track.stationary_candidate_since = None

            if (
                track.moving_candidate_since
                is None
            ):
                track.moving_candidate_since = (
                    timestamp
                )

                return

            moving_duration = (
                timestamp
                -
                track.moving_candidate_since
            )

            if (
                moving_duration
                <
                self.stopped_to_active_sec
            ):
                return

            track.has_moved = True

            track.last_moving_at = (
                timestamp
            )

            track.moving_candidate_since = None

            self._clear_stop_state(
                track
            )

            track.parked_anchor_x = None
            track.parked_anchor_y = None

            self._change_state(
                track,
                TrackState.ACTIVE,
                timestamp,
            )

            return

        # 움직임 후보가 끊기면 다시 처음부터.
        track.moving_candidate_since = None

        # STOPPED 상태인데 직전에 움직임 후보가 있었을 경우
        # stopped_since가 None으로 초기화되어 있다.
        if (
            track.stopped_since
            is None
            or
            track.stop_anchor_x is None
            or
            track.stop_anchor_y is None
        ):
            self._set_stop_anchor(
                track,
                timestamp,
            )

            return

        anchor_distance = (
            self._distance_from_stop_anchor(
                track
            )
        )

        anchor_threshold = (
            self._stop_anchor_threshold(
                track
            )
        )

        # 순간 motion threshold에는 못 미쳤더라도
        # 차량이 천천히 계속 이동해서 정지 기준 위치에서
        # 벗어난 경우 주차 타이머를 다시 시작한다.
        if (
            anchor_distance
            >
            anchor_threshold
        ):
            self._set_stop_anchor(
                track,
                timestamp,
            )

            return

        stopped_duration = (
            track.stopped_duration(
                timestamp
            )
        )

        if (
            stopped_duration
            <
            self.parked_after_sec
        ):
            return

        # 충분히 오랫동안 같은 위치에 머문 경우에만 PARKED.
        track.parked_anchor_x = (
            track.ground_x
        )

        track.parked_anchor_y = (
            track.ground_y
        )

        track.moving_candidate_since = None
        track.stationary_candidate_since = None

        self._change_state(
            track,
            TrackState.PARKED,
            timestamp,
        )

    def _update_parked_state(
        self,
        track: LocalTrack,
        timestamp: float,
        moving: bool,
    ) -> None:
        # PARKED가 되었을 때 anchor가 없는 예외 상황 방어.
        if (
            track.parked_anchor_x
            is None
            or
            track.parked_anchor_y
            is None
        ):
            track.parked_anchor_x = (
                track.ground_x
            )

            track.parked_anchor_y = (
                track.ground_y
            )

        exit_distance = (
            self._distance_from_parked_anchor(
                track
            )
        )

        exit_threshold = (
            self._parked_exit_threshold(
                track
            )
        )

        # PARKED에서는 단순 motion뿐 아니라
        # 실제 주차 위치에서 벗어났는지를 함께 확인.
        leaving_parked_position = (
            exit_distance
            >
            exit_threshold
        )

        movement_evidence = (
            moving
            or
            leaving_parked_position
        )

        if not movement_evidence:
            track.moving_candidate_since = None
            return

        if (
            track.moving_candidate_since
            is None
        ):
            track.moving_candidate_since = (
                timestamp
            )

            return

        moving_duration = (
            timestamp
            -
            track.moving_candidate_since
        )

        if (
            moving_duration
            <
            self.parked_to_active_sec
        ):
            return

        track.has_moved = True

        track.last_moving_at = (
            timestamp
        )

        track.moving_candidate_since = None

        self._clear_stop_state(
            track
        )

        track.parked_anchor_x = None
        track.parked_anchor_y = None

        self._change_state(
            track,
            TrackState.ACTIVE,
            timestamp,
        )

    def _update_motion_state(
        self,
        track: LocalTrack,
        timestamp: float,
    ) -> None:
        if not self._history_ready(
            track
        ):
            return

        motion_distance = (
            self._motion_distance(
                track,
                timestamp,
            )
        )

        threshold = (
            self._state_motion_threshold(
                track
            )
        )

        moving = (
            motion_distance
            >=
            threshold
        )

        if (
            track.state
            ==
            TrackState.UNKNOWN
        ):
            self._update_unknown_state(
                track,
                timestamp,
                moving,
            )

            return

        if (
            track.state
            ==
            TrackState.ACTIVE
        ):
            self._update_active_state(
                track,
                timestamp,
                moving,
            )

            return

        if (
            track.state
            ==
            TrackState.STOPPED
        ):
            self._update_stopped_state(
                track,
                timestamp,
                moving,
            )

            return

        if (
            track.state
            ==
            TrackState.PARKED
        ):
            self._update_parked_state(
                track,
                timestamp,
                moving,
            )

    # =====================================================
    # Track update
    # =====================================================

    def _update_track(
        self,
        track: LocalTrack,
        candidate: DetectionCandidate,
        timestamp: float,
    ) -> None:
        track.bbox = (
            candidate.bbox
        )

        track.class_name = (
            candidate.class_name
        )

        track.confidence = (
            candidate.confidence
        )

        track.last_seen = (
            timestamp
        )

        self._append_position(
            track,
            timestamp,
            candidate.ground_x,
            candidate.ground_y,
        )

        self._update_motion_state(
            track,
            timestamp,
        )

    def _create_track(
        self,
        candidate: DetectionCandidate,
        timestamp: float,
    ) -> LocalTrack:
        local_id = (
            self.next_local_id
        )

        self.next_local_id += 1

        track = LocalTrack(
            local_id=local_id,
            camera_id=(
                self.camera_id
            ),
            bbox=(
                candidate.bbox
            ),
            class_name=(
                candidate.class_name
            ),
            confidence=(
                candidate.confidence
            ),
            first_seen=(
                timestamp
            ),
            last_seen=(
                timestamp
            ),
        )

        self._append_position(
            track,
            timestamp,
            candidate.ground_x,
            candidate.ground_y,
        )

        self.tracks[
            local_id
        ] = track

        return track

    def _remove_stale_tracks(
        self,
        timestamp: float,
    ) -> None:
        stale_ids = []

        for track_id, track in (
            self.tracks.items()
        ):
            missing_duration = (
                timestamp
                -
                track.last_seen
            )

            if (
                missing_duration
                >
                self.max_missing_sec
            ):
                stale_ids.append(
                    track_id
                )

        for track_id in stale_ids:
            del self.tracks[
                track_id
            ]

    # =====================================================
    # Public API
    # =====================================================

    def update(
        self,
        detections,
        timestamp: float,
    ) -> list[
        TrackedDetection
    ]:
        timestamp = float(
            timestamp
        )

        candidates = (
            self._make_candidates(
                detections
            )
        )

        matches = (
            self._build_matches(
                candidates,
                timestamp,
            )
        )

        matched_detection_indices = set()

        result_by_detection: dict[
            int,
            LocalTrack,
        ] = {}

        for (
            track_id,
            detection_index,
        ) in matches:
            track = (
                self.tracks[
                    track_id
                ]
            )

            candidate = (
                candidates[
                    detection_index
                ]
            )

            self._update_track(
                track,
                candidate,
                timestamp,
            )

            matched_detection_indices.add(
                detection_index
            )

            result_by_detection[
                detection_index
            ] = track

        for candidate in candidates:
            if (
                candidate.index
                in
                matched_detection_indices
            ):
                continue

            track = (
                self._create_track(
                    candidate,
                    timestamp,
                )
            )

            result_by_detection[
                candidate.index
            ] = track

        self._remove_stale_tracks(
            timestamp
        )

        tracked_detections = []

        for candidate in candidates:
            track = (
                result_by_detection.get(
                    candidate.index
                )
            )

            if track is None:
                continue

            tracked_detections.append(
                TrackedDetection(
                    detection=(
                        candidate.detection
                    ),
                    track=track,
                )
            )

        return tracked_detections

    def active_track_count(
        self,
    ) -> int:
        return sum(
            1
            for track
            in self.tracks.values()
            if track.has_moved
        )

    def state_counts(
        self,
    ) -> dict[
        TrackState,
        int,
    ]:
        counts = {
            TrackState.UNKNOWN: 0,
            TrackState.ACTIVE: 0,
            TrackState.STOPPED: 0,
            TrackState.PARKED: 0,
        }

        for track in (
            self.tracks.values()
        ):
            counts[
                track.state
            ] += 1

        return counts