"""Associate synchronized camera observations into global vehicle IDs."""

from dataclasses import dataclass
import math
from typing import Iterable


@dataclass(frozen=True)
class AssociationObservation:
    camera_id: str
    local_id: int
    class_id: int
    point: tuple[float, float]
    confidence: float = 0.0


@dataclass
class _GlobalTrack:
    global_id: int
    class_id: int
    point: tuple[float, float]
    last_seen: int


class GlobalVehicleAssociator:
    """Match simultaneous camera observations in BEV pixel coordinates.

    New vehicles are registered only when they first appear in the entry camera.
    Other cameras can reuse an existing ID when their BEV observation is close
    enough to that track and has the same vehicle class.
    """

    def __init__(
        self,
        entry_camera: str = "cam01",
        max_distance: float = 90.0,
        max_missed_updates: int = 30,
    ) -> None:
        if max_distance <= 0:
            raise ValueError("max_distance must be greater than zero")
        if max_missed_updates < 1:
            raise ValueError("max_missed_updates must be at least one")
        self.entry_camera = entry_camera
        self.max_distance = float(max_distance)
        self.max_missed_updates = int(max_missed_updates)
        self._next_id = 1
        self._tick = 0
        self._tracks: dict[int, _GlobalTrack] = {}

    def update(self, observations: Iterable[AssociationObservation]) -> dict[tuple[str, int], int]:
        """Return global IDs for observations visible in this synchronized tick."""
        self._tick += 1
        current = list(observations)
        assignments: dict[tuple[str, int], int] = {}
        used_tracks: set[tuple[int, str]] = set()

        # Register entry-camera vehicles first so overlapping cameras can reuse them.
        ordered = sorted(current, key=lambda item: item.camera_id != self.entry_camera)
        for observation in ordered:
            track = self._closest_track(observation, used_tracks)
            if track is None:
                if observation.camera_id != self.entry_camera:
                    continue
                track = _GlobalTrack(
                    global_id=self._next_id,
                    class_id=observation.class_id,
                    point=observation.point,
                    last_seen=self._tick,
                )
                self._tracks[track.global_id] = track
                self._next_id += 1
            else:
                track.point = observation.point
                track.last_seen = self._tick
            used_tracks.add((track.global_id, observation.camera_id))
            assignments[(observation.camera_id, observation.local_id)] = track.global_id

        expired = [
            global_id
            for global_id, track in self._tracks.items()
            if self._tick - track.last_seen > self.max_missed_updates
        ]
        for global_id in expired:
            del self._tracks[global_id]
        return assignments

    def _closest_track(
        self,
        observation: AssociationObservation,
        used_tracks: set[tuple[int, str]],
    ) -> _GlobalTrack | None:
        candidates = [
            track
            for track in self._tracks.values()
            if (track.global_id, observation.camera_id) not in used_tracks
            and track.class_id == observation.class_id
        ]
        close_candidates = [
            track
            for track in candidates
            if math.dist(track.point, observation.point) <= self.max_distance
        ]
        return min(
            close_candidates,
            key=lambda track: math.dist(track.point, observation.point),
            default=None,
        )
