"""Read explicit parking scenarios without changing native tracking caches."""
from collections import defaultdict
from functools import lru_cache
import json
import math

from .parking_state import ParkingTimeline
from .store import ReplayError
from tracking.parking_state import plate_key


def read_parking_scenario(store):
    path = store.project / "data/parking_logs/parking_log.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Parking log must be an object")
        if data.get("video") != store.title:
            return None
        fps = data.get("fps")
        if (type(fps) not in (int, float) or not math.isfinite(fps)
                or not math.isclose(fps, store.manifest["fps"], abs_tol=.01)):
            raise ValueError("fps does not match the replay")
        zones = {zone["id"] for zone in store.manifest["map"]["zones"]}
        initial, events = data.get("initial_vehicles", []), data.get("events")
        if not isinstance(initial, list) or not isinstance(events, list):
            raise ValueError("initial_vehicles and events must be arrays")
        identities, plates = {}, {}
        initial_ids = set()
        for row in initial + events:
            if not isinstance(row, dict):
                raise ValueError("Each parking record must be an object")
            vehicle_id, zone, plate = row.get("scenario_vehicle_id"), row.get("zone"), row.get("plate")
            if type(vehicle_id) is not int or vehicle_id <= 0:
                raise ValueError("scenario_vehicle_id must be a positive integer")
            if not isinstance(zone, str) or zone not in zones:
                raise ValueError("Unknown parking zone")
            if not isinstance(plate, str) or not plate_key(plate):
                raise ValueError("plate is required")
            plate = plate_key(plate)
            if identities.setdefault(vehicle_id, plate) != plate or plates.setdefault(plate, vehicle_id) != vehicle_id:
                raise ValueError("Vehicle IDs and plates must have a consistent one-to-one mapping")
        for row in initial:
            if row["scenario_vehicle_id"] in initial_ids:
                raise ValueError("Duplicate initial vehicle")
            initial_ids.add(row["scenario_vehicle_id"])
        for row in events:
            if row.get("type") not in ("PARKED", "LOST", "LEFT"):
                raise ValueError("Parking event type must be PARKED, LOST or LEFT")
            n = row.get("frame")
            if type(n) is not int or not 0 <= n < store.manifest["frame_count"]:
                raise ValueError("Parking frame is outside the replay")
        return data
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ReplayError(f"data/parking_logs/parking_log.json: {exc}") from exc


@lru_cache(maxsize=4)
def scenario_timeline(gate_json, scenario_json, map_json):
    gate, scenario, layout = json.loads(gate_json), json.loads(scenario_json), json.loads(map_json)
    initial = scenario.get("initial_vehicles", [])
    parking = ParkingTimeline(layout, identity_field="scenario_vehicle_id",
                              initial_assignments={row["scenario_vehicle_id"]: row["zone"] for row in initial})
    states, histories = {}, {}

    def apply(row, status, zone):
        plate = plate_key(row.get("plate"))
        if not plate:
            return None
        states[plate] = {"status": status, "current_zone_id": zone, "map_position": None,
                         "camera_id": row.get("camera_id"), "replay_global_id": None,
                         "scenario_vehicle_id": row.get("scenario_vehicle_id"), "last_seen_at": None}
        return plate

    for row in initial:
        plate = apply(row, "PARKED", row["zone"])
        histories[plate] = [(0, dict(states[plate]))]

    by_frame = defaultdict(list)
    for row in scenario["events"]:
        by_frame[row["frame"]].append(row)
    for row in gate.get("events", []):
        if row.get("type") in ("IN", "OUT"):
            by_frame[row["frame"]].append(row)
    priority = {"LEFT": 0, "IN": 1, "PARKED": 2, "LOST": 2, "OUT": 3}
    for n, rows in sorted(by_frame.items()):
        changed = set()
        for row in sorted(rows, key=lambda row: priority[row["type"]]):
            kind = row["type"]
            status = "EXITED" if kind == "OUT" else "PARKED" if kind in ("PARKED", "LOST") else "MOVING"
            plate = apply(row, status, row.get("zone") if status == "PARKED" else None)
            if plate:
                changed.add(plate)
        parking.update({"frame_index": n, "parking": {"events": [
            row for row in sorted(rows, key=lambda row: priority[row["type"]])
            if row["type"] in ("PARKED", "LOST", "LEFT")]}})
        for plate in changed:
            history = histories.setdefault(plate, [])
            if not history or history[-1][1] != states[plate]:
                history.append((n, dict(states[plate])))
    return {plate: (tuple(n for n, _ in rows), tuple(state for _, state in rows))
            for plate, rows in histories.items()}, parking
