"""Associate gate plates with saved native tracks; never run a tracking model."""
from bisect import bisect_right
from functools import lru_cache
import json
from pathlib import Path

from native_project import open_native_cache
from .store import ReplayError, read_gate_log, signature
from .parking_state import ParkingTimeline, parked_zone
from .scenario import read_parking_scenario, scenario_timeline
from tracking.parking_state import plate_key, vehicle_fingerprint


def build_timeline(frames, gate_log, layout):
    """Build compact changes once, including stops before a seek destination."""
    events = {}
    for event in gate_log.get("events", []):
        if event.get("type") in ("IN", "OUT") and plate_key(event.get("plate")):
            events.setdefault(event["frame"], []).append(event)
    histories, bindings, states = {}, {}, {}
    default_camera = (gate_log.get("gate") or {}).get("camera_id")
    for frame in frames:
        n = frame["frame_index"]
        new_entries = set()
        for event in events.get(n, []):
            plate = plate_key(event["plate"])
            camera = event.get("camera_id") or default_camera
            states[plate] = {"status": "MOVING" if event["type"] == "IN" else "EXITED",
                             "current_zone_id": None, "map_position": None, "camera_id": camera,
                             "replay_global_id": None, "last_seen_at": None}
            bindings.pop(plate, None)
            if event["type"] == "IN":
                new_entries.add(plate)
                # Gate track_id is a camera-local ID, never a Global ID.
                local_id = event.get("track_id")
                detection = next((d for d in frame.get("cameras", {}).get(camera, [])
                                  if local_id is not None and d.get("local_id") == local_id), None)
                if detection:
                    bindings[plate] = [camera, local_id, detection.get("global_id")]
        for plate, binding in bindings.items():
            camera, local_id, global_id = binding
            observations = [p for p in frame.get("bev", [])
                            if (global_id is not None and p.get("global_id") == global_id)
                            or (global_id is None and p.get("camera_id") == camera and p.get("local_id") == local_id)]
            observations = [p for p in observations if p.get("state") in ("ACTIVE", "STOPPED", "PARKED")]
            if observations:
                point = max(observations, key=lambda p: p.get("confidence") or 0)
                if global_id is None and point.get("global_id") is not None:
                    binding[2] = point["global_id"]
                parked = point["state"] == "PARKED"
                states[plate].update(status="PARKED" if parked else "MOVING",
                                     current_zone_id=parked_zone(point, layout) if parked else None,
                                     camera_id=point.get("camera_id"), replay_global_id=binding[2])
            elif plate not in new_entries and states[plate]["status"] != "PARKED":
                # Missing observations do not prove parking or departure.
                states[plate].update(status="UNKNOWN", current_zone_id=None, map_position=None)
        for plate, state in states.items():
            if plate not in bindings and plate not in new_entries and state["status"] == "MOVING":
                state.update(status="UNKNOWN", current_zone_id=None)
            history = histories.setdefault(plate, [])
            if not history or history[-1][1] != state:
                history.append((n, dict(state)))
    return {plate: (tuple(n for n, _ in rows), tuple(state for _, state in rows))
            for plate, rows in histories.items()}


@lru_cache(maxsize=2)
def _timeline(path, size, mtime_ns, offsets, gate_json, map_json):
    # Use the external project's indexed reader; changes invalidate this cache.
    gate_log, layout = json.loads(gate_json), json.loads(map_json)
    parking = ParkingTimeline(layout)
    with open_native_cache(Path(path), offsets) as source:
        def frames():
            for n in range(len(offsets)):
                frame = source.read_frame(n)
                parking.update(frame)
                yield frame
        histories = build_timeline(frames(), gate_log, layout)
    return histories, parking


def replay_snapshot(store, frame_index, vehicles):
    gate_log, warning = read_gate_log(store.project, store.title, store.manifest["fps"], store.manifest["frame_count"])
    if warning:
        raise ReplayError(warning)
    scenario = read_parking_scenario(store)
    if scenario is not None:
        histories, parking = scenario_timeline(json.dumps(gate_log, sort_keys=True),
                                               json.dumps(scenario, sort_keys=True),
                                               json.dumps(store.manifest["map"], sort_keys=True))
    else:
        stamp = signature(store.frames_path)
        histories, parking = _timeline(str(store.frames_path), **stamp, offsets=tuple(store.offsets),
                              gate_json=json.dumps(gate_log, sort_keys=True),
                              map_json=json.dumps(store.manifest["map"], sort_keys=True))
    updates = {}
    for vehicle in vehicles:
        history = histories.get(plate_key(vehicle["plate_number"]))
        if not history:
            continue
        times, states = history
        index = bisect_right(times, frame_index) - 1
        if index >= 0:
            updates[vehicle["id"]] = {**states[index], "plate_number": vehicle["plate_number"],
                                      "parking_type": "UNKNOWN" if states[index]["status"] == "PARKED" else None,
                                      "parking_space_id": None,
                                      "replay_video": store.title, "replay_frame": frame_index}
    return updates, parking.at(frame_index)


def vehicle_snapshot(store, frame_index, vehicles):
    return replay_snapshot(store, frame_index, vehicles)[0]


def apply_snapshot(vehicles, snapshot):
    updates = snapshot.get("vehicles", {})
    bases = snapshot.get("base_states", {})
    return [{**vehicle, **updates[vehicle["id"]]}
            if vehicle["id"] in updates and bases.get(vehicle["id"]) == vehicle_fingerprint(vehicle)
            and plate_key(updates[vehicle["id"]].get("plate_number")) == plate_key(vehicle["plate_number"])
            else vehicle for vehicle in vehicles]
