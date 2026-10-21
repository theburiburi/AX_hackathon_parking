from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml


ROOT = Path(__file__).resolve().parents[1]

GATE_CONFIG_PATH = ROOT / "config" / "gate.yaml"


"""
차단기 입출차 감지 (config/gate.yaml).

박스 넓이 중 차량 bbox와 겹친 비율이 min_overlap_ratio보다 크고,
겹침 비율이 min_overlap_increase 만큼 커지면서(박스 안으로 들어오는 중)
박스의 direction 쪽으로 움직이면 입차(IN) / 출차(OUT)로 확정한다.
외길이라 속도는 보지 않는다. 같은 track은 박스마다 한 번만 기록한다.
"""


def load_gate_config() -> dict:

    with GATE_CONFIG_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:

        return yaml.safe_load(file) or {}


@dataclass
class Zone:
    """
    네모 감지 박스 (x1, y1, x2, y2). 차량 bbox와 같은 형식.
    """

    type: str
    label: str
    box: tuple[float, float, float, float]
    direction: np.ndarray


def load_zones(
    config: dict,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
) -> list[Zone]:
    """
    config의 박스(reference_size 칸 기준)를 실제 칸 크기로 늘려 읽는다.
    """

    zones = []

    for item in config.get("zones", []):

        # 가로 / 세로 배율이 다르면 방향도 같이 바뀐다.
        direction = np.asarray(
            item["direction"],
            dtype=np.float64,
        ) * [scale_x, scale_y]

        norm = float(np.linalg.norm(direction))

        if norm <= 0:
            raise ValueError(
                f"zone {item['type']}: direction must not be zero"
            )

        bx1, by1, bx2, by2 = (float(v) for v in item["box"])

        bx1, bx2 = bx1 * scale_x, bx2 * scale_x
        by1, by2 = by1 * scale_y, by2 * scale_y

        if bx2 <= bx1 or by2 <= by1:
            raise ValueError(
                f"zone {item['type']}: box must be [x1, y1, x2, y2] with x1 < x2, y1 < y2"
            )

        zones.append(
            Zone(
                type=str(item["type"]),
                label=str(item.get("label", item["type"])),
                box=(bx1, by1, bx2, by2),
                direction=direction / norm,
            )
        )

    if not zones:
        raise ValueError(
            f"No zones in {GATE_CONFIG_PATH}"
        )

    return zones


def overlap_ratio(
    bbox: tuple[float, float, float, float],
    zone: Zone,
) -> float:
    """
    감지 박스 중 차량 bbox와 겹친 넓이의 비율 (0 ~ 1).
    박스 넓이 기준이라 차량 bbox 크기와 관계없이 같은 기준으로 판정한다.
    """

    x1, y1, x2, y2 = bbox
    bx1, by1, bx2, by2 = zone.box

    box_area = (bx2 - bx1) * (by2 - by1)

    w = max(0.0, min(x2, bx2) - max(x1, bx1))
    h = max(0.0, min(y2, by2) - max(y1, by1))

    return w * h / box_area


@dataclass
class GateEvent:
    """
    확정된 입출차 1건.
    """

    zone: Zone
    # 처음 박스와 겹친 프레임 (기록 시각)
    frame: int
    track_id: int
    class_name: str
    # 확정 시점의 차량 위치(bbox 바닥 중앙)와 bbox
    position: tuple[float, float]
    bbox: tuple[float, float, float, float]
    # 겹치는 동안 가장 작았던 겹침 비율 -> 확정 시점 비율
    start_ratio: float
    ratio: float


class GateDetector:
    """
    프레임마다 추적 결과를 넣으면 그 프레임에 확정된 입출차를 돌려준다.
    """

    def __init__(
        self,
        zones: list[Zone],
        min_overlap_ratio: float = 0.3,
        min_overlap_increase: float = 0.2,
        min_frames: int = 3,
    ):
        self.zones = zones
        self.min_overlap_ratio = float(min_overlap_ratio)
        self.min_overlap_increase = float(min_overlap_increase)
        self.min_frames = int(min_frames)

        # (track_id, zone index) -> 박스와 연속으로 겹친 동안의 상태
        #   count     : 연속으로 겹친 프레임 수
        #   since     : 처음 겹친 프레임
        #   min_ratio : 그동안 가장 작았던 겹침 비율
        #   start     : 처음 겹쳤을 때 차량 위치 (bbox 바닥 중앙)
        self.inside: dict[tuple[int, int], dict] = {}

        # 이미 기록한 (track_id, zone index)
        self.fired: set[tuple[int, int]] = set()

    @classmethod
    def from_config(
        cls,
        config: dict,
        cell_rect: tuple[int, int, int, int],
    ) -> GateDetector:
        """
        config/gate.yaml 설정으로 만든다.
        박스는 reference_size 칸 기준이므로 cell_rect 칸 크기 비율만큼 늘린다.
        """

        x1, y1, x2, y2 = cell_rect

        reference_width, reference_height = (
            float(value)
            for value in config.get("reference_size", [x2 - x1, y2 - y1])
        )

        detector = cls(
            load_zones(
                config,
                (x2 - x1) / reference_width,
                (y2 - y1) / reference_height,
            ),
            min_overlap_ratio=config.get("min_overlap_ratio", 0.1),
            min_overlap_increase=config.get("min_overlap_increase", 0.2),
            min_frames=config.get("min_frames_in_zone", 3),
        )

        detector.scale = (
            (x2 - x1) / reference_width,
            (y2 - y1) / reference_height,
        )

        detector.reference_size = (
            reference_width,
            reference_height,
        )

        return detector

    def update(
        self,
        frame: int,
        tracked: list,
    ) -> list[GateEvent]:
        """
        tracked: 이 프레임의 TrackedDetection 목록 (Local Tracker 결과).
        """

        events = []

        for item in tracked:

            track = item.track
            track_id = int(track.local_id)

            x = float(track.ground_x)
            y = float(track.ground_y)

            bbox = (
                float(track.x1),
                float(track.y1),
                float(track.x2),
                float(track.y2),
            )

            for zone_index, zone in enumerate(self.zones):

                key = (track_id, zone_index)

                if key in self.fired:
                    continue

                ratio = overlap_ratio(bbox, zone)

                if ratio <= self.min_overlap_ratio:
                    self.inside.pop(key, None)
                    continue

                state = self.inside.setdefault(
                    key,
                    {
                        "count": 0,
                        "since": frame,
                        "min_ratio": ratio,
                        "start": (x, y),
                    },
                )

                state["count"] += 1
                state["min_ratio"] = min(state["min_ratio"], ratio)

                if state["count"] < self.min_frames:
                    continue

                # 박스 안으로 들어오는 중이어야 한다.
                # 서 있는 차량은 bbox가 흔들려도 겹침 비율이 거의 그대로다.
                if ratio - state["min_ratio"] < self.min_overlap_increase:
                    continue

                # 들어온 뒤 박스의 진행 방향 쪽으로 움직였어야 한다 (거리 / 속도 무관).
                # 반대 차로를 지나는 큰 bbox도 박스를 점점 덮을 수 있어서 거른다.
                moved = np.array(
                    [x - state["start"][0], y - state["start"][1]]
                )

                if float(np.dot(moved, zone.direction)) <= 0.0:
                    continue

                self.fired.add(key)

                events.append(
                    GateEvent(
                        zone=zone,
                        frame=state["since"],
                        track_id=track_id,
                        class_name=str(track.class_name),
                        position=(x, y),
                        bbox=bbox,
                        start_ratio=state["min_ratio"],
                        ratio=ratio,
                    )
                )

        return events
