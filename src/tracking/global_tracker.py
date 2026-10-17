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
    entry_eligible: bool = False

    @property
    def local_key(self) -> LocalTrackKey:
        return (
            self.camera_id,
            self.local_id,
        )


@dataclass
class _EntryEvidence:
    history: deque[tuple[float, float, float]] = field(default_factory=deque)
    inside_frames: int = 0
    admitted: bool = False


class EntryGate:
    """Remember cam01 vehicles that crossed the configured IN zone."""

    def __init__(self, config: dict, camera_size: tuple[int, int] | None = None):
        self.camera_id = str(config["camera_id"])
        reference_width, reference_height = config.get("reference_size", (640, 360))
        if reference_width <= 0 or reference_height <= 0:
            raise ValueError("invalid gate reference size")
        camera_width, camera_height = camera_size or (reference_width, reference_height)
        if camera_width <= 0 or camera_height <= 0:
            raise ValueError("invalid gate camera size")
        scale_x = camera_width / reference_width
        scale_y = camera_height / reference_height
        zones = [zone for zone in config["zones"] if zone["type"] == "IN"]
        if len(zones) != 1:
            raise ValueError("exactly one IN gate zone is required")
        zone = zones[0]
        self.box = tuple(float(value) * scale for value, scale in zip(
            zone["box"], (scale_x, scale_y, scale_x, scale_y)))
        dx, dy = (float(value) for value in zone["direction"])
        reference_length = math.hypot(dx, dy)
        dx, dy = dx * scale_x, dy * scale_y
        length = math.hypot(dx, dy)
        if (len(self.box) != 4 or self.box[0] >= self.box[2]
                or self.box[1] >= self.box[3] or length <= 0):
            raise ValueError("invalid IN gate geometry")
        self.direction = (dx / length, dy / length)
        self.min_overlap_ratio = float(config.get("min_overlap_ratio", 0.3))
        self.min_frames = int(config.get("min_frames_in_zone", 3))
        self.window_sec = float(config.get("direction_window_sec", 0.5))
        self.min_speed = (float(config.get("min_speed_px_per_sec", 10.0))
                          * length / reference_length)
        if (not 0 <= self.min_overlap_ratio <= 1 or self.min_frames < 1
                or self.window_sec <= 0 or self.min_speed < 0):
            raise ValueError("invalid IN gate thresholds")
        self.evidence: dict[int, _EntryEvidence] = {}

    def observe(self, track, timestamp: float) -> bool:
        if track.camera_id != self.camera_id:
            return False
        evidence = self.evidence.setdefault(track.local_id, _EntryEvidence())
        if evidence.admitted or track.occluded:
            return evidence.admitted
        evidence.history.append((timestamp, track.ground_x, track.ground_y))
        while (len(evidence.history) > 2
               and evidence.history[1][0] <= timestamp - self.window_sec):
            evidence.history.popleft()

        x1, y1, x2, y2 = track.bbox
        bx1, by1, bx2, by2 = self.box
        overlap = max(0.0, min(x2, bx2) - max(x1, bx1)) * max(
            0.0, min(y2, by2) - max(y1, by1))
        zone_area = (bx2 - bx1) * (by2 - by1)
        if overlap / zone_area <= self.min_overlap_ratio:
            evidence.inside_frames = 0
            return False
        evidence.inside_frames += 1
        if evidence.inside_frames < self.min_frames or len(evidence.history) < 2:
            return False
        first_time, first_x, first_y = evidence.history[0]
        elapsed = timestamp - first_time
        if elapsed <= 0:
            return False
        speed_along = (((track.ground_x - first_x) * self.direction[0]
                        + (track.ground_y - first_y) * self.direction[1]) / elapsed)
        evidence.admitted = speed_along >= self.min_speed
        return evidence.admitted


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
    candidate_first_seen: float | None = None

    # 같은 후보가 몇 번 연속 선택됐는지.
    candidate_count: int = 0

    # 충분히 반복 검증되어 provisional 상태가 된 Global ID.
    provisional_global_id: int | None = None

    # 마지막 probe 시각.
    last_seen: float = 0.0

    # BEV 이동 일치 확인용 기록 (bev_motion_window_sec 동안).
    motion_history: deque[BevSample] = field(
        default_factory=deque
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

        last_position_match_distance_px: float = 200.0,

        max_speed_px_per_sec: float = 180.0,

        time_weight: float = 0.10,

        class_mismatch_penalty: float = 0.20,

        max_match_score: float = 0.95,

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
        probe_handoff_grace_sec: float = 2.0,
        overlap_match_distance_px: float = 120.0,
        overlap_window_sec: float = 0.5,
        overlap_score_bonus: float = 0.15,
        handoff_confirmation_frames: int = 3,
        entry_camera_id: str = "cam01",
        bev_motion_window_sec: float = 1.0,
        bev_motion_min_px: float = 30.0,
        bev_motion_min_straightness: float = 0.8,
        bev_motion_max_angle_deg: float = 45.0,
        bev_motion_max_speed_ratio: float = 2.5,
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

        self.last_position_match_distance_px = max(
            0.0, float(last_position_match_distance_px)
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
        self.probe_handoff_grace_sec = max(0.0, float(probe_handoff_grace_sec))

        self.overlap_match_distance_px = float(overlap_match_distance_px)
        self.overlap_window_sec = float(overlap_window_sec)
        self.overlap_score_bonus = float(overlap_score_bonus)
        self.handoff_confirmation_frames = max(1, int(handoff_confirmation_frames))
        self.entry_camera_id = entry_camera_id
        self.bev_motion_window_sec = float(bev_motion_window_sec)
        self.bev_motion_min_px = float(bev_motion_min_px)
        self.bev_motion_min_straightness = float(bev_motion_min_straightness)
        self.bev_motion_max_angle_deg = float(bev_motion_max_angle_deg)
        self.bev_motion_max_speed_ratio = max(1.0, float(bev_motion_max_speed_ratio))
        if (self.overlap_match_distance_px < 0 or self.overlap_window_sec < 0
                or self.overlap_score_bonus < 0):
            raise ValueError("invalid camera overlap settings")

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
        self.handoff_candidates: dict[LocalTrackKey, tuple[int, int, float]] = {}
        self.entry_created_keys: set[LocalTrackKey] = set()

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

        probe.motion_history.append(
            BevSample(observation.timestamp, observation.bev_x, observation.bev_y)
        )
        while (len(probe.motion_history) > 2
               and probe.motion_history[0].timestamp
               < observation.timestamp - self.bev_motion_window_sec):
            probe.motion_history.popleft()

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

        if not observation.entry_eligible or observation.camera_id != self.entry_camera_id:
            raise ValueError("Global IDs may only start at the entrance")

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
        self.entry_created_keys.add(observation.local_key)

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

        # Two cameras may see the same car in one mosaic frame. Keep both
        # local bindings, but count their shared timestamp as one motion sample.
        if observation.timestamp == global_track.last_seen:
            global_track.local_keys.add(observation.local_key)
            global_track.observation_count += 1
            return

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
        max_time_gap_sec: float | None = None,
    ) -> tuple[
        float,
        float,
        float,
        float | None,
    ] | None:

        changing_camera = observation.camera_id != global_track.current_camera_id
        # A fresh local ID in the current camera should not inherit a car that
        # just left the same view. Cross-camera matches use BEV and time.
        if not changing_camera and observation.local_key not in global_track.local_keys:
            return None

        time_gap = (
            observation.timestamp
            -
            global_track.last_seen
        )

        max_gap = self.max_reid_gap_sec if max_time_gap_sec is None else max_time_gap_sec
        if (
            time_gap < 0.0
            or
            time_gap
            >
            max_gap
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

        last_distance = math.hypot(
            observation.bev_x - global_track.last_bev_x,
            observation.bev_y - global_track.last_bev_y,
        )

        allowed_distance = (
            self._allowed_distance(
                time_gap
            )
        )

        overlapping_view = (
            changing_camera and time_gap <= self.overlap_window_sec
            and predicted_distance <= self.overlap_match_distance_px
        )
        if overlapping_view:
            allowed_distance = max(allowed_distance, self.overlap_match_distance_px)

        fallback_limit = self.last_position_match_distance_px
        if max_time_gap_sec is not None and max_time_gap_sec > self.max_reid_gap_sec:
            fallback_limit = self.max_match_distance_px
        use_last_position = (
            changing_camera
            and last_distance <= min(fallback_limit, allowed_distance)
            and last_distance / max(allowed_distance, 1.0) + 0.20
            < predicted_distance / max(allowed_distance, 1.0)
        )
        spatial_distance = last_distance if use_last_position else predicted_distance
        if spatial_distance > allowed_distance:
            return None

        position_score = (
            spatial_distance / max(allowed_distance, 1.0)
            + (0.20 if use_last_position else 0.0)
        )

        time_score = (
            time_gap
            /
            max(
                max_gap,
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

        if overlapping_view:
            score = max(0.0, score - self.overlap_score_bonus)

        if (
            score
            >
            self.max_match_score
        ):

            return None

        return (
            score,
            spatial_distance,
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
        max_time_gap_sec: float | None = None,
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
                    max_time_gap_sec=max_time_gap_sec,
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
        max_time_gap_sec: float | None = None,
    ) -> tuple[
        GlobalTrack | None,
        float,
        float,
        bool,
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
                max_time_gap_sec=max_time_gap_sec,
            )
        )

        if not candidates:

            return (
                None,
                0.0,
                0.0,
                False,
            )

        if (len(candidates) > 1
                and candidates[1][0] - candidates[0][0] < self.min_score_margin):
            return (None, 0.0, 0.0, True)

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
            False,
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

        # One GID may have observations in several cameras, but only one
        # current Local ID per camera. Retire an older ID before replacing it.
        for old_key in list(global_track.local_keys):
            if old_key[0] == observation.camera_id and old_key != observation.local_key:
                global_track.local_keys.remove(old_key)
                self.local_to_global.pop(old_key, None)

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

    def _probe_max_gap(self, probe: ProbeState, timestamp: float) -> float:
        if probe.provisional_global_id is None or probe.candidate_first_seen is None:
            return self.max_reid_gap_sec
        # The first appearance had to pass the normal gap limit. Allow only
        # the time spent confirming this same Local ID to extend that limit.
        confirmation_time = max(0.0, timestamp - probe.candidate_first_seen)
        return self.max_reid_gap_sec + min(
            self.probe_handoff_grace_sec, confirmation_time)

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
                max_time_gap_sec=self._probe_max_gap(probe, observation.timestamp),
            )
        )

        # 기존 GID 후보가 없다.
        if not candidates:

            probe.candidate_global_id = (
                None
            )
            probe.candidate_first_seen = None

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
            probe.candidate_first_seen = None

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
            probe.candidate_first_seen = observation.timestamp

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

    def bev_motion_matches(
        self,
        local_key: LocalTrackKey,
        global_id: int,
    ) -> bool:
        """
        UNKNOWN 차량이 BEV에서 실제로 꾸준히 움직였고, 그 속도 벡터가
        후보 GID의 마지막 속도 벡터와 비슷한지.

        카메라 쪽으로 다가오는 먼 차량은 이미지에서 거의 움직이지 않아
        Local 움직임 판정(ACTIVE)이 늦다. BEV 이동으로 대신 확인한다.
        주차 차량의 박스 흔들림은 BEV 이동이 작거나 경로가 곧지 않다.
        """

        probe = self.probes.get(local_key)
        global_track = self.global_tracks.get(global_id)

        if probe is None or global_track is None:
            return False

        history = probe.motion_history

        if len(history) < 2:
            return False

        first, last = history[0], history[-1]
        span = last.timestamp - first.timestamp

        if span < self.bev_motion_window_sec * 0.9:
            return False

        net = math.hypot(last.x - first.x, last.y - first.y)
        path = sum(
            math.hypot(b.x - a.x, b.y - a.y)
            for a, b in zip(history, list(history)[1:])
        )

        if (net < self.bev_motion_min_px
                or net < self.bev_motion_min_straightness * path):
            return False

        speed = net / span
        track_speed = global_track.speed_px_per_sec

        if track_speed < self.min_direction_speed_px_per_sec:
            return False

        cos_angle = (
            ((last.x - first.x) * global_track.velocity_x
             + (last.y - first.y) * global_track.velocity_y)
            / (net * track_speed)
        )

        if cos_angle < math.cos(math.radians(self.bev_motion_max_angle_deg)):
            return False

        ratio = speed / track_speed

        return (1.0 / self.bev_motion_max_speed_ratio
                <= ratio <= self.bev_motion_max_speed_ratio)

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

            # An actual IN crossing takes precedence even if this Local ID was
            # tentatively linked to a different entrance-created vehicle.
            if (observation.entry_eligible and observation.camera_id == self.entry_camera_id
                    and observation.local_key not in self.entry_created_keys):
                previous_id = self.local_to_global.pop(observation.local_key, None)
                if previous_id in self.global_tracks:
                    self.global_tracks[previous_id].local_keys.discard(observation.local_key)
                unbound_observations.append(observation)
                continue

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

        for observation in sorted(
            unbound_observations,
            key=lambda item: not (item.entry_eligible and item.camera_id == self.entry_camera_id),
        ):

            # The entrance is the only place that allocates a new identity.
            # A newly admitted local car is a new arrival, not a handoff.
            if observation.entry_eligible and observation.camera_id == self.entry_camera_id:
                entrant = self._create_global_track(observation)
                assignments[observation.local_key] = entrant.global_id
                seen_cameras_by_global.setdefault(entrant.global_id, set()).add(
                    observation.camera_id)
                continue

            probe = self.probes.get(
                observation.local_key
            )

            provisional_id = (
                probe.provisional_global_id
                if probe is not None
                else None
            )
            if (probe is not None and provisional_id is not None
                    and observation.timestamp - probe.last_seen > self.probe_retention_sec):
                provisional_id = None
            provisional_max_gap = (
                self._probe_max_gap(probe, observation.timestamp)
                if probe is not None and provisional_id is not None else None
            )

            best_track = None
            distance = None
            time_gap = None
            ambiguous = False

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
                            max_time_gap_sec=provisional_max_gap,
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

            if best_track is not None:
                reviewed, reviewed_distance, reviewed_gap, ambiguous = (
                    self._find_best_global_track(
                        observation, seen_cameras_by_global,
                        max_time_gap_sec=provisional_max_gap)
                )
                if ambiguous:
                    self.handoff_candidates.pop(observation.local_key, None)
                    continue
                if reviewed is None or reviewed.global_id != best_track.global_id:
                    best_track = None
                else:
                    distance, time_gap = reviewed_distance, reviewed_gap

            if best_track is None:

                (
                    best_track,
                    distance_value,
                    time_gap_value,
                    ambiguous,
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

            if ambiguous:
                self.handoff_candidates.pop(observation.local_key, None)
                continue

            if (best_track is not None
                    and observation.camera_id != best_track.current_camera_id
                    and provisional_id != best_track.global_id):
                previous_id, count, last_seen = self.handoff_candidates.get(
                    observation.local_key, (None, 0, observation.timestamp))
                count = (count + 1 if previous_id == best_track.global_id
                         and observation.timestamp - last_seen <= self.probe_retention_sec else 1)
                self.handoff_candidates[observation.local_key] = (
                    best_track.global_id, count, observation.timestamp)
                if count < self.handoff_confirmation_frames:
                    continue

            # ---------------------------------------------
            # 2-3. 기존 GID가 없으면 새 GID
            # ---------------------------------------------

            if best_track is None:
                # No entrance observation, so keep this Local ID unassigned.
                self.handoff_candidates.pop(observation.local_key, None)
                continue

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

            self.handoff_candidates.pop(observation.local_key, None)

            seen_cameras_by_global.setdefault(
                best_track.global_id,
                set(),
            ).add(
                observation.camera_id
            )

        self._remove_stale_probes(
            timestamp
        )

        return assignments

    # =====================================================
    # Cleanup
    # =====================================================

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

        self.handoff_candidates = {
            key: candidate for key, candidate in self.handoff_candidates.items()
            if timestamp - candidate[2] <= self.probe_retention_sec
            and candidate[0] in self.global_tracks
        }

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
