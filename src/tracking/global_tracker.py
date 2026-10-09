from __future__ import annotations

import math
from collections import deque
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
class BevSample:
    timestamp: float
    x: float
    y: float


@dataclass
class ProbeState:
    # UNKNOWN 차량이 움직이기 시작했을 때
    # 임시로 모으는 BEV 위치 기록.
    history: deque[BevSample] = field(
        default_factory=deque
    )

    # 현재 가장 가능성이 높은 기존 Global ID.
    candidate_global_id: int | None = None

    # 같은 후보가 몇 번 연속 선택됐는지.
    candidate_count: int = 0

    # 충분히 반복 검증되어 provisional 상태가 된 Global ID.
    provisional_global_id: int | None = None

    # 마지막 probe 시각.
    last_seen: float = 0.0


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

    # 최근 BEV 이동 궤적.
    bev_history: deque[BevSample] = field(
        default_factory=deque
    )

    # BEV 기준 속도 벡터.
    velocity_x: float = 0.0
    velocity_y: float = 0.0

    # BEV 기준 속력.
    speed_px_per_sec: float = 0.0

    # 정규화된 진행 방향.
    direction_x: float = 0.0
    direction_y: float = 0.0

    @property
    def label(self) -> str:
        return f"G{self.global_id:03d}"


    def predicted_position(
        self,
        timestamp: float,
    ) -> tuple[float, float]:

        time_gap = max(
            0.0,
            float(timestamp) - self.last_seen,
        )

        return (
            self.last_bev_x
            + self.velocity_x * time_gap,

            self.last_bev_y
            + self.velocity_y * time_gap,
        )


