from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase
from replay.parking_state import ParkingTimeline
from . import json_store
from .parking_state import zone_occupancy


LAYOUT = {"map_id": "test", "width": 100, "height": 100, "zones": [
    {"id": "A", "capacity": 14, "label": [20, 20], "bndbox": {"xmin": 0, "ymin": 0, "xmax": 30, "ymax": 30}},
    {"id": "B", "capacity": 4, "label": [70, 20], "bndbox": {"xmin": 50, "ymin": 0, "xmax": 90, "ymax": 30}}]}


def point(state, **changes):
    return {"global_id": 1, "local_id": 10, "camera_id": "cam01", "state": state,
            "x": 20, "y": 20, "confidence": .9, **changes}


class ParkingTimelineTests(SimpleTestCase):
    def timeline(self, observations, gate=None):
        result = ParkingTimeline(LAYOUT, gate or {})
        for n, rows in enumerate(observations):
            cameras = {}
            for row in rows:
                cameras.setdefault(row["camera_id"], []).append(row)
            result.update({"frame_index": n, "bev": rows, "cameras": cameras})
        return result

    def test_only_completed_parking_increments_and_camera_duplicates_count_once(self):
        parked = point("PARKED")
        rows = [[point("ACTIVE")], [point("STOPPED")], [parked, {**parked, "camera_id": "cam02", "local_id": 22}],
                [parked], [], [point("STOPPED")], [point("ACTIVE")]]
        result = self.timeline(rows)
        for frame, expected in ((0, {}), (1, {}), (2, {"A": 1}), (3, {"A": 1}), (4, {"A": 1}), (5, {"A": 1}), (6, {})):
            self.assertEqual(result.at(frame), expected)
        self.assertEqual(result.at(1), {})  # A backward seek restores the earlier total.

    def test_initial_parked_vehicle_is_not_added_and_departure_reduces_baseline(self):
        result = self.timeline([[point("PARKED")], [], [point("ACTIVE")], [point("PARKED", x=70)]])
        self.assertEqual(result.at(0), {})
        self.assertEqual(result.at(2), {"A": -1})
        self.assertEqual(result.at(3), {"A": -1, "B": 1})

    def test_moving_between_zones_transfers_count_and_parked_jitter_does_not(self):
        result = self.timeline([[point("ACTIVE")], [point("PARKED")], [point("PARKED", x=70)],
                                [point("ACTIVE")], [point("PARKED", x=70)]])
        self.assertEqual(result.at(2), {"A": 1})
        self.assertEqual(result.at(3), {})
        self.assertEqual(result.at(4), {"B": 1})

    def test_invalid_or_out_of_zone_coordinates_never_invent_parking(self):
        for x in (float("nan"), float("inf"), -1, 100, 40, "20", True):
            result = self.timeline([[point("ACTIVE")], [point("PARKED", x=x)]])
            with self.subTest(x=x):
                self.assertEqual(result.at(1), {})

    def test_different_global_ids_count_separately_even_with_same_local_id(self):
        a, b = point("ACTIVE"), point("ACTIVE", global_id=2, camera_id="cam02")
        result = self.timeline([[a, b], [{**a, "state": "PARKED"}, {**b, "state": "PARKED"}]])
        self.assertEqual(result.at(1), {"A": 2})

    def test_gate_entry_then_parked_counts_without_active_bev_or_plate(self):
        gate = {"gate": {"camera_id": "cam01"}, "events": [
            {"frame": 0, "type": "IN", "track_id": 10}, {"frame": 2, "type": "OUT", "track_id": 10}]}
        result = self.timeline([[point("STOPPED")], [point("PARKED")], []], gate)
        self.assertEqual(result.at(1), {"A": 1})
        self.assertEqual(result.at(2), {})

    def test_unknown_gate_exit_does_not_subtract_arbitrary_zone(self):
        gate = {"gate": {"camera_id": "cam02"}, "events": [{"frame": 1, "type": "OUT", "track_id": 10}]}
        result = self.timeline([[point("PARKED")], []], gate)
        self.assertEqual(result.at(1), {})

    def test_stale_parked_observations_cannot_undo_gate_exit(self):
        gate = {"gate": {"camera_id": "cam01"}, "events": [
            {"frame": 2, "type": "OUT", "track_id": 10}, {"frame": 4, "type": "IN", "track_id": 10}]}
        result = self.timeline([[point("ACTIVE")], [point("PARKED")], [point("PARKED")],
                                [point("PARKED")], [point("ACTIVE")], [point("PARKED")]], gate)
        self.assertEqual(result.at(1), {"A": 1})
        self.assertEqual(result.at(2), {})
        self.assertEqual(result.at(3), {})
        self.assertEqual(result.at(5), {"A": 1})

    def test_capacity_and_overflow_recompute_when_counts_or_capacity_change(self):
        initial = [{"zone_id": "A", "parked_count": 20}]
        counts = zone_occupancy(initial, LAYOUT["zones"], {"A": 1})["A"]
        self.assertEqual((counts["parked_count"], counts["overflow_count"]), (21, 7))
        zones = deepcopy(LAYOUT["zones"])
        zones[0]["capacity"] = 30
        self.assertEqual(zone_occupancy(initial, zones, {"A": 1})["A"]["overflow_count"], 0)
        self.assertEqual(zone_occupancy([], zones, {"A": -1})["A"]["parked_count"], 0)


class ManualParkingEventTests(SimpleTestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for target, value in (("tracking.json_store.DATA_DIR", Path(directory.name)),
                              ("tracking.views.current_map_layout", LAYOUT),
                              ("tracking.views.current_user", {"role": "ADMIN"})):
            mocked = patch(target, return_value=value) if not target.endswith("DATA_DIR") else patch(target, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        json_store.write("parking_zones", LAYOUT["zones"])
        json_store.write("initial_parking", [{"zone_id": "A", "parked_count": 20}])
        json_store.write("tracking_logs", [])
        json_store.write("vehicles", [{"id": "V1", "plate_number": "111가1111", "status": "MOVING", "current_zone_id": None}])

    def send(self, status, zone="A"):
        response = self.client.post("/api/tracking-events/", {"plate_number": "111가1111", "camera_id": "cam01", "zone_id": zone, "status": status}, content_type="application/json")
        self.assertEqual(response.status_code, 201, response.content)

    def total(self, zone="A"):
        response = self.client.get("/api/parking-zones/")
        self.assertEqual(response.status_code, 200, response.content)
        return next(row for row in response.json() if row["id"] == zone)["parked_count"]

    def test_new_parking_repeated_updates_departure_and_zone_change(self):
        self.send("MOVING")
        self.assertEqual(self.total(), 20)
        self.send("PARKED")
        self.send("PARKED")
        self.assertEqual(self.total(), 21)
        self.send("UNKNOWN")
        self.assertEqual(self.total(), 21)
        self.send("MOVING")
        self.assertEqual(self.total(), 20)
        self.send("PARKED", "B")
        self.assertEqual(self.total("B"), 1)
        self.send("EXITED", "B")
        self.assertEqual(self.total("B"), 0)

    def test_existing_parked_vehicle_is_already_in_baseline(self):
        vehicles = json_store.read("vehicles")
        vehicles[0].update(status="PARKED", current_zone_id="A")
        json_store.write("vehicles", vehicles)
        self.send("PARKED")
        self.assertEqual(self.total(), 20)
        self.send("MOVING")
        self.assertEqual(self.total(), 19)
        self.send("PARKED", "B")
        self.assertEqual(self.total(), 19)
        self.assertEqual(self.total("B"), 1)
