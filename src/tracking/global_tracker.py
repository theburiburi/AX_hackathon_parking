from __future__ import annotations

import math
from dataclasses import dataclass, field

from .local_tracker import TrackState


LocalTrackKey = tuple[str, int]


@dataclass
class GlobalObservation:
    camera_id: str
    local_id: int

    state: TrackState

    class_name: str
    confidence: float

    bev_x: float
    bev_y: float

    timestamp: float

    @property
    def local_key(self) -> LocalTrackKey:
        return (
            self.camera_id,
            self.local_id,
        )


@dataclass
class GlobalTrack:
    global_id: int

    first_seen: float
    last_seen: float

    last_bev_x: float
    last_bev_y: float

    current_camera_id: str
    current_local_id: int

    state: TrackState

    class_name: str
    confidence: float

    observation_count: int = 1

    local_keys: set[LocalTrackKey] = field(
        default_factory=set
    )

    @property
    def label(self) -> str:
        return f"G{self.global_id:03d}"

    @property
    def current_local_key(self) -> LocalTrackKey:
        return (
            self.current_camera_id,
            self.current_local_id,
        )

    def distance_to(
        self,
        bev_x: float,
        bev_y: float,
    ) -> float:
        return math.hypot(
            bev_x - self.last_bev_x,
            bev_y - self.last_bev_y,
        )


