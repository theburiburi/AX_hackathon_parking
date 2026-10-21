from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from replay.scenario import read_parking_scenario, scenario_timeline
from replay.store import ReplayError
from tracking.parking_state import vehicle_fingerprint
from . import json_store


class ParkingScenarioTests(SimpleTestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.addCleanup(scenario_timeline.cache_clear)
        self.root = Path(temporary.name)
        self.layout = {"width": 100, "height": 100, "zones": [
            {"id": "A", "capacity": 3, "label": [20, 20], "bndbox": {"xmin": 0, "ymin": 0, "xmax": 30, "ymax": 30}},
            {"id": "B", "capacity": 5, "label": [70, 20], "bndbox": {"xmin": 50, "ymin": 0, "xmax": 90, "ymax": 30}}]}
        self.store = SimpleNamespace(project=self.root, title="demo", frames_path=self.root / "unused.jsonl", offsets=[],
                                     manifest={"cache_id": "cache-1", "frame_count": 10, "fps": 1, "map": self.layout})
        self.scenario = {"video": "demo", "fps": 1,
            "initial_vehicles": [{"scenario_vehicle_id": 7, "plate": "77사7777", "zone": "B"}],
            "events": [
                {"frame": 3, "type": "PARKED", "scenario_vehicle_id": 1, "plate": "11가1111", "zone": "A"},
                {"frame": 5, "type": "LEFT", "scenario_vehicle_id": 7, "plate": "77사7777", "zone": "B"}],
            "final_zone_counts": {"A": 999}}
        self.path = self.root / "data/parking_logs/parking_log.json"
        self.path.parent.mkdir(parents=True)
        self.save()
        gate = {"video": "demo", "fps": 1, "gate": {"camera_id": "cam01"}, "events": [
            {"frame": 1, "type": "IN", "scenario_vehicle_id": 1, "plate": "11가1111"},
            {"frame": 5, "type": "OUT", "scenario_vehicle_id": 7, "plate": "77사7777", "zone": "B"}]}
        gate_path = self.root / "data/demo/gate_log.json"
        gate_path.parent.mkdir(parents=True)
        gate_path.write_text(json.dumps(gate), encoding="utf-8")
        runtime = self.root / "runtime"
        runtime.mkdir()
        for target, options in (
                ("tracking.json_store.DATA_DIR", {"new": runtime}),
                ("tracking.views.current_user", {"return_value": {"role": "ADMIN"}}),
                ("tracking.views.current_map_layout", {"return_value": self.layout}),
                ("tracking.replay_views.open_store", {"return_value": self.store}),
                ("replay.vehicle_state.open_native_cache", {"side_effect": AssertionError("Manual scenarios must not scan native tracking")}),
                ("native_project.tracking_definitions", {"side_effect": AssertionError("No inference during scenario replay")})):
            mocked = patch(target, **options)
            mocked.start()
            self.addCleanup(mocked.stop)
        json_store.write("initial_parking", [{"zone_id": "A", "parked_count": 0}, {"zone_id": "B", "parked_count": 1}])
        json_store.write("parking_zones", [])
        json_store.write("vehicles", [{"id": "V1", "name": "Car 1", "plate_number": "11가1111", "status": "UNKNOWN",
                                       "team_id": "SECTION_DIGITAL_COMMUNICATION"},
                                      {"id": "V7", "name": "Car 7", "plate_number": "77사7777", "status": "UNKNOWN",
                                       "team_id": "SECTION_COLD_DX"}])

    def save(self):
        self.path.write_text(json.dumps(self.scenario), encoding="utf-8")

    def sync(self, n):
        return self.client.post("/api/replay/vehicle-state/", {"frame": n, "cache_id": "cache-1"}, content_type="application/json")

    def counts(self):
        response = self.client.get("/api/parking-zones/")
        self.assertEqual(response.status_code, 200, response.content)
        return {row["id"]: row["parked_count"] for row in response.json()}

    def test_initial_vehicle_departure_parking_and_rewinds_follow_scenario(self):
        for n, expected in ((0, {"A": 0, "B": 1}), (1, {"A": 0, "B": 1}),
                            (3, {"A": 1, "B": 1}), (5, {"A": 1, "B": 0}),
                            (5, {"A": 1, "B": 0}), (0, {"A": 0, "B": 1}), (3, {"A": 1, "B": 1})):
            self.assertEqual(self.sync(n).status_code, 200)
            self.assertEqual(self.counts(), expected)
        updates = json_store.read("vehicle_replay_state")["vehicles"]
        self.assertEqual((updates["V1"]["status"], updates["V1"]["current_zone_id"]), ("PARKED", "A"))
        self.assertIsNone(updates["V1"]["replay_global_id"])
        self.assertEqual(updates["V1"]["scenario_vehicle_id"], 1)
        self.assertEqual(self.sync(5).status_code, 200)
        self.assertEqual(json_store.read("vehicle_replay_state")["vehicles"]["V7"]["status"], "MOVING")

    def test_departure_changes_section_driving_status_visibility_and_booking_vehicle(self):
        json_store.write("vehicle_schedules", [])
        json_store.write("users", [
            {"id": "digital", "name": "Digital driver", "role": "USER", "team_id": "SECTION_DIGITAL_COMMUNICATION"},
            {"id": "cold", "name": "Cold driver", "role": "USER", "team_id": "SECTION_COLD_DX"}])
        original = json_store.read("vehicles")
        for n, digital_ids, cold_ids in ((0, ["V1"], ["V7"]), (3, ["V1"], ["V7"]),
                                         (5, ["V1", "V7"], []), (5, ["V1", "V7"], []),
                                         (0, ["V1"], ["V7"]), (5, ["V1", "V7"], [])):
            self.assertEqual(self.sync(n).status_code, 200)
            for team, expected in (("SECTION_DIGITAL_COMMUNICATION", digital_ids), ("SECTION_COLD_DX", cold_ids)):
                user = {"id": "digital" if team == "SECTION_DIGITAL_COMMUNICATION" else "cold",
                        "role": "USER", "team_id": team}
                with patch("tracking.views.current_user", return_value=user):
                    rows = self.client.get("/api/vehicles/").json()
                    self.assertEqual([row["id"] for row in rows], expected)
                    schedule = self.client.get("/api/vehicle-schedules/?date=2026-10-18").json()
                    self.assertEqual([row["id"] for row in schedule["vehicles"]], expected)
                    detail = self.client.get("/api/vehicles/V7/")
                    self.assertEqual(detail.status_code, 200 if "V7" in expected else 404)
                    if n == 5 and "V7" in expected:
                        self.assertEqual((detail.json()["status"], detail.json()["current_zone_id"]), ("MOVING", None))
            self.assertEqual(self.counts()["B"], 0 if n == 5 else 1)
        payload = {"date": "2026-10-18", "vehicle_id": "V7", "driver_id": "digital",
                   "start_time": "09:00", "end_time": "10:00", "destination": "Site", "purpose": "Inspection"}
        with patch("tracking.views.current_user", return_value={"id": "cold", "role": "USER", "team_id": "SECTION_COLD_DX"}):
            self.assertEqual(self.client.post("/api/vehicle-schedules/", payload, content_type="application/json").status_code, 400)
        with patch("tracking.views.current_user", return_value={"id": "digital", "role": "USER", "team_id": "SECTION_DIGITAL_COMMUNICATION"}):
            response = self.client.post("/api/vehicle-schedules/", payload, content_type="application/json")
            self.assertEqual(response.status_code, 201, response.content)
            self.assertEqual(response.json()["team_id"], "SECTION_DIGITAL_COMMUNICATION")
        self.assertEqual(json_store.read("vehicles"), original)

    def test_transferred_section_remains_after_reentry_but_rewinds_to_original_section(self):
        gate_path = self.root / "data/demo/gate_log.json"
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        gate["events"].append({"frame": 6, "type": "IN", "scenario_vehicle_id": 7, "plate": "77사7777"})
        gate_path.write_text(json.dumps(gate), encoding="utf-8")
        self.scenario["events"].append({"frame": 7, "type": "PARKED", "scenario_vehicle_id": 7, "plate": "77사7777", "zone": "B"})
        self.save()
        for n, status, team in ((5, "MOVING", "SECTION_DIGITAL_COMMUNICATION"),
                                (6, "PARKING", "SECTION_DIGITAL_COMMUNICATION"),
                                (7, "PARKED", "SECTION_DIGITAL_COMMUNICATION"),
                                (0, "PARKED", "SECTION_COLD_DX")):
            self.assertEqual(self.sync(n).status_code, 200)
            vehicle = self.client.get("/api/vehicles/V7/").json()
            self.assertEqual((vehicle["status"], vehicle["team_id"]), (status, team))

    def test_existing_departure_snapshot_is_driving_and_transferred_on_next_read(self):
        vehicle = json_store.read("vehicles")[1]
        json_store.write("vehicle_replay_state", {
            "vehicles": {"V7": {"plate_number": vehicle["plate_number"], "status": "EXITED",
                                  "current_zone_id": "B", "map_position": {"x": 70, "y": 20},
                                  "parking_type": "DOUBLE", "parking_space_id": "B-01"}},
            "base_states": {"V7": vehicle_fingerprint(vehicle)}})
        row = self.client.get("/api/vehicles/V7/").json()
        self.assertEqual((row["status"], row["team_id"]), ("MOVING", "SECTION_DIGITAL_COMMUNICATION"))
        self.assertIsNone(row["current_zone_id"])
        self.assertIsNone(row["map_position"])
        self.assertIsNone(row["parking_type"])
        self.assertIsNone(row["parking_space_id"])

    def test_gate_entry_parking_completed_zone_and_rewind_preserve_original_state(self):
        original = json_store.read("vehicles")
        for n, status, zone, count in ((0, "UNKNOWN", None, 0), (1, "PARKING", None, 0),
                                       (2, "PARKING", None, 0), (3, "PARKED", "A", 1),
                                       (5, "PARKED", "A", 1), (0, "UNKNOWN", None, 0)):
            self.assertEqual(self.sync(n).status_code, 200)
            row = self.client.get("/api/vehicles/V1/").json()
            self.assertEqual((row["status"], row.get("current_zone_id")), (status, zone))
            self.assertEqual(self.counts()["A"], count)
        self.assertEqual(json_store.read("vehicles"), original)

    def test_gate_recognition_changes_only_matched_vehicle_and_keeps_stored_defaults(self):
        original = json_store.read("vehicles")
        original[0].update(status="MOVING", current_zone_id=None)
        original.append({"id": "UNMATCHED", "plate_number": "OTHER", "status": "PARKED",
                         "current_zone_id": "B", "team_id": "SECTION_COLD_DX"})
        json_store.write("vehicles", original)
        for frame, status in ((0, "MOVING"), (1, "PARKING"), (3, "PARKED"), (0, "MOVING")):
            self.assertEqual(self.sync(frame).status_code, 200)
            rows = {row["id"]: row for row in self.client.get("/api/vehicles/").json()}
            self.assertEqual(rows["V1"]["status"], status)
            self.assertEqual(rows["UNMATCHED"], original[-1])
        self.assertEqual(json_store.read("vehicles"), original)

    def test_scenario_edits_apply_without_regenerating_native_cache(self):
        self.assertEqual(self.sync(3).status_code, 200)
        self.scenario["events"][0]["zone"] = "B"
        self.save()
        self.assertEqual(self.sync(3).status_code, 200)
        self.assertEqual(self.counts(), {"A": 0, "B": 2})

    def test_invalid_scenario_does_not_overwrite_last_good_shared_state(self):
        self.sync(3)
        before = json_store.read("vehicle_replay_state")
        original = deepcopy(self.scenario)
        for field, value in (("zone", "UNKNOWN"), ("frame", 10), ("frame", True),
                             ("scenario_vehicle_id", "1"), ("plate", ""), ("type", "IN")):
            with self.subTest(field=field, value=value):
                self.scenario = deepcopy(original)
                self.scenario["events"][0][field] = value
                self.save()
                self.assertEqual(self.sync(3).status_code, 503)
                self.assertEqual(json_store.read("vehicle_replay_state"), before)

    def test_initial_identity_and_plate_conflicts_are_rejected(self):
        self.scenario["events"].append({"frame": 6, "type": "PARKED", "scenario_vehicle_id": 7,
                                        "plate": "OTHER", "zone": "A"})
        self.save()
        with self.assertRaises(ReplayError):
            read_parking_scenario(self.store)

    def test_missing_or_other_video_scenario_uses_native_mode(self):
        self.scenario["video"] = "other"
        self.save()
        self.assertIsNone(read_parking_scenario(self.store))
        self.path.unlink()
        self.assertIsNone(read_parking_scenario(self.store))
