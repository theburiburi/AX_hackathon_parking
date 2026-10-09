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
            seed.initialize("TestPassword123!")
        store_patch = patch.object(json_store, "DATA_DIR", root / "data")
        store_patch.start()
        self.addCleanup(store_patch.stop)
        self.admin = self.login("admin")
        self.user = self.login("digital")

    def login(self, username):
        response = self.client.post("/api/auth/login/", {"username": username, "password": "TestPassword123!"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        return {"HTTP_AUTHORIZATION": "Bearer " + response.json()["token"]}

    def test_login_and_profile_include_person_name_and_team(self):
        for username, name, team in (
            ("digital", "권혁돈", "SECTION_DIGITAL_COMMUNICATION"),
            ("cold-dx", "조의재", "SECTION_COLD_DX"),
            ("steelmaking", "한용만", "SECTION_STEELMAKING_CASTING"),
        ):
            with self.subTest(username=username):
                response = self.client.post("/api/auth/login/", {
                    "username": username, "password": "TestPassword123!",
                }, content_type="application/json")
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data["user"]["name"], name)
                self.assertEqual(data["user"]["team_id"], team)
                profile = self.client.get("/api/auth/me/", HTTP_AUTHORIZATION="Bearer " + data["token"])
                self.assertEqual(profile.status_code, 200)
                self.assertEqual(profile.json(), data["user"])
                self.assertNotIn("password_hash", data["user"])
                self.assertNotIn("password_salt", data["user"])

    def test_map_regions_match_legend_and_do_not_include_old_numbered_regions(self):
        layout = self.client.get("/api/parking-map/", **self.user).json()["layout"]
        self.assertEqual([zone["id"] for zone in layout["zones"]], list("ABCDEFGHIJKLMN"))
        self.assertEqual(layout["map_id"], "map.png")
        zones = json_store.read("parking_zones")
        self.assertEqual([zone["id"] for zone in zones], list("ABCDEFGHIJKLMN"))

    def test_login_and_vehicle_scope_remain_section_restricted(self):
        self.assertEqual(self.client.get("/api/auth/me/", **self.user).json()["username"], "digital")
        self.assertEqual(self.client.get("/api/vehicles/").status_code, 401)
        self.assertEqual(self.client.get("/api/tracking-logs/", **self.user).status_code, 403)
        for vehicle in self.client.get("/api/vehicles/?team_id=OTHER", **self.user).json():
            self.assertEqual(vehicle["team_id"], "SECTION_DIGITAL_COMMUNICATION")
