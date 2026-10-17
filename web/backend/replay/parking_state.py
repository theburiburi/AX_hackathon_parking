"""Count native parking and estimates once per Global ID."""
from bisect import bisect_right
from collections import defaultdict
import math


def parked_zone(point, layout):
    x, y = point.get("x"), point.get("y")
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in (x, y)):
        return None
    if not (0 <= x < layout["width"] and 0 <= y < layout["height"]):
        return None
    return next((z["id"] for z in layout["zones"]
                 if z["bndbox"]["xmin"] <= x <= z["bndbox"]["xmax"]
                 and z["bndbox"]["ymin"] <= y <= z["bndbox"]["ymax"]), None)


class ParkingTimeline:
    """Store absolute deltas at changes, so seeks and retries are idempotent."""
    def __init__(self, layout, *, identity_field="global_id", initial_assignments=None):
        self.zones = {zone["id"] for zone in layout["zones"]}
        self.identity_field = identity_field
        self.assigned, self.seen = dict(initial_assignments or {}), set()
        self.deltas = defaultdict(int)
        self.times, self.values = [], []

    def update(self, frame):
        before = dict(self.deltas)
        # Replay native events once per GID. A LOST estimate followed by PARKED
        # retains its count; a different confirmed zone transfers that same car.
        for event in frame.get("parking", {}).get("events", []):
            kind, gid, zone = event.get("type"), event.get(self.identity_field), event.get("zone")
            n = event.get("frame")
            if (kind not in ("PARKED", "LOST", "LEFT") or type(gid) is not int or gid <= 0
                    or type(n) is not int or not 0 <= n <= frame["frame_index"]
                    or not isinstance(zone, str) or zone not in self.zones):
                continue
            key = (n, kind, gid, zone)
            if key in self.seen:
                continue
            self.seen.add(key)
            previous = self.assigned.get(gid)
            if kind in ("PARKED", "LOST") and previous != zone:
                if previous is not None:
                    self.deltas[previous] -= 1
                self.assigned[gid] = zone
                self.deltas[zone] += 1
            elif kind == "LEFT" and previous == zone:
                self.deltas[zone] -= 1
                del self.assigned[gid]
        current = {zone: value for zone, value in self.deltas.items() if value}
        if current != {zone: value for zone, value in before.items() if value}:
            self.times.append(frame["frame_index"])
            self.values.append(current)

    def at(self, frame_index):
        index = bisect_right(self.times, frame_index) - 1
        return dict(self.values[index]) if index >= 0 else {}
