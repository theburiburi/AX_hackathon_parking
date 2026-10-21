from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

# 움직이던 차량이 가려진 정지 차량 뒤로 사라지면, 남은 검출은
# 정지 차량이 다시 보이는 것이다. 움직이던 track이 그 정지 차량의
# 보관 박스(IoU 이 값 이상, 크기 거의 같음) 위에 이 시간 이상 멈춰 있으면
# 검출을 정지 차량에게 돌려준다. 앞을 지나가는 차량은 겹친 채 머물지 않는다.
OCCLUDED_REAPPEAR_IOU = 0.8
OCCLUDED_REAPPEAR_SEC = 0.5

# 정차·주차한 차량에 박스가 하나 더 잡혀 새 track이 생기면, 둘이 검출을
# 번갈아 가져가다 원래 track이 사라지며 Local ID·상태(GID)를 잃는다.
# 원래 track과 같은 프레임에 IoU 이 값 이상 겹쳐 생긴 새 track이 아직
# 움직인 적 없고 이 시간 이내면, 검출을 원래 track에 돌려주고 새 track은 지운다.
# (다른 곳에서 와서 앞을 지나가는 차량은 겹쳐서 생기지 않으므로 해당하지 않는다)
DUPLICATE_TRACK_IOU = 0.5
DUPLICATE_TRACK_MAX_AGE_SEC = 5.0


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
    moving_evidence_sec: float = 0.0
    last_motion_evidence_at: float | None = None
    last_detection_gap_sec: float = 0.0

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
    occluded: bool = False

    # 움직이던 track이 가려진 정지 차량의 보관 박스 위에 머물기 시작한 시각과
    # 그 정지 차량의 Local ID.
    covered_dwell_since: float | None = None
    covered_dwell_track_id: int | None = None

    # 정차·주차 차량에 겹쳐 같은 프레임에 생긴 중복 track이면 그 원래 Local ID.
    duplicate_of: int | None = None

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
        unknown_motion_gap_sec: float = 0.25,
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
        self.unknown_motion_gap_sec = max(0.0, float(unknown_motion_gap_sec))

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

        candidate_diagonals = {
            candidate.index: self._bbox_diagonal(candidate.bbox)
            for candidate in candidates
        }

        for track_id, track in (
            self.tracks.items()
        ):
            predicted_x, predicted_y = track.raw_ground_x, track.raw_ground_y
            if (track.state == TrackState.ACTIVE or track.moving_candidate_since is not None):
                history = track.raw_history
                if len(history) >= 2:
                    first, last = history[0], history[-1]
                    elapsed = last.timestamp - first.timestamp
                    if elapsed > 0:
                        horizon = min(0.2, max(0.0, timestamp - last.timestamp))
                        predicted_x = last.x + (last.x - first.x) / elapsed * horizon
                        predicted_y = last.y + (last.y - first.y) / elapsed * horizon
            track_diagonal = track.diagonal
            tx1, ty1, tx2, ty2 = track.bbox
            for candidate in candidates:
                distance = math.hypot(
                    predicted_x
                    -
                    candidate.ground_x,
                    predicted_y
                    -
                    candidate.ground_y,
                )

                # 빠른 제외: 박스가 겹치지 않고(IoU 0) 중심 거리가
                # 매칭 허용 거리의 상한보다 멀면 아래 검사도 반드시 제외한다.
                cx1, cy1, cx2, cy2 = candidate.bbox
                if (
                    (cx1 >= tx2 or cx2 <= tx1 or cy1 >= ty2 or cy2 <= ty1)
                    and distance > max(
                        self.match_distance_px,
                        max(track_diagonal, candidate_diagonals[candidate.index])
                        * self.match_distance_bbox_ratio,
                    )
                ):
                    continue

                iou = self._iou(
                    track.bbox,
                    candidate.bbox,
                )

                # An abrupt camera reframing can put a parked vehicle's
                # old box over a different, much larger nearby vehicle.
                # Do not carry its Local (and therefore Global) ID across
                # that change in apparent object size.
                old_area = track.width * track.height
                new_area = max(1.0, candidate.bbox[2] - candidate.bbox[0]) * max(
                    1.0, candidate.bbox[3] - candidate.bbox[1]
                )
                if (
                    track.state in (TrackState.STOPPED, TrackState.PARKED)
                    and (new_area > old_area * 2.25 or old_area > new_area * 2.25)
                ):
                    continue

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

                # A covered stationary box can coincide with the moving car.
                # Let the moving track claim its own detection first.
                if track.occluded and track.state != TrackState.ACTIVE:
                    cost += 0.8

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

        # A camera-wide reframing can move a stationary car beyond its
        # ordinary one-frame distance limit. Use the displacement of other
        # stationary cars that were matched confidently in this frame to
        # recover its corresponding detection. A single moving neighbor is
        # not enough evidence to move a parked identity.
        reference_moves = []
        for track_id, track in self.tracks.items():
            stationary = track.state in (TrackState.STOPPED, TrackState.PARKED)
            stable_unknown = (
                track.state == TrackState.UNKNOWN
                and timestamp - track.first_seen >= 1.0
                and track.moving_candidate_since is None
            )
            if not (stationary or stable_unknown):
                continue
            if timestamp - track.last_seen > 0.15:
                continue
            for candidate in candidates:
                width = max(1.0, candidate.bbox[2] - candidate.bbox[0])
                height = max(1.0, candidate.bbox[3] - candidate.bbox[1])
                dx = candidate.ground_x - track.raw_ground_x
                dy = candidate.ground_y - track.raw_ground_y
                if (0.7 <= width / track.width <= 1.4
                        and 0.7 <= height / track.height <= 1.4
                        and 30.0 <= math.hypot(dx, dy) <= 150.0
                        and abs(dy) <= 40.0):
                    reference_moves.append((
                        track_id, candidate.index, track.raw_ground_x,
                        track.raw_ground_y, dx, dy,
                        (track_id, candidate.index) in matches,
                    ))

        recovery_options = []
        for track_id, track in self.tracks.items():
            if track_id in matched_tracks or track.state not in (TrackState.STOPPED, TrackState.PARKED):
                continue
            if timestamp - track.last_seen > 0.15:
                continue
            for candidate in candidates:
                if candidate.index in matched_detections:
                    continue
                old_width, old_height = track.width, track.height
                new_width = max(1.0, candidate.bbox[2] - candidate.bbox[0])
                new_height = max(1.0, candidate.bbox[3] - candidate.bbox[1])
                if not (0.65 <= new_width / old_width <= 1.5
                        and 0.65 <= new_height / old_height <= 1.5):
                    continue
                dx = candidate.ground_x - track.raw_ground_x
                dy = candidate.ground_y - track.raw_ground_y
                if math.hypot(dx, dy) < self._match_threshold(track, candidate, timestamp):
                    continue
                supporters = sorted((
                    (math.hypot(dx - other_dx, dy - other_dy), other_track,
                     other_candidate, confirmed)
                    for other_track, other_candidate, x, y, other_dx, other_dy, confirmed
                    in reference_moves
                    if other_track != track_id and other_candidate != candidate.index
                    and math.hypot(x - track.raw_ground_x, y - track.raw_ground_y) <= 350.0
                    and math.hypot(dx - other_dx, dy - other_dy) <= 40.0
                ))
                supported_costs = [
                    first[0] + second[0]
                    for index, first in enumerate(supporters)
                    for second in supporters[index + 1:]
                    if first[1] != second[1] and first[2] != second[2]
                    and (first[3] or second[3])
                ]
                if supported_costs:
                    recovery_options.append((min(supported_costs), track_id, candidate.index))

        for _, track_id, detection_index in sorted(recovery_options):
            if track_id not in matched_tracks and detection_index not in matched_detections:
                matches.append((track_id, detection_index))
                matched_tracks.add(track_id)
                matched_detections.add(detection_index)

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
            # A missing detection can leave one resumed frame without enough
            # motion history. Ordinary non-moving detections still reset the
            # timer so camera scaling cannot accumulate false evidence.
            resumed_after_gap = (
                track.last_motion_evidence_at is not None
                and track.last_detection_gap_sec > 1.5 / self.nominal_fps
                and timestamp - track.last_motion_evidence_at <= self.unknown_motion_gap_sec
            )
            if resumed_after_gap:
                return
            track.moving_candidate_since = None
            track.last_motion_evidence_at = None
            track.moving_evidence_sec = 0.0
            return

        previous_motion_at = track.last_motion_evidence_at
        if (previous_motion_at is None
                or timestamp - previous_motion_at > self.unknown_motion_gap_sec):
            track.moving_candidate_since = timestamp
            track.last_motion_evidence_at = timestamp
            track.moving_evidence_sec = 0.0
            return

        elapsed = max(0.0, timestamp - previous_motion_at)
        track.moving_evidence_sec += min(elapsed, 2.0 / self.nominal_fps)
        track.last_motion_evidence_at = timestamp

        if (
            track.moving_evidence_sec
            <
            self.unknown_to_active_sec
        ):
            return

        track.has_moved = True

        track.last_moving_at = (
            timestamp
        )

        track.moving_candidate_since = None
        track.last_motion_evidence_at = None
        track.moving_evidence_sec = 0.0

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
        track.occluded = False
        track.last_detection_gap_sec = max(0.0, timestamp - track.last_seen)
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

    def _return_covered_detections(
        self,
        matches: list[tuple[int, int]],
        candidates: list[DetectionCandidate],
        timestamp: float,
    ) -> list[tuple[int, int]]:
        # A moving car that disappears behind a parked car leaves only the
        # parked car's detection. The moving track wins that detection while
        # the parked track is occluded, then sits still on the parked car's
        # box. Once that lasts, hand the detection back and drop the moving
        # track: its car is out of sight, and its Global ID must stay free
        # for the camera where the car shows up next.
        matched_track_ids = {track_id for track_id, _ in matches}
        lost_track_ids = []
        result = []
        for track_id, detection_index in matches:
            track = self.tracks[track_id]
            owner_id = None
            if track.state == TrackState.ACTIVE:
                bbox = candidates[detection_index].bbox
                width = max(1.0, bbox[2] - bbox[0])
                height = max(1.0, bbox[3] - bbox[1])
                for other_id, other in self.tracks.items():
                    if (other_id in matched_track_ids or not other.occluded
                            or other.state == TrackState.ACTIVE):
                        continue
                    if (self._iou(bbox, other.bbox) >= OCCLUDED_REAPPEAR_IOU
                            and 0.85 <= width / other.width <= 1.18
                            and 0.85 <= height / other.height <= 1.18):
                        owner_id = other_id
                        break
            if owner_id is None:
                track.covered_dwell_since = None
                track.covered_dwell_track_id = None
            elif track.covered_dwell_track_id != owner_id:
                track.covered_dwell_since = timestamp
                track.covered_dwell_track_id = owner_id
            if (owner_id is not None
                    and timestamp - track.covered_dwell_since >= OCCLUDED_REAPPEAR_SEC):
                result.append((owner_id, detection_index))
                matched_track_ids.add(owner_id)
                lost_track_ids.append(track_id)
            else:
                result.append((track_id, detection_index))
        for track_id in lost_track_ids:
            del self.tracks[track_id]
        return result

    def _absorb_duplicate_tracks(
        self,
        matches: list[tuple[int, int]],
        candidates: list[DetectionCandidate],
        timestamp: float,
    ) -> list[tuple[int, int]]:
        matched_track_ids = {track_id for track_id, _ in matches}
        result = []
        for track_id, detection_index in matches:
            track = self.tracks[track_id]
            bbox = candidates[detection_index].bbox
            if (track.state == TrackState.UNKNOWN and not track.has_moved
                    and timestamp - track.first_seen <= DUPLICATE_TRACK_MAX_AGE_SEC):
                owner = self.tracks.get(track.duplicate_of)
                if (owner is not None
                        and track.duplicate_of not in matched_track_ids
                        and owner.state in (TrackState.STOPPED, TrackState.PARKED)
                        and timestamp - owner.last_seen <= self.max_missing_sec
                        and self._iou(owner.bbox, bbox) >= DUPLICATE_TRACK_IOU):
                    matched_track_ids.discard(track_id)
                    matched_track_ids.add(track.duplicate_of)
                    del self.tracks[track_id]
                    result.append((track.duplicate_of, detection_index))
                    continue
            result.append((track_id, detection_index))
        return result

    @staticmethod
    def _covered_fraction(rear_bbox, front_bbox) -> float:
        x1 = max(rear_bbox[0], front_bbox[0])
        y1 = max(rear_bbox[1], front_bbox[1])
        x2 = min(rear_bbox[2], front_bbox[2])
        y2 = min(rear_bbox[3], front_bbox[3])
        overlap = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        rear_area = max(1.0, rear_bbox[2] - rear_bbox[0]) * max(1.0, rear_bbox[3] - rear_bbox[1])
        return overlap / rear_area

    @staticmethod
    def _mark_occluded(track: LocalTrack) -> None:
        # A partly hidden bbox is not evidence that the parked car moved.
        track.occluded = True
        track.moving_candidate_since = None
        track.last_motion_evidence_at = None
        track.moving_evidence_sec = 0.0
        track.raw_history.clear()
        track.smoothed_history.clear()

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

        matches = self._return_covered_detections(
            matches, candidates, timestamp)
        matches = self._absorb_duplicate_tracks(
            matches, candidates, timestamp)

        matched_detection_indices = set()

        result_by_detection: dict[
            int,
            LocalTrack,
        ] = {}

        foreground_boxes = [
            (track_id, candidates[detection_index].bbox)
            for track_id, detection_index in matches
            if (self.tracks[track_id].state == TrackState.ACTIVE
                or self.tracks[track_id].moving_candidate_since is not None)
        ]
        matched_track_ids = {track_id for track_id, _ in matches}
        foreground_boxes.extend(
            (track_id, track.bbox)
            for track_id, track in self.tracks.items()
            if track_id not in matched_track_ids
            and track.state == TrackState.ACTIVE
            and timestamp - track.last_seen <= 0.2
        )

        def covered_by_moving_car(track_id: int, track: LocalTrack) -> bool:
            return (track.state != TrackState.ACTIVE and any(
                other_id != track_id
                and self._covered_fraction(track.bbox, box) >= 0.25
                for other_id, box in foreground_boxes
            ))

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

            if covered_by_moving_car(track_id, track):
                self._mark_occluded(track)
                track.last_seen = timestamp
            else:
                self._update_track(track, candidate, timestamp)

            matched_detection_indices.add(
                detection_index
            )

            result_by_detection[
                detection_index
            ] = track

        for track_id, track in self.tracks.items():
            if track_id not in matched_track_ids and covered_by_moving_car(track_id, track):
                self._mark_occluded(track)

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
            owners = [
                other_id for other_id in matched_track_ids
                if other_id in self.tracks
                and self.tracks[other_id].has_moved
                and self.tracks[other_id].state in (TrackState.STOPPED, TrackState.PARKED)
                and self._iou(self.tracks[other_id].bbox, candidate.bbox)
                >= DUPLICATE_TRACK_IOU
            ]
            if len(owners) == 1:
                track.duplicate_of = owners[0]

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