class GlobalTracker:
    def __init__(
        self,
        max_reid_gap_sec: float = 3.0,
        base_match_distance_px: float = 80.0,
        max_match_distance_px: float = 300.0,
        max_speed_px_per_sec: float = 180.0,
        time_weight: float = 0.25,
        class_mismatch_penalty: float = 0.20,
        max_match_score: float = 1.25,
        retention_sec: float = 120.0,
        print_events: bool = True,
    ):
        self.max_reid_gap_sec = float(
            max_reid_gap_sec
        )

        self.base_match_distance_px = float(
            base_match_distance_px
        )

        self.max_match_distance_px = float(
            max_match_distance_px
        )

        self.max_speed_px_per_sec = float(
            max_speed_px_per_sec
        )

        self.time_weight = float(
            time_weight
        )

        self.class_mismatch_penalty = float(
            class_mismatch_penalty
        )

        self.max_match_score = float(
            max_match_score
        )

        self.retention_sec = float(
            retention_sec
        )

        self.print_events = bool(
            print_events
        )

        self.next_global_id = 1

        self.global_tracks: dict[
            int,
            GlobalTrack,
        ] = {}

        self.local_to_global: dict[
            LocalTrackKey,
            int,
        ] = {}

    def _create_global_track(
        self,
        observation: GlobalObservation,
    ) -> GlobalTrack:
        global_id = self.next_global_id
        self.next_global_id += 1

        global_track = GlobalTrack(
            global_id=global_id,
            first_seen=observation.timestamp,
            last_seen=observation.timestamp,
            last_bev_x=observation.bev_x,
            last_bev_y=observation.bev_y,
            current_camera_id=observation.camera_id,
            current_local_id=observation.local_id,
            state=observation.state,
            class_name=observation.class_name,
            confidence=observation.confidence,
        )

        global_track.local_keys.add(
            observation.local_key
        )

        self.global_tracks[
            global_id
        ] = global_track

        self.local_to_global[
            observation.local_key
        ] = global_id

        if self.print_events:
            print(
                f"[GLOBAL] "
                f"{global_track.label} created <- "
                f"{observation.camera_id.upper()}"
                f"-L{observation.local_id:03d} "
                f"at "
                f"({observation.bev_x:.1f}, "
                f"{observation.bev_y:.1f})"
            )

        return global_track

    def _update_global_track(
        self,
        global_track: GlobalTrack,
        observation: GlobalObservation,
    ) -> None:
        global_track.last_seen = (
            observation.timestamp
        )

        global_track.last_bev_x = (
            observation.bev_x
        )

        global_track.last_bev_y = (
            observation.bev_y
        )

        global_track.current_camera_id = (
            observation.camera_id
        )

        global_track.current_local_id = (
            observation.local_id
        )

        global_track.state = (
            observation.state
        )

        global_track.class_name = (
            observation.class_name
        )

        global_track.confidence = (
            observation.confidence
        )

        global_track.observation_count += 1

        global_track.local_keys.add(
            observation.local_key
        )

    def _allowed_distance(
        self,
        time_gap: float,
    ) -> float:
        dynamic_distance = (
            self.base_match_distance_px
            +
            self.max_speed_px_per_sec
            *
            max(
                0.0,
                time_gap,
            )
        )

        return min(
            self.max_match_distance_px,
            dynamic_distance,
        )

    def _candidate_score(
        self,
        global_track: GlobalTrack,
        observation: GlobalObservation,
    ) -> tuple[float, float, float] | None:
        time_gap = (
            observation.timestamp
            -
            global_track.last_seen
        )

        if time_gap < 0.0:
            return None

        if (
            time_gap
            >
            self.max_reid_gap_sec
        ):
            return None

        distance = (
            global_track.distance_to(
                observation.bev_x,
                observation.bev_y,
            )
        )

        allowed_distance = (
            self._allowed_distance(
                time_gap
            )
        )

        if (
            distance
            >
            allowed_distance
        ):
            return None

        distance_score = (
            distance
            /
            max(
                allowed_distance,
                1.0,
            )
        )

        time_score = (
            time_gap
            /
            max(
                self.max_reid_gap_sec,
                0.001,
            )
        )

        score = (
            distance_score
            +
            self.time_weight
            *
            time_score
        )

        if (
            global_track.class_name
            !=
            observation.class_name
        ):
            score += (
                self.class_mismatch_penalty
            )

        if (
            score
            >
            self.max_match_score
        ):
            return None

        return (
            score,
            distance,
            time_gap,
        )

    def _find_best_global_track(
        self,
        observation: GlobalObservation,
        seen_cameras_by_global: dict[
            int,
            set[str],
        ],
    ) -> tuple[
        GlobalTrack | None,
        float,
        float,
    ]:
        best_track = None
        best_score = float("inf")
        best_distance = 0.0
        best_time_gap = 0.0

        for global_track in (
            self.global_tracks.values()
        ):
            seen_cameras = (
                seen_cameras_by_global.get(
                    global_track.global_id,
                    set(),
                )
            )

            # 같은 프레임에서 같은 카메라의 서로 다른
            # Local ID 두 개를 같은 Global ID로 합치는 것을 방지.
            if (
                observation.camera_id
                in
                seen_cameras
            ):
                continue

            result = (
                self._candidate_score(
                    global_track,
                    observation,
                )
            )

            if result is None:
                continue

            (
                score,
                distance,
                time_gap,
            ) = result

            if score >= best_score:
                continue

            best_track = global_track
            best_score = score
            best_distance = distance
            best_time_gap = time_gap

        return (
            best_track,
            best_distance,
            best_time_gap,
        )

    def _bind_local_track(
        self,
        observation: GlobalObservation,
        global_track: GlobalTrack,
        distance: float | None = None,
        time_gap: float | None = None,
    ) -> None:
        previous_global_id = (
            self.local_to_global.get(
                observation.local_key
            )
        )

        self.local_to_global[
            observation.local_key
        ] = global_track.global_id

        global_track.local_keys.add(
            observation.local_key
        )

        if (
            self.print_events
            and
            previous_global_id is None
        ):
            message = (
                f"[GLOBAL] "
                f"{observation.camera_id.upper()}"
                f"-L{observation.local_id:03d} "
                f"-> "
                f"{global_track.label}"
            )

            if (
                distance is not None
                and
                time_gap is not None
            ):
                message += (
                    f" | "
                    f"distance={distance:.1f}px "
                    f"gap={time_gap:.2f}s"
                )

            print(message)

    def update(
        self,
        observations: list[
            GlobalObservation
        ],
        timestamp: float,
    ) -> dict[
        LocalTrackKey,
        int,
    ]:
        timestamp = float(
            timestamp
        )

        assignments: dict[
            LocalTrackKey,
            int,
        ] = {}

        seen_cameras_by_global: dict[
            int,
            set[str],
        ] = {}

        unbound_observations = []

        # -------------------------------------------------
        # 1. 기존 local -> global binding 우선 갱신
        # -------------------------------------------------

        for observation in observations:
            global_id = (
                self.local_to_global.get(
                    observation.local_key
                )
            )

            if global_id is None:
                unbound_observations.append(
                    observation
                )
                continue

            global_track = (
                self.global_tracks.get(
                    global_id
                )
            )

            if global_track is None:
                del self.local_to_global[
                    observation.local_key
                ]

                unbound_observations.append(
                    observation
                )
                continue

            self._update_global_track(
                global_track,
                observation,
            )

            assignments[
                observation.local_key
            ] = global_id

            seen_cameras_by_global.setdefault(
                global_id,
                set(),
            ).add(
                observation.camera_id
            )

        # -------------------------------------------------
        # 2. 새로운 LocalTrack을 기존 GlobalTrack과 매칭
        # -------------------------------------------------

        for observation in (
            unbound_observations
        ):
            (
                best_track,
                distance,
                time_gap,
            ) = self._find_best_global_track(
                observation,
                seen_cameras_by_global,
            )

            if best_track is None:
                best_track = (
                    self._create_global_track(
                        observation
                    )
                )

                distance = None
                time_gap = None

            else:
                self._bind_local_track(
                    observation,
                    best_track,
                    distance=distance,
                    time_gap=time_gap,
                )

                self._update_global_track(
                    best_track,
                    observation,
                )

            assignments[
                observation.local_key
            ] = (
                best_track.global_id
            )

            seen_cameras_by_global.setdefault(
                best_track.global_id,
                set(),
            ).add(
                observation.camera_id
            )

        self._remove_stale_global_tracks(
            timestamp
        )

        return assignments

    def _remove_stale_global_tracks(
        self,
        timestamp: float,
    ) -> None:
        stale_ids = []

        for global_id, global_track in (
            self.global_tracks.items()
        ):
            age = (
                timestamp
                -
                global_track.last_seen
            )

            if (
                age
                >
                self.retention_sec
            ):
                stale_ids.append(
                    global_id
                )

        for global_id in stale_ids:
            global_track = (
                self.global_tracks.pop(
                    global_id
                )
            )

            if self.print_events:
                print(
                    f"[GLOBAL] "
                    f"{global_track.label} expired "
                    f"after "
                    f"{timestamp - global_track.last_seen:.1f}s"
                )

    def get_global_id(
        self,
        camera_id: str,
        local_id: int,
    ) -> int | None:
        return self.local_to_global.get(
            (
                camera_id,
                local_id,
            )
        )

    def get_global_track(
        self,
        global_id: int,
    ) -> GlobalTrack | None:
        return self.global_tracks.get(
            global_id
        )

    def current_tracks(
        self,
    ) -> list[
        GlobalTrack
    ]:
        return list(
            self.global_tracks.values()
        )