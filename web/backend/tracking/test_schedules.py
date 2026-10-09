import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch

from django.core import signing
from django.core.management import call_command
from django.test import Client, SimpleTestCase

import seed
from . import json_store
from .views import TOKEN_SALT, password_matches


class ScheduleTests(SimpleTestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        shutil.copytree(seed.ROOT / "fixtures", root / "fixtures")
        with patch.object(seed, "ROOT", root):
            seed.initialize("ScheduleTest123!")
        self.root = root
        store_patch = patch.object(json_store, "DATA_DIR", root / "data")
        store_patch.start()
        self.addCleanup(store_patch.stop)
        self.payload = {"date": "2026-09-26", "vehicle_id": "V001", "driver_id": "digital", "start_time": "09:00", "end_time": "10:00", "destination": "공장", "purpose": "현장 점검"}

    def headers(self, user):
        return {"HTTP_AUTHORIZATION": "Bearer " + signing.dumps({"user_id": user}, salt=TOKEN_SALT)}

    def create(self, user="digital", **changes):
        return self.client.post("/api/vehicle-schedules/", {**self.payload, **changes}, content_type="application/json", **self.headers(user))

    def day(self, user="digital", query="date=2026-09-26"):
        return self.client.get("/api/vehicle-schedules/?" + query, **self.headers(user))

    def change(self, item, user="digital", **changes):
        return self.client.put(f"/api/vehicle-schedules/{item['id']}/", {**item, **changes}, content_type="application/json", **self.headers(user))

    def test_section_visibility_includes_colleagues_but_never_other_sections(self):
        self.assertEqual(self.create().status_code, 201)
        self.assertEqual(self.create("cold-dx", vehicle_id="V002", driver_id="cold-dx").status_code, 201)
        self.assertEqual(self.create("steelmaking", vehicle_id="V003", driver_id="steelmaking").status_code, 201)
        response = self.day("digital2", "date=2026-09-26&team_id=SECTION_COLD_DX")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual([item["driver_id"] for item in data["schedules"]], ["digital"])
        self.assertFalse(data["schedules"][0]["can_edit"])
        self.assertEqual([v["id"] for v in data["vehicles"]], ["V001"])
        self.assertEqual({u["id"] for u in data["members"]}, {"digital", "digital2", "digital3"})
        self.assertNotIn("password", json.dumps(data))
        self.assertEqual(len(self.day("admin").json()["schedules"]), 3)
        filtered = self.day("admin", "date=2026-09-26&team_id=SECTION_COLD_DX").json()
        self.assertEqual([s["vehicle_id"] for s in filtered["schedules"]], ["V002"])
        self.assertEqual(self.day(query="date=2026-09-27").json()["schedules"], [])

    def test_unauthenticated_and_forged_owner_or_vehicle(self):
        self.assertEqual(self.client.get("/api/vehicle-schedules/").status_code, 401)
        self.assertEqual(self.client.post("/api/vehicle-schedules/", self.payload, content_type="application/json").status_code, 401)
        self.assertEqual(self.create(vehicle_id="V002").status_code, 400)
        self.assertEqual(self.create(driver_id="digital2").status_code, 400)
        self.assertEqual(self.create("admin", vehicle_id="V001", driver_id="cold-dx").status_code, 400)
        item = self.create(team_id="SECTION_COLD_DX", created_by="admin").json()
        self.assertEqual(item["team_id"], "SECTION_DIGITAL_COMMUNICATION")
        self.assertEqual(item["created_by"], "digital")

    def test_invalid_dates_times_and_fields(self):
        for changes in ({"date": "2026-02-30"}, {"date": "20260926"}, {"date": None}, {"start_time": "24:00"}, {"start_time": "9:00"}, {"end_time": "10:60"}, {"end_time": "09:00"}, {"end_time": "08:00"}, {"destination": " "}, {"purpose": []}, {"purpose": "x" * 201}):
            with self.subTest(changes=changes):
                self.assertEqual(self.create(**changes).status_code, 400)
        self.assertEqual(self.day(query="date=wrong").status_code, 400)
        self.assertEqual(self.client.post("/api/vehicle-schedules/", [], content_type="application/json", **self.headers("digital")).status_code, 400)

    def test_vehicle_conflict_and_touching_time_boundaries(self):
        self.assertEqual(self.create().status_code, 201)
        for start, end in (("09:00", "10:00"), ("08:00", "09:30"), ("09:30", "10:30"), ("08:00", "11:00")):
            self.assertEqual(self.create("digital2", driver_id="digital2", start_time=start, end_time=end).status_code, 409)
        self.assertEqual(self.create("digital2", driver_id="digital2", start_time="10:00", end_time="11:00").status_code, 201)
        self.assertEqual(self.create(start_time="23:30", end_time="24:00").status_code, 201)
        self.assertEqual(self.create(date="2026-09-27").status_code, 201)

    def test_driver_cannot_book_two_vehicles_simultaneously(self):
        vehicles = json_store.read("vehicles")
        vehicles.append({**vehicles[0], "id": "V004", "plate_number": "TEST-04"})
        json_store.write("vehicles", vehicles)
        self.create()
        self.assertEqual(self.create(vehicle_id="V004").status_code, 409)

    def test_update_cancel_permissions_and_persistence(self):
        item = self.create().json()
        self.assertEqual(self.change(item, "digital2", purpose="변경").status_code, 403)
        self.assertEqual(self.change(item, "cold-dx", purpose="변경").status_code, 404)
        self.assertEqual(self.change(item, vehicle_id="V002").status_code, 400)
        response = self.change(item, start_time="11:00", end_time="12:00", purpose="회의")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json_store.read("vehicle_schedules")[0]["purpose"], "회의")
        self.assertEqual(self.client.delete(f"/api/vehicle-schedules/{item['id']}/", **self.headers("digital2")).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/vehicle-schedules/{item['id']}/", **self.headers("cold-dx")).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/vehicle-schedules/{item['id']}/", **self.headers("digital")).status_code, 204)
        self.assertEqual(self.day().json()["schedules"], [])
        self.assertEqual(self.create().status_code, 201)

    def test_admin_can_assign_and_manage_all_sections(self):
        item = self.create("admin", vehicle_id="V002", driver_id="cold-dx").json()
        self.assertEqual(item["driver_name"], "조의재")
        self.assertEqual(self.change(item, "admin", start_time="12:00", end_time="13:00").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/vehicle-schedules/{item['id']}/", **self.headers("admin")).status_code, 204)

    def test_failed_update_preserves_existing_booking(self):
        item = self.create().json()
        self.create("digital2", driver_id="digital2", start_time="10:00", end_time="11:00")
        before = json_store.read("vehicle_schedules")
        self.assertEqual(self.change(item, end_time="10:30").status_code, 409)
        self.assertEqual(json_store.read("vehicle_schedules"), before)

    def test_simultaneous_requests_cannot_double_book(self):
        barrier = Barrier(2)
        def reserve(user):
            barrier.wait(timeout=10)
            return Client().post("/api/vehicle-schedules/", {**self.payload, "driver_id": user}, content_type="application/json", **self.headers(user)).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, ["digital", "digital2"]))
        self.assertEqual(sorted(results), [201, 409])
        self.assertEqual(len(json_store.read("vehicle_schedules")), 1)

    def test_missing_collection_is_compatible_with_existing_workspaces(self):
        (json_store.DATA_DIR / "vehicle_schedules.json").unlink()
        self.assertEqual(self.day().json()["schedules"], [])
        self.assertEqual(self.create().status_code, 201)

    def test_demo_account_upgrade_is_idempotent_and_preserves_existing_data(self):
        original = [u for u in json_store.read("users") if u["id"] not in ("digital2", "digital3")]
        json_store.write("users", original)
        call_command("add_schedule_demo_users", password="local-test", stdout=StringIO())
        users = json_store.read("users")
        self.assertEqual(users[:len(original)], original)
        for username in ("digital2", "digital3"):
            member = next(u for u in users if u["id"] == username)
            self.assertTrue(password_matches("local-test", member))
            self.assertEqual(member["team_id"], "SECTION_DIGITAL_COMMUNICATION")
        call_command("add_schedule_demo_users", password="different", stdout=StringIO())
        self.assertEqual(json_store.read("users"), users)
