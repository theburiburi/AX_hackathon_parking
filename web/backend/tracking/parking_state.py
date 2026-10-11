"""Plate-free parking inventories and vehicle replay identity helpers."""
import hashlib
import json


def plate_key(value):
    return "".join(str(value or "").split())


def vehicle_fingerprint(vehicle):
    return hashlib.sha256(json.dumps(vehicle, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def initial_zone_counts(document, zones):
    """Validate a complete list before returning canonical zone count records."""
    if not isinstance(document, list):
        raise ValueError("Initial parking data must be an array of zone counts.")
    zone_ids = {str(zone["id"]).casefold(): zone["id"] for zone in zones}
    result, seen = [], set()
    for index, row in enumerate(document, 1):
        prefix = f"zones[{index}]"
        if not isinstance(row, dict) or set(row) - {"zone_id", "parked_count", "capacity"}:
            raise ValueError(f"{prefix} supports only zone_id, parked_count and capacity.")
        zone_id = row.get("zone_id")
        if not isinstance(zone_id, str) or zone_id.strip().casefold() not in zone_ids:
            raise ValueError(f"{prefix}.zone_id must be a configured zone.")
        zone_id = zone_ids[zone_id.strip().casefold()]
        if zone_id in seen:
            raise ValueError(f"{prefix}: duplicate zone_id {zone_id}.")
        seen.add(zone_id)
        total = row.get("parked_count")
        if type(total) is not int or total < 0:
            raise ValueError(f"{prefix}.parked_count must be a nonnegative integer.")
        normalized = {"zone_id": zone_id, "parked_count": total}
        if "capacity" in row:
            capacity = row["capacity"]
            if type(capacity) is not int or capacity < 0:
                raise ValueError(f"{prefix}.capacity must be a nonnegative integer.")
            normalized["capacity"] = capacity
        result.append(normalized)
    return result


def manual_zone_deltas(vehicles):
    deltas = {}
    for vehicle in vehicles:
        if "parking_baseline_zone_id" not in vehicle:
            continue  # Untouched vehicles are already included in the initial JSON.
        origin = vehicle["parking_baseline_zone_id"]
        current = vehicle.get("parking_counted_zone_id")
        for zone, delta in ((origin, -1), (current, 1)):
            if zone is not None:
                deltas[zone] = deltas.get(zone, 0) + delta
    return deltas


def occupancy_deltas(vehicles, snapshot):
    manual = manual_zone_deltas(vehicles)
    deltas = snapshot.get("parking_deltas")
    baseline = snapshot.get("parking_base_deltas")
    if all(isinstance(rows, dict) and all(type(value) is int for value in rows.values())
           for rows in (deltas, baseline)):
        # Metadata edits must not reset occupancy. Apply only manual changes
        # since the last explicit replay synchronization, without adding twice.
        return {zone: deltas.get(zone, 0) + manual.get(zone, 0) - baseline.get(zone, 0)
                for zone in deltas.keys() | manual.keys() | baseline.keys()}
    return manual


def zone_occupancy(document, zones, deltas=None):
    inventory = {row["zone_id"]: row for row in initial_zone_counts(document, zones)}
    counts = {}
    for zone in zones:
        row = inventory.get(zone["id"], {})
        initial = row.get("parked_count", 0)
        delta = (deltas or {}).get(zone["id"], 0)
        total = max(0, initial + delta)
        capacity = row.get("capacity", zone.get("capacity"))
        counts[zone["id"]] = {
            "initial_parked_count": initial, "parking_delta": delta,
            "parked_count": total, "capacity": capacity,
            "overflow_count": max(0, total - capacity) if type(capacity) is int and capacity >= 0 else None,
        }
    return counts