class GlobalTracker:
    def __init__(
        self,

        max_reid_gap_sec: float = 3.0,

        base_match_distance_px: float = 80.0,

        max_match_distance_px: float = 300.0,

        max_speed_px_per_sec: float = 180.0,

        time_weight: float = 0.10,

        class_mismatch_penalty: float = 0.20,

        max_match_score: float = 0.95,

        retention_sec: float = 120.0,

        print_events: bool = True,

        motion_history_sec: float = 0.8,

        prediction_weight: float = 0.55,

        direction_weight: float = 0.25,

        speed_weight: float = 0.10,

        direction_soft_limit_deg: float = 60.0,

        direction_hard_limit_deg: float = 120.0,

        min_direction_speed_px_per_sec: float = 15.0,

        provisional_confirm_count: int = 3,

        min_score_margin: float = 0.15,

        probe_retention_sec: float = 3.0,
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

        self.motion_history_sec = max(
            0.2,
            float(
                motion_history_sec
            ),
        )

        self.prediction_weight = max(
            0.0,
            float(
                prediction_weight
            ),
        )

        self.direction_weight = max(
            0.0,
            float(
                direction_weight
            ),
        )

        self.speed_weight = max(
            0.0,
            float(
                speed_weight
            ),
        )

        self.direction_soft_limit_deg = float(
            direction_soft_limit_deg
        )

        self.direction_hard_limit_deg = float(
            direction_hard_limit_deg
        )

        self.min_direction_speed_px_per_sec = max(
            0.0,
            float(
                min_direction_speed_px_per_sec
            ),
        )

        self.provisional_confirm_count = max(
            1,
            int(
                provisional_confirm_count
            ),
        )

        self.min_score_margin = max(
            0.0,
            float(
                min_score_margin
            ),
        )

        self.probe_retention_sec = max(
            0.5,
            float(
                probe_retention_sec
            ),
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

        # ACTIVE 확정 전 UNKNOWN 차량에 대한
        # provisional global matching 정보.
        self.probes: dict[
            LocalTrackKey,
            ProbeState,
        ] = {}

    # =====================================================
    # Motion helpers
    # =====================================================

    @staticmethod
    def _linear_velocity(
        history: deque[BevSample],
    ) -> tuple[
        float,
        float,
    ]:

        if len(history) < 2:
            return (
                0.0,
                0.0,
            )

        samples = list(
            history
        )

        mean_t = (
            sum(
                sample.timestamp
                for sample in samples
            )
            /
            len(samples)
        )

        mean_x = (
            sum(
                sample.x
                for sample in samples
            )
            /
            len(samples)
        )

        mean_y = (
            sum(
                sample.y
                for sample in samples
            )
            /
            len(samples)
        )

        denominator = sum(
            (
                sample.timestamp
                -
                mean_t
            )
            ** 2
            for sample in samples
        )

        if denominator <= 1e-9:
            return (
                0.0,
                0.0,
            )

        velocity_x = (
            sum(
                (
                    sample.timestamp
                    -
                    mean_t
                )
                *
                (
                    sample.x
                    -
                    mean_x
                )
                for sample in samples
            )
            /
            denominator
        )

        velocity_y = (
            sum(
                (
                    sample.timestamp
                    -
                    mean_t
                )
                *
                (
                    sample.y
                    -
                    mean_y
                )
                for sample in samples
            )
            /
            denominator
        )

        return (
            velocity_x,
            velocity_y,
        )

    @staticmethod
    def _direction(
        velocity_x: float,
        velocity_y: float,
    ) -> tuple[
        float,
        float,
        float,
    ]:

        speed = math.hypot(
            velocity_x,
            velocity_y,
        )

        if speed <= 1e-9:
            return (
                0.0,
                0.0,
                0.0,
            )

        return (
            velocity_x / speed,
            velocity_y / speed,
            speed,
        )

    def _trim_history(
        self,
        history: deque[BevSample],
        timestamp: float,
    ) -> None:

        keep_after = (
            timestamp
            -
            self.motion_history_sec
        )

        while (
            len(history) > 2
            and
            history[0].timestamp
            <
            keep_after
        ):

            history.popleft()

    def _append_global_history(
        self,
        global_track: GlobalTrack,
        observation: GlobalObservation,
    ) -> None:

        global_track.bev_history.append(
            BevSample(
                timestamp=(
                    observation.timestamp
                ),
                x=(
                    observation.bev_x
                ),
                y=(
                    observation.bev_y
                ),
            )
        )

        self._trim_history(
            global_track.bev_history,
            observation.timestamp,
        )

        velocity_x, velocity_y = (
            self._linear_velocity(
                global_track.bev_history
            )
        )

        (
            direction_x,
            direction_y,
            speed,
        ) = self._direction(
            velocity_x,
            velocity_y,
        )

        global_track.velocity_x = (
            velocity_x
        )

        global_track.velocity_y = (
            velocity_y
        )

        global_track.direction_x = (
            direction_x
        )

        global_track.direction_y = (
            direction_y
        )

        global_track.speed_px_per_sec = (
            speed
        )

    def _append_probe_history(
        self,
        probe: ProbeState,
        observation: GlobalObservation,
    ) -> None:

        probe.history.append(
            BevSample(
                timestamp=(
                    observation.timestamp
                ),
                x=(
                    observation.bev_x
                ),
                y=(
                    observation.bev_y
                ),
            )
        )

        self._trim_history(
            probe.history,
            observation.timestamp,
        )

        probe.last_seen = (
            observation.timestamp
        )

    # =====================================================
    # Global track
    # =====================================================

    def _create_global_track(
        self,
        observation: GlobalObservation,
    ) -> GlobalTrack:

        global_id = (
            self.next_global_id
        )

        self.next_global_id += 1

        global_track = GlobalTrack(

            global_id=global_id,

            first_seen=(
                observation.timestamp
            ),

            last_seen=(
                observation.timestamp
            ),

            last_bev_x=(
                observation.bev_x
            ),

            last_bev_y=(
                observation.bev_y
            ),

            current_camera_id=(
                observation.camera_id
            ),

            current_local_id=(
                observation.local_id
            ),

            state=(
                observation.state
            ),

            class_name=(
                observation.class_name
            ),

            confidence=(
                observation.confidence
            ),
        )

        global_track.local_keys.add(
            observation.local_key
        )

        self._append_global_history(
            global_track,
            observation,
        )

        self.global_tracks[
            global_id
        ] = global_track

        self.local_to_global[
            observation.local_key
        ] = global_id

        self.probes.pop(
            observation.local_key,
            None,
        )

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

        self._append_global_history(
            global_track,
            observation,
        )

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

    # =====================================================
    # Candidate geometry
    # =====================================================

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

    @staticmethod
    def _angle_degrees(
        ax: float,
        ay: float,
        bx: float,
        by: float,
    ) -> float | None:

        norm_a = math.hypot(
            ax,
            ay,
        )

        norm_b = math.hypot(
            bx,
            by,
        )

        if (
            norm_a <= 1e-9
            or
            norm_b <= 1e-9
        ):

            return None

        cosine = (
            (
                ax * bx
                +
                ay * by
            )
            /
            (
                norm_a
                *
                norm_b
            )
        )

        cosine = max(
            -1.0,
            min(
                1.0,
                cosine,
            ),
        )

        return math.degrees(
            math.acos(
                cosine
            )
        )

    # =====================================================
    # Candidate score
    # =====================================================

    def _candidate_score(
        self,
        global_track: GlobalTrack,
        observation: GlobalObservation,
        local_velocity: tuple[
            float,
            float,
        ]
        |
        None = None,
    ) -> tuple[
        float,
        float,
        float,
        float | None,
    ] | None:

        time_gap = (
            observation.timestamp
            -
            global_track.last_seen
        )

        if (
            time_gap < 0.0
            or
            time_gap
            >
            self.max_reid_gap_sec
        ):

            return None

        # 기존 차량이 이전 속도와 방향을 그대로 유지했다고 가정한
        # 현재 시점 예상 위치.
        (
            predicted_x,
            predicted_y,
        ) = global_track.predicted_position(
            observation.timestamp
        )

        predicted_distance = math.hypot(

            observation.bev_x
            -
            predicted_x,

            observation.bev_y
            -
            predicted_y,
        )

        allowed_distance = (
            self._allowed_distance(
                time_gap
            )
        )

        if (
            predicted_distance
            >
            allowed_distance
        ):

            return None

        position_score = (
            predicted_distance
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

        direction_score = None
        speed_score = None
        direction_angle = None

        if local_velocity is not None:

            (
                local_velocity_x,
                local_velocity_y,
            ) = local_velocity

            (
                _,
                _,
                local_speed,
            ) = self._direction(
                local_velocity_x,
                local_velocity_y,
            )

            global_speed = (
                global_track.speed_px_per_sec
            )

            if (
                local_speed
                >=
                self.min_direction_speed_px_per_sec
                and
                global_speed
                >=
                self.min_direction_speed_px_per_sec
            ):

                direction_angle = (
                    self._angle_degrees(

                        global_track.direction_x,
                        global_track.direction_y,

                        local_velocity_x,
                        local_velocity_y,
                    )
                )

                # 거의 반대 방향이면 같은 차량으로 보지 않는다.
                if (
                    direction_angle is not None
                    and
                    direction_angle
                    >
                    self.direction_hard_limit_deg
                ):

                    return None

                if direction_angle is not None:

                    direction_score = min(
                        1.0,
                        direction_angle
                        /
                        max(
                            self.direction_soft_limit_deg,
                            1.0,
                        ),
                    )

                speed_score = (
                    abs(
                        global_speed
                        -
                        local_speed
                    )
                    /
                    max(
                        global_speed,
                        local_speed,
                        self.min_direction_speed_px_per_sec,
                        1.0,
                    )
                )

        # 방향/속도가 아직 계산되지 않은 초기 probe에서는
        # 해당 항목을 score에서 제외하고 나머지 가중치를 재정규화한다.
        weighted_sum = (
            self.prediction_weight
            *
            position_score
        )

        weight_sum = (
            self.prediction_weight
        )

        if self.time_weight > 0.0:

            weighted_sum += (
                self.time_weight
                *
                time_score
            )

            weight_sum += (
                self.time_weight
            )

        if (
            direction_score is not None
            and
            self.direction_weight > 0.0
        ):

            weighted_sum += (
                self.direction_weight
                *
                direction_score
            )

            weight_sum += (
                self.direction_weight
            )

        if (
            speed_score is not None
            and
            self.speed_weight > 0.0
        ):

            weighted_sum += (
                self.speed_weight
                *
                speed_score
            )

            weight_sum += (
                self.speed_weight
            )

        if weight_sum <= 1e-9:
            return None

        score = (
            weighted_sum
            /
            weight_sum
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
            predicted_distance,
            time_gap,
            direction_angle,
        )

    def _candidate_list(
        self,
        observation: GlobalObservation,
        seen_cameras_by_global: dict[
            int,
            set[str],
        ]
        |
        None = None,
        local_velocity: tuple[
            float,
            float,
        ]
        |
        None = None,
    ) -> list[
        tuple[
            float,
            GlobalTrack,
            float,
            float,
            float | None,
        ]
    ]:

        candidates = []

        if seen_cameras_by_global is None:
            seen_cameras_by_global = {}

        for global_track in (
            self.global_tracks.values()
        ):

            seen_cameras = (
                seen_cameras_by_global.get(
                    global_track.global_id,
                    set(),
                )
            )

            # 같은 프레임 같은 카메라에서
            # 서로 다른 두 Local ID를 하나의 GID로 합치는 것을 방지.
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

                    local_velocity=(
                        local_velocity
                    ),
                )
            )

            if result is None:
                continue

            (
                score,
                distance,
                time_gap,
                angle,
            ) = result

            candidates.append(
                (
                    score,
                    global_track,
                    distance,
                    time_gap,
                    angle,
                )
            )

        candidates.sort(
            key=lambda item: item[0]
        )

        return candidates

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

        probe = self.probes.get(
            observation.local_key
        )

        local_velocity = None

        if (
            probe is not None
            and
            len(probe.history) >= 2
        ):

            local_velocity = (
                self._linear_velocity(
                    probe.history
                )
            )

        candidates = (
            self._candidate_list(

                observation,

                seen_cameras_by_global=(
                    seen_cameras_by_global
                ),

                local_velocity=(
                    local_velocity
                ),
            )
        )

        if not candidates:

            return (
                None,
                0.0,
                0.0,
            )

        (
            _,
            best_track,
            distance,
            time_gap,
            _,
        ) = candidates[0]

        return (
            best_track,
            distance,
            time_gap,
        )

    # =====================================================
    # Binding
    # =====================================================

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
        ] = (
            global_track.global_id
        )

        global_track.local_keys.add(
            observation.local_key
        )

        self.probes.pop(
            observation.local_key,
            None,
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

            print(
                message
            )

    # =====================================================
    # UNKNOWN early probe
    # =====================================================

    def probe_existing(
        self,
        observation: GlobalObservation,
    ) -> int | None:

        # 이미 확정된 LocalTrack이면 probe 불필요.
        confirmed_global_id = (
            self.local_to_global.get(
                observation.local_key
            )
        )

        if confirmed_global_id is not None:

            return (
                confirmed_global_id
            )

        probe = self.probes.setdefault(
            observation.local_key,
            ProbeState(),
        )

        self._append_probe_history(
            probe,
            observation,
        )

        local_velocity = None

        if len(probe.history) >= 2:

            local_velocity = (
                self._linear_velocity(
                    probe.history
                )
            )

        candidates = (
            self._candidate_list(

                observation,

                local_velocity=(
                    local_velocity
                ),
            )
        )

        # 기존 GID 후보가 없다.
        if not candidates:

            probe.candidate_global_id = (
                None
            )

            probe.candidate_count = 0

            probe.provisional_global_id = (
                None
            )

            self._remove_stale_probes(
                observation.timestamp
            )

            return None

        (
            best_score,
            best_track,
            _,
            _,
            _,
        ) = candidates[0]

        if len(candidates) > 1:

            second_score = (
                candidates[1][0]
            )

        else:

            second_score = float(
                "inf"
            )

        score_margin = (
            second_score
            -
            best_score
        )

        # 1등과 2등 후보가 너무 비슷하면
        # 잘못된 Global ID를 잡지 않고 보류.
        if (
            score_margin
            <
            self.min_score_margin
        ):

            probe.candidate_global_id = (
                None
            )

            probe.candidate_count = 0

            probe.provisional_global_id = (
                None
            )

            self._remove_stale_probes(
                observation.timestamp
            )

            return None

        if (
            probe.candidate_global_id
            ==
            best_track.global_id
        ):

            probe.candidate_count += 1

        else:

            probe.candidate_global_id = (
                best_track.global_id
            )

            probe.candidate_count = 1

            probe.provisional_global_id = (
                None
            )

        # 같은 기존 GID가 여러 프레임 연속
        # 최적 후보일 경우 provisional 확정.
        if (
            probe.candidate_count
            >=
            self.provisional_confirm_count
        ):

            probe.provisional_global_id = (
                best_track.global_id
            )

        self._remove_stale_probes(
            observation.timestamp
        )

        return (
            probe.provisional_global_id
        )

    def get_provisional_global_id(
        self,
        camera_id: str,
        local_id: int,
    ) -> int | None:

        probe = self.probes.get(
            (
                camera_id,
                local_id,
            )
        )

        if probe is None:
            return None

        return (
            probe.provisional_global_id
        )

    # =====================================================
    # Main update
    # =====================================================

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
        # 1. 기존 Local -> Global binding 갱신
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
        # 2. 새 LocalTrack
        #
        # UNKNOWN 단계에서 만들어 둔 provisional GID를
        # 먼저 검사한다.
        # -------------------------------------------------

        for observation in (
            unbound_observations
        ):

            probe = self.probes.get(
                observation.local_key
            )

            provisional_id = (
                probe.provisional_global_id
                if probe is not None
                else None
            )

            best_track = None
            distance = None
            time_gap = None

            # ---------------------------------------------
            # 2-1. provisional 후보 우선 재검증
            # ---------------------------------------------

            if provisional_id is not None:

                provisional_track = (
                    self.global_tracks.get(
                        provisional_id
                    )
                )

                same_camera_already_used = (
                    observation.camera_id
                    in
                    seen_cameras_by_global.get(
                        provisional_id,
                        set(),
                    )
                )

                if (
                    provisional_track is not None
                    and
                    not same_camera_already_used
                ):

                    local_velocity = None

                    if (
                        probe is not None
                        and
                        len(probe.history) >= 2
                    ):

                        local_velocity = (
                            self._linear_velocity(
                                probe.history
                            )
                        )

                    result = (
                        self._candidate_score(

                            provisional_track,

                            observation,

                            local_velocity=(
                                local_velocity
                            ),
                        )
                    )

                    if result is not None:

                        (
                            _,
                            distance,
                            time_gap,
                            _,
                        ) = result

                        best_track = (
                            provisional_track
                        )

            # ---------------------------------------------
            # 2-2. provisional이 없거나 최종 검증 실패
            #      → 일반 Global Re-ID
            # ---------------------------------------------

            if best_track is None:

                (
                    best_track,
                    distance_value,
                    time_gap_value,
                ) = self._find_best_global_track(

                    observation,

                    seen_cameras_by_global,
                )

                if best_track is not None:

                    distance = (
                        distance_value
                    )

                    time_gap = (
                        time_gap_value
                    )

            # ---------------------------------------------
            # 2-3. 기존 GID가 없으면 새 GID
            # ---------------------------------------------

            if best_track is None:

                best_track = (
                    self._create_global_track(
                        observation
                    )
                )

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

        self._remove_stale_probes(
            timestamp
        )

        return assignments

    # =====================================================
    # Cleanup
    # =====================================================

    def _remove_stale_global_tracks(
        self,
        timestamp: float,
    ) -> None:

        stale_ids = [

            global_id

            for (
                global_id,
                global_track,
            )
            in self.global_tracks.items()

            if (
                timestamp
                -
                global_track.last_seen
            )
            >
            self.retention_sec
        ]

        for global_id in stale_ids:

            global_track = (
                self.global_tracks.pop(
                    global_id
                )
            )

            # 만료된 Global ID binding도 함께 제거.
            stale_local_keys = [

                local_key

                for (
                    local_key,
                    bound_global_id,
                )
                in self.local_to_global.items()

                if (
                    bound_global_id
                    ==
                    global_id
                )
            ]

            for local_key in (
                stale_local_keys
            ):

                self.local_to_global.pop(
                    local_key,
                    None,
                )

            # probe가 만료된 GID를 보고 있다면 제거.
            for probe in (
                self.probes.values()
            ):

                if (
                    probe.candidate_global_id
                    ==
                    global_id
                ):

                    probe.candidate_global_id = (
                        None
                    )

                    probe.candidate_count = 0

                if (
                    probe.provisional_global_id
                    ==
                    global_id
                ):

                    probe.provisional_global_id = (
                        None
                    )

            if self.print_events:

                print(
                    f"[GLOBAL] "
                    f"{global_track.label} expired "
                    f"after "
                    f"{timestamp - global_track.last_seen:.1f}s"
                )

    def _remove_stale_probes(
        self,
        timestamp: float,
    ) -> None:

        stale_keys = [

            local_key

            for (
                local_key,
                probe,
            )
            in self.probes.items()

            if (
                timestamp
                -
                probe.last_seen
            )
            >
            self.probe_retention_sec
        ]

        for local_key in (
            stale_keys
        ):

            self.probes.pop(
                local_key,
                None,
            )

    # =====================================================
    # Public API
    # =====================================================

    def get_global_id(
        self,
        camera_id: str,
        local_id: int,
    ) -> int | None:

        return (
            self.local_to_global.get(
                (
                    camera_id,
                    local_id,
                )
            )
        )
