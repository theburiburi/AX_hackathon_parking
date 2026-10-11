import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.core import signing
from django.test import SimpleTestCase

import seed
from replay.vehicle_state import _timeline, build_timeline, apply_snapshot
from . import json_store
from .views import TOKEN_SALT


class ReplayVehicleTests(SimpleTestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        shutil.copytree(seed.ROOT / "fixtures", root / "fixtures")
        with patch.object(seed, "ROOT", root):
            seed.initialize()
        store_patch = patch.object(json_store, "DATA_DIR", root / "data")
        store_patch.start()
        self.addCleanup(store_patch.stop)
        self.layout = {"width": 100, "height": 100, "zones": [
            {"id": "A", "capacity": 14, "label": [25, 50], "bndbox": {"xmin": 0, "ymin": 0, "xmax": 30, "ymax": 30}}]}
        json_store.write("initial_parking", [{"zone_id": "A", "parked_count": 20}])
        self.gate = {"video": "demo", "fps": 30, "gate": {"camera_id": "cam01"}, "events": [
            {"frame": 1, "type": "IN", "track_id": 13, "plate": "111가1111"},
            {"frame": 4, "type": "OUT", "track_id": 13, "plate": "111가 1111"}]}
        active = {"global_id": 7, "local_id": 13, "camera_id": "cam01", "state": "ACTIVE", "x": 50, "y": 50}
        parked = {**active, "local_id": 21, "camera_id": "cam02", "state": "PARKED", "x": 20, "y": 20}
        self.frames = [
            {"frame_index": 0, "cameras": {}, "bev": []},
            {"frame_index": 1, "cameras": {"cam01": [active]}, "bev": [active]},
            {"frame_index": 2, "cameras": {"cam02": [parked]}, "bev": [parked]},
            {"frame_index": 3, "cameras": {}, "bev": []},
            {"frame_index": 4, "cameras": {}, "bev": []}]
        offsets = []
        path = root / "frames.jsonl"
        with path.open("wb") as target:
            for frame in self.frames:
                offsets.append(target.tell())
                target.write((json.dumps(frame) + "\n").encode())
        (root / "data/gate_logs").mkdir()
        self.gate_path = root / "data/gate_logs/gate_log.json"
        self.gate_path.write_text(json.dumps(self.gate), encoding="utf-8")
        self.store = SimpleNamespace(project=root, title="demo", frames_path=path, offsets=offsets,
                                     manifest={"cache_id": "cache-1", "frame_count": 5, "fps": 30, "map": self.layout})
        open_patch = patch("tracking.replay_views.open_store", return_value=self.store)
        open_patch.start()
        self.addCleanup(open_patch.stop)
        self.addCleanup(_timeline.cache_clear)

    def headers(self, user="admin"):
        return {"HTTP_AUTHORIZATION": "Bearer " + signing.dumps({"user_id": user}, salt=TOKEN_SALT)}

    def sync(self, frame, user="admin", **extra):
        return self.client.post("/api/replay/vehicle-state/", {"frame": frame, "cache_id": "cache-1", **extra},
                                content_type="application/json", **self.headers(user))

    def vehicles(self, user="digital"):
        return self.client.get("/api/vehicles/", **self.headers(user)).json()

    def occupancy(self):
        with patch("tracking.views.current_map_layout", return_value=self.layout):
            response = self.client.get("/api/parking-zones/", **self.headers("digital"))
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()[0]

    def test_zone_totals_follow_parking_exit_retries_and_backward_seek(self):
        for frame, total in ((0, 20), (1, 20), (3, 21), (3, 21), (4, 20), (0, 20), (3, 21)):
            self.assertEqual(self.sync(frame).status_code, 200)
            counts = self.occupancy()
            self.assertEqual((counts["parked_count"], counts["capacity"], counts["overflow_count"]), (total, 14, total - 14))
        self.assertEqual(json_store.read("initial_parking"), [{"zone_id": "A", "parked_count": 20}])

    def test_aggregate_counts_work_without_registered_vehicles_or_plates(self):
        json_store.write("vehicles", [])
        for event in self.gate["events"]:
            event.pop("plate")
        self.gate_path.write_text(json.dumps(self.gate), encoding="utf-8")
        self.assertEqual(self.sync(3).json()["updated"], 0)
        self.assertEqual(self.occupancy()["parked_count"], 21)
        self.assertEqual(self.sync(4).status_code, 200)
        self.assertEqual(self.occupancy()["parked_count"], 20)

    def test_metadata_edits_and_vehicle_registration_do_not_reset_occupancy(self):
        self.assertEqual(self.sync(3).status_code, 200)
        vehicles = json_store.read("vehicles")
        vehicles[0]["name"] = "Updated name"
        vehicles.append({"id": "NEW", "plate_number": "NEW", "status": "UNKNOWN"})
        json_store.write("vehicles", vehicles)
        self.assertEqual(self.occupancy()["parked_count"], 21)

    def test_manual_events_after_replay_adjust_counts_without_losing_other_tracks(self):
        self.assertEqual(self.sync(3).status_code, 200)
        with patch("tracking.views.current_map_layout", return_value=self.layout):
            for state, total in (("PARKED", 21), ("PARKED", 21), ("MOVING", 20)):
                response = self.client.post("/api/tracking-events/", {"plate_number": "111가1111", "camera_id": "cam02", "zone_id": "A", "status": state},
                                            content_type="application/json", **self.headers())
                self.assertEqual(response.status_code, 201, response.content)
                self.assertEqual(self.occupancy()["parked_count"], total)
        # Explicit replay synchronization restores that frame, without re-adding
        # the manual change on each subsequent occupancy GET.
        self.assertEqual(self.sync(3).status_code, 200)
        self.assertEqual(self.occupancy()["parked_count"], 21)
        self.assertEqual(self.occupancy()["parked_count"], 21)

    def test_entry_camera_handoff_parking_exit_and_backward_seek(self):
        original = json_store.read("vehicles")
        for n, status, zone in [(1, "MOVING", None), (3, "PARKED", "A"), (4, "EXITED", None)]:
            response = self.sync(n)
            self.assertEqual(response.status_code, 200, response.content)
            own = self.vehicles()
            self.assertEqual(len(own), 4)
            self.assertEqual((own[0]["status"], own[0]["current_zone_id"]), (status, zone))
            self.assertIsNone(own[0]["map_position"])
            self.assertEqual(own[0]["replay_global_id"], 7 if n < 4 else None)
            detail = self.client.get("/api/vehicles/V001/", **self.headers("digital")).json()
            self.assertEqual(detail, own[0])
        self.assertEqual(self.sync(0).status_code, 200)
        self.assertEqual(self.vehicles()[0], original[0])
        self.assertEqual(json_store.read("vehicles"), original)
        self.assertEqual(self.sync(3).status_code, 200)
        self.assertEqual(self.vehicles()[0]["current_zone_id"], "A")
        self.assertEqual([v["id"] for v in self.vehicles("cold-dx")], ["V002"])
        self.assertEqual(self.client.get("/api/vehicles/V001/", **self.headers("cold-dx")).status_code, 404)

    def test_invalid_or_unauthorized_requests_do_not_change_shared_state(self):
        self.sync(1)
        before = json_store.read("vehicle_replay_state")
        for n in (-1, 5, True, "1", 1.5, None):
            self.assertEqual(self.sync(n).status_code, 400)
        self.assertEqual(self.sync(1, cache_id="stale").status_code, 409)
        self.assertEqual(self.sync(3, user="digital").status_code, 403)
        self.assertEqual(self.client.post("/api/replay/vehicle-state/", {}, content_type="application/json").status_code, 401)
        self.assertEqual(self.client.get("/api/replay/vehicle-state/", **self.headers()).status_code, 405)
        self.assertEqual(json_store.read("vehicle_replay_state"), before)

    def test_server_uses_saved_results_and_ignores_client_status_or_coordinates(self):
        with patch("native_project.tracking_definitions", side_effect=AssertionError("Must not run tracking")):
            response = self.sync(1, status="PARKED", current_zone_id="A", map_position={"x": 20, "y": 20})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.vehicles()[0]["status"], "MOVING")
        self.assertIsNone(self.vehicles()[0]["current_zone_id"])

    def test_gate_edits_invalidate_associations_and_unregistered_plates_stay_separate(self):
        self.sync(3)
        self.gate["events"][0]["plate"] = "999가9999"
        self.gate_path.write_text(json.dumps(self.gate), encoding="utf-8")
        self.assertEqual(self.sync(3).json()["updated"], 0)
        self.assertNotIn("replay_video", self.vehicles()[0])

    def test_local_ids_never_match_global_ids_or_other_camera_local_ids(self):
        self.frames[1]["cameras"] = {"cam01": [{"local_id": 99, "global_id": 13}]}
        self.frames[1]["bev"] = [{"local_id": 13, "global_id": 7, "camera_id": "cam02", "state": "PARKED", "x": 20, "y": 20}]
        rows = build_timeline(self.frames, self.gate, self.layout)["111가1111"][1]
        self.assertFalse(any(row["status"] == "PARKED" for row in rows))

    def test_invalid_bev_point_does_not_invent_a_parking_zone(self):
        for x in (float("nan"), -1, 101, "20", True):
            self.frames[2]["bev"][0]["x"] = x
            rows = build_timeline(self.frames, self.gate, self.layout)["111가1111"][1]
            self.assertTrue(all(row["current_zone_id"] is None for row in rows))

    def test_changed_plate_does_not_inherit_another_vehicles_snapshot(self):
        self.sync(3)
        vehicles = json_store.read("vehicles")
        vehicles[0]["plate_number"] = "888가8888"
        result = apply_snapshot(vehicles, json_store.read("vehicle_replay_state"))
        self.assertEqual(result[0], vehicles[0])

    def test_initial_double_parking_restores_on_seek_and_clears_after_departure(self):
        vehicles = json_store.read("vehicles")
        vehicles[0].update(status="PARKED", current_zone_id="A", parking_type="DOUBLE", parking_space_id="A-01")
        json_store.write("vehicles", vehicles)
        self.assertEqual(self.sync(0).status_code, 200)
        self.assertEqual(self.vehicles()[0]["parking_type"], "DOUBLE")
        for frame, kind in ((1, None), (3, "UNKNOWN"), (4, None)):
            self.assertEqual(self.sync(frame).status_code, 200)
            self.assertEqual(self.vehicles()[0]["parking_type"], kind)
            self.assertIsNone(self.vehicles()[0]["parking_space_id"])
        self.assertEqual(self.sync(0).status_code, 200)
        self.assertEqual(self.vehicles()[0]["parking_type"], "DOUBLE")
        self.assertEqual(self.vehicles()[0]["parking_space_id"], "A-01")
