"""Plate-independent changes to a video's initial zone parking counts."""
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


def track_key(point):
    if point.get("global_id") is not None:
        return ("global", point["global_id"])
    if point.get("camera_id") is not None and point.get("local_id") is not None:
        return ("local", point["camera_id"], point["local_id"])
    return None


class ParkingTimeline:
    """Store absolute deltas at changes, so seeks and retries are idempotent."""
    def __init__(self, layout, gate_log):
        self.layout = layout
        self.tracks, self.aliases = {}, {}
        self.deltas = defaultdict(int)
        self.events = defaultdict(list)
        self.default_camera = (gate_log.get("gate") or {}).get("camera_id")
        for event in gate_log.get("events", []):
            if event.get("type") in ("IN", "OUT"):
                self.events[event["frame"]].append(event)
        self.times, self.values = [], []

    def release(self, state):
        if state["zone"] is not None:
            self.deltas[state["zone"]] -= 1
            state["zone"] = None

    def update(self, frame):
        before = dict(self.deltas)
        # Camera-local IDs are aliases, never interchangeable with Global IDs.
        for camera, detections in frame.get("cameras", {}).items():
            for detection in detections:
                key = track_key({**detection, "camera_id": camera})
                if key is not None and detection.get("local_id") is not None:
                    self.aliases[(camera, detection["local_id"])] = key
        observations = {}
        for point in frame.get("bev", []):
            key = track_key(point)
            if key is None or point.get("state") not in ("ACTIVE", "STOPPED", "PARKED"):
                continue
            if point.get("local_id") is not None:
                self.aliases[(point.get("camera_id"), point["local_id"])] = key
            if key not in observations or (point.get("confidence") or 0) > (observations[key].get("confidence") or 0):
                observations[key] = point
        exiting = set()
        for event in self.events.get(frame["frame_index"], []):
            alias = (event.get("camera_id") or self.default_camera, event.get("track_id"))
            key = self.aliases.get(alias)
            if key is None:
                continue  # No known origin: do not subtract an arbitrary zone.
            state = self.tracks.setdefault(key, {"zone": None, "moving": False})
            if event["type"] == "OUT":
                self.release(state)
                state["exited"] = True
                exiting.add(key)
            else:
                state["moving"] = True
                state["exited"] = False
        for key, point in observations.items():
            if key in exiting:
                continue
            state = self.tracks.setdefault(key, {"zone": None, "moving": False})
            if state.get("exited"):
                continue  # A lingering cached observation cannot undo gate OUT.
            if point["state"] == "ACTIVE":
                self.release(state)
                state["moving"] = True
            elif point["state"] == "PARKED" and state["zone"] is None:
                zone = parked_zone(point, self.layout)
                if zone is not None:
                    # First seen parked is already included in the initial JSON.
                    # Only an observed arrival/movement followed by parking adds 1.
                    if state["moving"]:
                        self.deltas[zone] += 1
                    state["zone"] = zone
        # STOPPED, missing detections and coordinate jitter do not prove departure.
        current = {zone: value for zone, value in self.deltas.items() if value}
        if current != {zone: value for zone, value in before.items() if value}:
            self.times.append(frame["frame_index"])
            self.values.append(current)

    def at(self, frame_index):
        index = bisect_right(self.times, frame_index) - 1
        return dict(self.values[index]) if index >= 0 else {}
