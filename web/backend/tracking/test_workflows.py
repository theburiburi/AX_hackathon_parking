from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase
from . import json_store
import seed


class WorkflowTests(SimpleTestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        shutil.copytree(seed.ROOT / "fixtures", root / "fixtures")
        with patch.object(seed, "ROOT", root):
            seed.initialize()
        store_patch = patch.object(json_store, "DATA_DIR", root / "data")
        store_patch.start()
        self.addCleanup(store_patch.stop)
        self.admin = self.login("admin")
        self.user = self.login("digital")

    def login(self, user_id):
        response = self.client.post("/api/auth/login/", {"id": user_id, "password": "test"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        return {"HTTP_AUTHORIZATION": "Bearer " + response.json()["token"]}

    def test_login_and_profile_include_person_name_and_team(self):
        for user_id, name, team in (
            ("admin", "관리자", None),
            ("digital", "권혁돈", "SECTION_DIGITAL_COMMUNICATION"),
            ("digital2", "디지털 사용자 2", "SECTION_DIGITAL_COMMUNICATION"),
            ("digital3", "디지털 사용자 3", "SECTION_DIGITAL_COMMUNICATION"),
            ("cold-dx", "조의재", "SECTION_COLD_DX"),
            ("steelmaking", "한용만", "SECTION_STEELMAKING_CASTING"),
        ):
            with self.subTest(user_id=user_id):
                response = self.client.post("/api/auth/login/", {
                    "id": user_id, "password": "test",
                }, content_type="application/json")
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data["user"]["id"], user_id)
                self.assertEqual(set(data["user"]), {"id", "name", "role", "team_id", "team_name"})
                self.assertEqual(data["user"]["name"], name)
                self.assertEqual(data["user"]["team_id"], team)
                team_name = next((item["name"] for item in json_store.read("teams") if item["id"] == team), name)
                self.assertEqual(data["user"]["team_name"], team_name)
                profile = self.client.get("/api/auth/me/", HTTP_AUTHORIZATION="Bearer " + data["token"])
                self.assertEqual(profile.status_code, 200)
                self.assertEqual(profile.json(), data["user"])
                self.assertNotIn("password", data["user"])

    def test_invalid_login_is_rejected_without_issuing_token(self):
        for body in (
            {"id": "digital", "password": "wrong"},
            {"id": "missing", "password": "test"},
            {"id": "digital", "password": ""},
            {"id": "digital", "password": None},
            {"id": "digital", "password": 1234},
            {"id": None, "password": "test"},
            {"id": " ", "password": "test"},
            {"id": 1234, "password": "test"},
            {"id": {}, "password": "test"},
            {"username": "digital", "password": "test"},
            {}, [],
        ):
            with self.subTest(body=body):
                response = self.client.post("/api/auth/login/", body, content_type="application/json")
                self.assertEqual(response.status_code, 401)
                self.assertNotIn("token", response.json())

    def test_initial_accounts_use_one_stable_id_for_login_and_schedules(self):
        for user in json_store.read("users"):
            self.assertEqual(set(user), {"id", "password", "name", "role", "team_id", "team_name"})
        day = self.client.get("/api/vehicle-schedules/?date=2026-10-10", **self.user)
        self.assertEqual(day.status_code, 200)
        self.assertEqual({member["id"] for member in day.json()["members"]}, {"digital", "digital2", "digital3"})

    def test_json_account_edits_control_password_name_and_section_display(self):
        users = json_store.read("users")
        user = next(item for item in users if item["id"] == "digital")
        user.update(password=" demo ", name="이름 변경", team_name="테스트 섹션")
        json_store.write("users", users)
        for password in ("test", "demo"):
            response = self.client.post("/api/auth/login/", {"id": "digital", "password": password}, content_type="application/json")
            self.assertEqual(response.status_code, 401)
        response = self.client.post("/api/auth/login/", {"id": " digital ", "password": " demo "}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["name"], "이름 변경")
        self.assertEqual(response.json()["user"]["team_name"], "테스트 섹션")
        self.assertNotIn("password", response.json()["user"])

    def test_existing_session_reads_edited_section_name_without_login_again(self):
        users = json_store.read("users")
        user = next(item for item in users if item["id"] == "digital")
        user["team_name"] = "광양디지털통신기술섹션"
        json_store.write("users", users)
        response = self.client.get("/api/auth/me/", **self.user)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["team_name"], "광양디지털통신기술섹션")
        self.assertEqual(response.json()["team_id"], "SECTION_DIGITAL_COMMUNICATION")
        self.assertNotIn("password", response.json())

    def test_seed_preserves_edited_accounts_and_existing_business_data(self):
        users = json_store.read("users")
        users[0]["password"] = "custom"
        json_store.write("users", users)
        json_store.write("vehicle_schedules", [{"id": "existing-booking"}])
        json_store.write("tracking_logs", [{"id": "existing-event"}])
        before = {name: json_store.read(name) for name in ("users", "vehicles", "vehicle_schedules", "tracking_logs")}
        with patch.object(seed, "ROOT", json_store.DATA_DIR.parent):
            seed.initialize()
            seed.initialize()
        self.assertEqual({name: json_store.read(name) for name in before}, before)

    def test_map_regions_match_legend_and_do_not_include_old_numbered_regions(self):
        layout = self.client.get("/api/parking-map/", **self.user).json()["layout"]
        self.assertEqual([zone["id"] for zone in layout["zones"]], list("ABCDEFGHIJKLMN"))
        self.assertEqual(layout["map_id"], "map.png")
        zones = json_store.read("parking_zones")
        self.assertEqual([zone["id"] for zone in zones], list("ABCDEFGHIJKLMN"))

    def test_login_and_vehicle_scope_remain_section_restricted(self):
        self.assertEqual(self.client.get("/api/auth/me/", **self.user).json()["id"], "digital")
        self.assertEqual(self.client.get("/api/vehicles/").status_code, 401)
        self.assertEqual(self.client.get("/api/tracking-logs/", **self.user).status_code, 403)
        for vehicle in self.client.get("/api/vehicles/?team_id=OTHER", **self.user).json():
            self.assertEqual(vehicle["team_id"], "SECTION_DIGITAL_COMMUNICATION")

    def test_scenario_vehicles_are_grouped_into_sections_without_old_bookings(self):
        groups = (("digital", [1, 2, 3]), ("steelmaking", [4, 5, 6]), ("cold-dx", [7, 8, 9, 10]))
        expected_plates = ["11가1111", "22나2222", "33다3333", "44라4444", "55마5555",
                           "66바6666", "77사7777", "88아8888", "99자9999", "10차1010"]
        all_vehicles = self.client.get("/api/vehicles/", **self.admin).json()
        self.assertEqual([row["plate_number"] for row in all_vehicles], expected_plates)
        for user_id, numbers in groups:
            with self.subTest(user=user_id):
                headers = self.login(user_id)
                rows = self.client.get("/api/vehicles/?team_id=OTHER", **headers).json()
                self.assertEqual([row["scenario_vehicle_id"] for row in rows], numbers)
                schedules = self.client.get("/api/vehicle-schedules/?date=2026-10-18", **headers).json()
                self.assertEqual([row["scenario_vehicle_id"] for row in schedules["vehicles"]], numbers)
                self.assertEqual(schedules["schedules"], [])
        parked = [row for row in all_vehicles if row["status"] == "PARKED"]
        self.assertEqual([(row["scenario_vehicle_id"], row["current_zone_id"]) for row in parked], [(7, "L")])
        self.assertTrue(all(row["status"] == "UNKNOWN" for row in all_vehicles if row["scenario_vehicle_id"] != 7))
        self.assertEqual(json_store.read("vehicle_schedules"), [])
