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


def event(kind, n, **changes):
    return {"type": kind, "frame": n, "global_id": 1, "zone": "A", **changes}


class ParkingTimelineTests(SimpleTestCase):
    def timeline(self, frames):
        result = ParkingTimeline(LAYOUT)
        for n, frame in enumerate(frames):
            result.update({"frame_index": n, **frame})
        return result

    def test_parking_events_count_and_cumulative_repeats_do_not_add_twice(self):
        parked, left = event("PARKED", 1), event("LEFT", 4)
        result = self.timeline([
            {"parking": {"events": []}},
            {"parking": {"events": [parked, parked], "counts": {"A": 99}}},
            {"parking": {"events": [parked]}},
            {"bev": [point("ACTIVE")]},
            {"parking": {"events": [parked, left]}},
            {"parking": {"events": [parked, left]}},
        ])
        for n, expected in ((0, {}), (1, {"A": 1}), (2, {"A": 1}),
                            (3, {"A": 1}), (4, {}), (5, {}), (1, {"A": 1})):
            self.assertEqual(result.at(n), expected)

    def test_lost_estimates_count_and_departures_release_them(self):
        lost, left, parked = event("LOST", 0), event("LEFT", 1), event("PARKED", 2)
        result = self.timeline([
            {"parking": {"events": [lost], "counts": {"A": 1}}},
            {"parking": {"events": [lost, left]}},
            {"parking": {"events": [lost, left, parked]}},
        ])
        self.assertEqual(result.at(0), {"A": 1})
        self.assertEqual(result.at(1), {})
        self.assertEqual(result.at(2), {"A": 1})

    def test_lost_then_confirmed_in_same_zone_keeps_one_vehicle(self):
        lost, parked = event("LOST", 0), event("PARKED", 1)
        result = self.timeline([
            {"parking": {"events": [lost]}},
            {"parking": {"events": [lost, parked]}},
            {"parking": {"events": [lost, parked, parked]}},
            {"parking": {"events": [lost, parked, event("LEFT", 3)]}},
        ])
        for n in (0, 1, 2):
            self.assertEqual(result.at(n), {"A": 1})
        self.assertEqual(result.at(3), {})
        self.assertEqual(result.at(0), {"A": 1})

    def test_lost_then_confirmed_in_another_zone_transfers_without_extra_vehicle(self):
        lost = event("LOST", 0)
        for transfer in ([event("PARKED", 1, zone="B")],
                         [event("LEFT", 1), event("PARKED", 1, zone="B")]):
            with self.subTest(transfer=transfer):
                result = self.timeline([
                    {"parking": {"events": [lost]}},
                    {"parking": {"events": [lost, *transfer]}},
                    {"parking": {"events": [lost, *transfer]}},
                ])
                self.assertEqual(result.at(0), {"A": 1})
                self.assertEqual(result.at(1), {"B": 1})
                self.assertEqual(result.at(2), {"B": 1})

    def test_bev_states_without_native_events_cannot_invent_parking(self):
        result = self.timeline([
            {"bev": [point("ACTIVE")]},
            {"bev": [point("PARKED"), point("PARKED", global_id=None)]},
            {"bev": [point("STOPPED")], "parking": {"counts": {"A": 50}}},
        ])
        self.assertEqual(result.at(2), {})

    def test_different_global_ids_count_separately(self):
        result = self.timeline([{"parking": {"events": [
            event("PARKED", 0), event("PARKED", 0, global_id=2)]}}])
        self.assertEqual(result.at(0), {"A": 2})

    def test_same_frame_departure_and_new_parking_transfer_the_vehicle(self):
        parked = event("PARKED", 0)
        transfer = [parked, event("LEFT", 1), event("PARKED", 1, zone="B")]
        result = self.timeline([
            {"parking": {"events": [parked]}},
            {"parking": {"events": transfer}},
            {"parking": {"events": transfer}},
        ])
        self.assertEqual(result.at(0), {"A": 1})
        self.assertEqual(result.at(1), {"B": 1})
        self.assertEqual(result.at(2), {"B": 1})

    def test_left_only_releases_the_confirmed_vehicle_in_the_matching_zone(self):
        parked = event("PARKED", 0)
        result = self.timeline([
            {"parking": {"events": [parked]}},
            {"parking": {"events": [parked, event("LEFT", 1, zone="B"),
                                     event("LEFT", 1, global_id=2)]}},
        ])
        self.assertEqual(result.at(1), {"A": 1})

    def test_invalid_events_never_invent_counts(self):
        changes = [{"global_id": None}, {"global_id": True}, {"global_id": "1"},
                   {"global_id": 0}, {"zone": "UNKNOWN"}, {"zone": None},
                   {"frame": -1}, {"frame": True}, {"frame": "0"}, {"type": "IN"}]
        for change in changes:
            with self.subTest(change=change):
                result = self.timeline([{"parking": {"events": [event("PARKED", 0, **change)]}}])
                self.assertEqual(result.at(0), {})

    def test_future_events_wait_for_their_video_frame(self):
        parked = event("PARKED", 2)
        result = self.timeline([{"parking": {"events": [parked]}} for _ in range(3)])
        self.assertEqual(result.at(0), {})
        self.assertEqual(result.at(1), {})
        self.assertEqual(result.at(2), {"A": 1})

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
