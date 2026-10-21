from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase
from .parking_state import initial_zone_counts, zone_occupancy


class InitialParkingTests(SimpleTestCase):
    def setUp(self):
        self.zones = [{"id": "A", "capacity": 14, "label": [25, 50]},
                      {"id": "B", "capacity": 4, "label": [75, 50]}]
        self.document = [{"zone_id": "a", "parked_count": 20}]

    def test_plate_free_counts_can_overflow_capacity(self):
        original = deepcopy(self.document)
        rows = initial_zone_counts(self.document, self.zones)
        self.assertEqual(rows, [{"zone_id": "A", "parked_count": 20}])
        counts = zone_occupancy(self.document, self.zones)
        self.assertEqual(counts["A"], {"initial_parked_count": 20, "parking_delta": 0,
                         "parked_count": 20, "capacity": 14, "overflow_count": 6})
        self.assertEqual(counts["B"]["parked_count"], 0)
        self.assertEqual(self.document, original)

    def test_only_zone_and_total_are_required(self):
        counts = zone_occupancy([{"zone_id": "A", "parked_count": 20}], self.zones)["A"]
        self.assertEqual((counts["parked_count"], counts["capacity"], counts["overflow_count"]), (20, 14, 6))

    def test_capacity_in_inventory_overrides_map_and_updates_overflow_after_parking(self):
        self.document[0]["capacity"] = 10
        self.assertEqual(initial_zone_counts(self.document, self.zones),
                         [{"zone_id": "A", "parked_count": 20, "capacity": 10}])
        counts = zone_occupancy(self.document, self.zones, {"A": 1})["A"]
        self.assertEqual((counts["parked_count"], counts["capacity"], counts["overflow_count"]), (21, 10, 11))
        self.document[0]["capacity"] = 0
        counts = zone_occupancy(self.document, self.zones)["A"]
        self.assertEqual((counts["capacity"], counts["overflow_count"]), (0, 20))

    def test_invalid_capacity_is_rejected(self):
        for capacity in (-1, True, False, 2.5, "14", None):
            with self.subTest(capacity=capacity), self.assertRaises(ValueError):
                initial_zone_counts([{**self.document[0], "capacity": capacity}], self.zones)

    def test_invalid_counts_are_rejected_instead_of_displaying_partial_totals(self):
        for field, value in (("parked_count", -1), ("parked_count", True), ("parked_count", 2.5),
                             ("parked_count", "20"), ("parked_count", None),
                             ("double_parked_count", -1), ("double_parked_count", 21),
                             ("double_parked_count", False), ("double_parked_count", 1.5), ("zone_id", "Z"),
                             ("plate_number", "unused")):
            document = deepcopy(self.document)
            document[0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                initial_zone_counts(document, self.zones)
        for document in ({"schema_version": 1, "vehicles": []}, [None], [{"zone_id": "A"}]):
            with self.assertRaises(ValueError):
                initial_zone_counts(document, self.zones)

    def test_duplicate_zone_case_is_rejected(self):
        with self.assertRaises(ValueError):
            initial_zone_counts(self.document + [{"zone_id": "A", "parked_count": 1}], self.zones)

    def test_cli_check_and_import_never_change_vehicle_data(self):
        self.document[0]["capacity"] = 10
        script = Path(__file__).resolve().parents[2] / "initialize_parking.py"
        spec = importlib.util.spec_from_file_location("initialize_parking_command", script)
        command = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(command)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "web/backend/data"
            runtime.mkdir(parents=True)
            (root / "data/maps").mkdir(parents=True)
            (root / "data/maps/zones.json").write_text(json.dumps({"zones": self.zones}), encoding="utf-8")
            target = runtime / "initial_parking.json"
            target.write_text("[]", encoding="utf-8")
            source = root / "inventory.json"
            source.write_text(json.dumps(self.document), encoding="utf-8")
            vehicle_file = runtime / "vehicles.json"
            vehicle_file.write_text('[{"id": "EXISTING"}]', encoding="utf-8")
            original_vehicles = vehicle_file.read_bytes()
            with patch.object(command, "WEB", root / "web"), patch("builtins.print"):
                self.assertEqual(command.main(["--input", str(source), "--check"]), 0)
                self.assertEqual(target.read_text(encoding="utf-8"), "[]")
                self.assertEqual(command.main(["--input", str(source)]), 0)
                self.assertEqual(json.loads(target.read_text(encoding="utf-8"))[0]["zone_id"], "A")
                self.assertEqual(json.loads(target.read_text(encoding="utf-8"))[0]["capacity"], 10)
                imported = target.read_bytes()
                self.assertEqual(command.main([]), 0)
                self.assertEqual(target.read_bytes(), imported)
                self.document[0]["double_parked_count"] = 21
                source.write_text(json.dumps(self.document), encoding="utf-8")
                self.assertEqual(command.main(["--input", str(source)]), 1)
                self.assertEqual(target.read_bytes(), imported)
                self.assertEqual(vehicle_file.read_bytes(), original_vehicles)

    def test_zone_api_reads_edits_and_does_not_double_count_registered_cars(self):
        # These two known vehicles are already included in the manually entered 20.
        vehicles = [{"id": "V1", "plate_number": "OWN", "team_id": "T1", "status": "PARKED", "current_zone_id": "A"},
                    {"id": "V2", "plate_number": "OTHER", "team_id": "T2", "status": "PARKED", "current_zone_id": "A"}]
        catalog = {"vehicles": vehicles, "vehicle_replay_state": {}, "parking_zones": self.zones,
                   "initial_parking": self.document}
        for role in ("USER", "ADMIN"):
            with patch("tracking.views.current_user", return_value={"role": role, "team_id": "T1"}), \
                    patch("tracking.views.read", side_effect=catalog.__getitem__), \
                    patch("tracking.views.current_map_layout", return_value={"zones": self.zones}):
                response = self.client.get("/api/parking-zones/?team_id=T1")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()[0]["parked_count"], self.document[0]["parked_count"])
                self.assertEqual(response.json()[0]["overflow_count"], self.document[0]["parked_count"] - 14)
                self.assertNotIn("plate_number", response.content.decode())
                self.assertEqual(len(self.client.get("/api/vehicles/").json()), 1 if role == "USER" else 2)
                self.document[0]["parked_count"] += 1
                self.assertEqual(self.client.get("/api/parking-zones/").json()[0]["parked_count"], self.document[0]["parked_count"])
        self.assertEqual(self.client.get("/api/parking-zones/").status_code, 401)

    def test_invalid_inventory_api_returns_error_without_falling_back_to_zero(self):
        with patch("tracking.views.current_user", return_value={"role": "ADMIN"}), \
                patch("tracking.views.current_map_layout", return_value={"zones": self.zones}), \
                patch("tracking.views.read", side_effect=lambda key: self.zones if key == "parking_zones" else [{"zone_id": "A", "parked_count": -1}]):
            response = self.client.get("/api/parking-zones/")
            self.assertEqual(response.status_code, 503)
            self.assertIn("initial_parking.json", response.json()["detail"])

    def test_api_uses_inventory_capacity_instead_of_map_or_catalog(self):
        catalog = {"vehicles": [], "vehicle_replay_state": {},
                   "parking_zones": [{**zone, "capacity": 1000} for zone in self.zones],
                   "initial_parking": [{**self.document[0], "capacity": 10}]}
        for role in ("USER", "ADMIN"):
            with self.subTest(role=role), patch("tracking.views.current_user", return_value={"role": role}), \
                    patch("tracking.views.read", side_effect=catalog.__getitem__), \
                    patch("tracking.views.current_map_layout", return_value={"zones": self.zones}):
                response = self.client.get("/api/parking-zones/")
                self.assertEqual(response.status_code, 200, response.content)
                zone = response.json()[0]
                self.assertEqual((zone["parked_count"], zone["capacity"], zone["overflow_count"]), (20, 10, 10))

    def test_file_edits_are_read_from_disk_without_restart(self):
        from . import json_store
        with TemporaryDirectory() as temporary, patch.object(json_store, "DATA_DIR", Path(temporary)), \
                patch("tracking.views.current_user", return_value={"role": "ADMIN"}), \
                patch("tracking.views.current_map_layout", return_value={"zones": self.zones}):
            json_store.write("parking_zones", self.zones)
            json_store.write("initial_parking", self.document)
            self.assertEqual(self.client.get("/api/parking-zones/").json()[0]["parked_count"], 20)
            self.document[0]["parked_count"] = 25
            json_store.write("initial_parking", self.document)
            self.assertEqual(self.client.get("/api/parking-zones/").json()[0]["parked_count"], 25)
            self.document[0]["capacity"] = 10
            json_store.write("initial_parking", self.document)
            zone = self.client.get("/api/parking-zones/").json()[0]
            self.assertEqual((zone["parked_count"], zone["capacity"], zone["overflow_count"]), (25, 10, 15))
            self.document[0]["capacity"] = -1
            json_store.write("initial_parking", self.document)
            self.assertEqual(self.client.get("/api/parking-zones/").status_code, 503)
            (Path(temporary) / "initial_parking.json").write_text("[", encoding="utf-8")
            self.assertEqual(self.client.get("/api/parking-zones/").status_code, 503)
