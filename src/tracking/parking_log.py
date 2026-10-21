from __future__ import annotations

import math
import random
from dataclasses import dataclass


"""
구역별 주차 대수와 주차 기록.

GID 차량만 센다 (입구에서 들어온 차량 = 한 대에 하나의 GID).

- PARKED : 구역 안에서 PARKED 상태가 되면 그 구역 +1
- LOST   : PARKED가 아니어도 lost_after_sec 동안 어디서도 보이지 않으면
           마지막 위치에서 가장 가까운 구역 +1
           (마지막으로 입구 카메라에서만 보인 차량은 나간 것으로 보고 세지 않는다)
- LEFT   : 센 차량이 다시 ACTIVE로 구역 밖으로 움직이면 그 구역 -1

같은 차량은 한 구역에만 한 번 센다.
"""


# 자가용 번호판 한글 (임의 번호 생성용)
_PLATE_LETTERS = (
    "가나다라마"
    "거너더러머버서어저"
    "고노도로모보소오조"
    "구누두루무부수우주"
)


def vehicle_plate(global_id: int) -> str:
    """
    GID별 임의 차량 번호 (예: "123가 4567").
    GID를 시드로 써서 재생바 이동 / 서버 재시작 후에도 같은 번호가 나온다.
    """
    rng = random.Random(f"plate-{int(global_id)}")
    return (
        f"{rng.randint(10, 699)}"
        f"{rng.choice(_PLATE_LETTERS)} "
        f"{rng.randint(1000, 9999)}"
    )


@dataclass
class _LastSeen:
    timestamp: float
    frame: int
    x: float
    y: float
    cameras: frozenset[str]


class ParkingLog:

    def __init__(
        self,
        zones: list[dict],
        lost_after_sec: float = 10.0,
        leave_margin_px: float = 20.0,
        exit_camera_ids: tuple[str, ...] = ("cam01",),
    ):
        self.zones = [
            {
                "id": str(zone["id"]),
                "capacity": int(zone.get("capacity", 0)),
                "box": (
                    float(zone["bndbox"]["xmin"]),
                    float(zone["bndbox"]["ymin"]),
                    float(zone["bndbox"]["xmax"]),
                    float(zone["bndbox"]["ymax"]),
                ),
            }
            for zone in zones
        ]
        self.lost_after_sec = float(lost_after_sec)
        self.leave_margin_px = float(leave_margin_px)
        self.exit_camera_ids = frozenset(exit_camera_ids)

        self.counts = {zone["id"]: 0 for zone in self.zones}
        self.assigned: dict[int, str] = {}
        self.last_seen: dict[int, _LastSeen] = {}
        self.events: list[dict] = []

    # -----------------------------------------------------
    # Geometry
    # -----------------------------------------------------

    def _zone_at(self, x: float, y: float, margin: float = 0.0) -> str | None:
        for zone in self.zones:
            x1, y1, x2, y2 = zone["box"]
            if x1 - margin <= x <= x2 + margin and y1 - margin <= y <= y2 + margin:
                return zone["id"]
        return None

    def _nearest_zone(self, x: float, y: float) -> tuple[str, float]:
        best = None
        for zone in self.zones:
            x1, y1, x2, y2 = zone["box"]
            distance = math.hypot(max(x1 - x, 0.0, x - x2), max(y1 - y, 0.0, y - y2))
            if best is None or distance < best[1]:
                best = (zone["id"], distance)
        return best

    def _capacity(self, zone_id: str) -> int:
        return next(zone["capacity"] for zone in self.zones if zone["id"] == zone_id)

    # -----------------------------------------------------
    # Events
    # -----------------------------------------------------

    def _event(self, kind: str, frame: int, timestamp: float, global_id: int,
               zone_id: str, x: float, y: float, distance: float = 0.0) -> None:
        self.events.append({
            "type": kind,
            "frame": int(frame),
            "time": round(float(timestamp), 3),
            "global_id": int(global_id),
            "plate": vehicle_plate(global_id),
            "zone": zone_id,
            "count": self.counts[zone_id],
            "capacity": self._capacity(zone_id),
            "x": round(float(x), 1),
            "y": round(float(y), 1),
            "distance": round(float(distance), 1),
        })

    def _assign(self, kind: str, global_id: int, zone_id: str, frame: int,
                timestamp: float, x: float, y: float, distance: float = 0.0) -> None:
        self.assigned[global_id] = zone_id
        self.counts[zone_id] += 1
        self._event(kind, frame, timestamp, global_id, zone_id, x, y, distance)

    def _release(self, global_id: int, frame: int, timestamp: float,
                 x: float, y: float) -> None:
        zone_id = self.assigned.pop(global_id)
        self.counts[zone_id] -= 1
        self._event("LEFT", frame, timestamp, global_id, zone_id, x, y)

    # -----------------------------------------------------
    # Update
    # -----------------------------------------------------

    def update(self, frame: int, timestamp: float, items: list[dict]) -> list[dict]:
        """
        items: 이 프레임의 BEV 항목 (global_id, state, x, y).
        반환: 이 프레임에서 새로 생긴 이벤트.
        """
        first_event = len(self.events)

        observed: dict[int, list[dict]] = {}
        for item in items:
            if item.get("global_id") is not None:
                observed.setdefault(int(item["global_id"]), []).append(item)

        for global_id, group in observed.items():
            x = sum(item["x"] for item in group) / len(group)
            y = sum(item["y"] for item in group) / len(group)
            states = {item["state"] for item in group}
            self.last_seen[global_id] = _LastSeen(
                timestamp, frame, x, y,
                frozenset(item["camera_id"] for item in group))

            zone_id = self.assigned.get(global_id)

            if zone_id is not None:
                # 센 차량이 다시 움직여 구역 밖으로 나가면 뺀다.
                if ("ACTIVE" in states
                        and self._zone_at(x, y, self.leave_margin_px) != zone_id):
                    self._release(global_id, frame, timestamp, x, y)
                # 추정(LOST)했던 차량이 다른 구역에서 주차가 확인되면 옮겨 센다.
                elif states == {"PARKED"}:
                    parked_zone = self._zone_at(x, y)
                    if parked_zone is not None and parked_zone != zone_id:
                        self._release(global_id, frame, timestamp, x, y)
                        self._assign("PARKED", global_id, parked_zone,
                                     frame, timestamp, x, y)
                continue

            if states == {"PARKED"}:
                zone_id = self._zone_at(x, y)
                if zone_id is not None:
                    self._assign("PARKED", global_id, zone_id, frame, timestamp, x, y)

        # 오래 보이지 않는 차량은 마지막 위치에서 가장 가까운 구역에 센다.
        for global_id, seen in self.last_seen.items():
            if (global_id in observed or global_id in self.assigned
                    or timestamp - seen.timestamp < self.lost_after_sec
                    or seen.cameras <= self.exit_camera_ids):
                continue
            zone_id, distance = self._nearest_zone(seen.x, seen.y)
            self._assign("LOST", global_id, zone_id, frame, timestamp,
                         seen.x, seen.y, distance)

        return self.events[first_event:]

    def snapshot(self) -> dict:
        return {
            "counts": dict(self.counts),
            "events": list(self.events),
        }
