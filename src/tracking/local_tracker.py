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

    has_moved: bool = False

    last_moving_at: float | None = None
    stopped_since: float | None = None

    moving_candidate_since: float | None = None

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
            return self.smoothed_history[-1].x

        return self.raw_ground_x

    @property
    def ground_y(
        self,
    ) -> float:

        if self.smoothed_history:
            return self.smoothed_history[-1].y

        return self.raw_ground_y

    def stopped_duration(
        self,
        timestamp: float,
    ) -> float:

        if self.stopped_since is None:
            return 0.0

        return max(
            0.0,
            timestamp
            -
            self.stopped_since,
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

        self.tracks: dict[
            int,
            LocalTrack,
        ] = {}

        self.next_local_id = 1

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
            float(detection.x1),
            float(detection.y1),
            float(detection.x2),
            float(detection.y2),
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

    def _match_threshold(
        self,
        track: LocalTrack,
        candidate: DetectionCandidate,
    ) -> float:

        track_diagonal = (
            track.diagonal
        )

        candidate_diagonal = (
            self._bbox_diagonal(
                candidate.bbox
            )
        )

        bbox_based_threshold = (
            max(
                track_diagonal,
                candidate_diagonal,
            )
            *
            self.match_distance_bbox_ratio
        )

        return max(
            self.match_distance_px,
            bbox_based_threshold,
        )

    def _build_matches(
        self,
        candidates: list[
            DetectionCandidate
        ],
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
                    )
                )

                if (
                    distance > threshold
                    and
                    iou
                    <
                    self.match_iou_threshold
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

                cost = (
                    normalized_distance
                    -
                    (
                        iou
                        *
                        0.50
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

    def _motion_distance(
        self,
        track: LocalTrack,
        timestamp: float,
    ) -> float:

        if len(
            track.smoothed_history
        ) < 2:

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

    def _required_motion_time(
        self,
        track: LocalTrack,
    ) -> float:

        if (
            track.state
            ==
            TrackState.PARKED
        ):

            return (
                self.parked_to_active_sec
            )

        if (
            track.state
            ==
            TrackState.STOPPED
        ):

            return (
                self.stopped_to_active_sec
            )

        return (
            self.unknown_to_active_sec
        )

    def _confirm_moving(
        self,
        track: LocalTrack,
        timestamp: float,
        moving: bool,
    ) -> bool:

        if not moving:

            track.moving_candidate_since = None

            return False

        if (
            track.moving_candidate_since
            is None
        ):

            track.moving_candidate_since = (
                timestamp
            )

            return False

        required_time = (
            self._required_motion_time(
                track
            )
        )

        duration = (
            timestamp
            -
            track.moving_candidate_since
        )

        return (
            duration
            >=
            required_time
        )

    def _update_motion_state(
        self,
        track: LocalTrack,
        timestamp: float,
    ) -> None:

        if len(
            track.smoothed_history
        ) < 2:

            return

        history_duration = (
            track.smoothed_history[-1].timestamp
            -
            track.smoothed_history[0].timestamp
        )

        if (
            history_duration
            <
            self.motion_window_sec
            *
            0.70
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

        confirmed_moving = (
            self._confirm_moving(
                track,
                timestamp,
                moving,
            )
        )

        if confirmed_moving:

            track.has_moved = True

            track.last_moving_at = (
                timestamp
            )

            track.stopped_since = None

            track.moving_candidate_since = None

            self._change_state(
                track,
                TrackState.ACTIVE,
                timestamp,
            )

            return

        if moving:

            # 움직임 후보는 맞지만 아직
            # 연속시간 조건을 만족하지 못함.
            return

        if not track.has_moved:

            self._change_state(
                track,
                TrackState.UNKNOWN,
                timestamp,
            )

            return

        if (
            track.state
            ==
            TrackState.ACTIVE
        ):

            if (
                track.stopped_since
                is None
            ):

                track.stopped_since = (
                    timestamp
                )

            self._change_state(
                track,
                TrackState.STOPPED,
                timestamp,
            )

            return

        if (
            track.state
            ==
            TrackState.STOPPED
        ):

            if (
                track.stopped_since
                is None
            ):

                track.stopped_since = (
                    timestamp
                )

            stopped_duration = (
                track.stopped_duration(
                    timestamp
                )
            )

            if (
                stopped_duration
                >=
                self.parked_after_sec
            ):

                self._change_state(
                    track,
                    TrackState.PARKED,
                    timestamp,
                )

            return

        if (
            track.state
            ==
            TrackState.PARKED
        ):

            # PARKED는 작은 흔들림이나
            # 순간적인 bbox 변동으로는
            # 상태가 바뀌지 않는다.
            return

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
                candidates
            )
        )

        matched_detection_indices = (
            set()
        )

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