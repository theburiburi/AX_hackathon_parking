import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch

from django.core import signing
from django.test import Client, SimpleTestCase

import seed
from . import json_store
from .views import TOKEN_SALT


class ScheduleTests(SimpleTestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        shutil.copytree(seed.ROOT / "fixtures", root / "fixtures")
        with patch.object(seed, "ROOT", root):
            seed.initialize()
        self.root = root
        store_patch = patch.object(json_store, "DATA_DIR", root / "data")
        store_patch.start()
        self.addCleanup(store_patch.stop)
        self.demo_records = json_store.read("vehicle_schedules")
        json_store.write("vehicle_schedules", [])
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
        self.assertEqual(self.create("cold-dx", vehicle_id="V007", driver_id="cold-dx").status_code, 201)
        self.assertEqual(self.create("steelmaking", vehicle_id="V004", driver_id="steelmaking").status_code, 201)
        response = self.day("digital2", "date=2026-09-26&team_id=SECTION_COLD_DX")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual([item["driver_id"] for item in data["schedules"]], ["digital"])
        self.assertFalse(data["schedules"][0]["can_edit"])
        self.assertEqual([v["id"] for v in data["vehicles"]], ["V001", "V002", "V003"])
        self.assertEqual({u["id"] for u in data["members"]}, {"digital", "digital2", "digital3"})
        self.assertNotIn("password", json.dumps(data))
        self.assertEqual(len(self.day("admin").json()["schedules"]), 3)
        filtered = self.day("admin", "date=2026-09-26&team_id=SECTION_COLD_DX").json()
        self.assertEqual([s["vehicle_id"] for s in filtered["schedules"]], ["V007"])
        self.assertEqual(self.day(query="date=2026-09-27").json()["schedules"], [])

    def test_unauthenticated_and_forged_owner_or_vehicle(self):
        self.assertEqual(self.client.get("/api/vehicle-schedules/").status_code, 401)
        self.assertEqual(self.client.post("/api/vehicle-schedules/", self.payload, content_type="application/json").status_code, 401)
        self.assertEqual(self.create(vehicle_id="V007").status_code, 400)
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
        self.assertEqual(self.create(start_time="19:30", end_time="20:00").status_code, 201)
        self.assertEqual(self.create(date="2026-09-27").status_code, 201)

    def test_operating_time_boundaries_for_users_and_admins(self):
        day = 11
        for user in ("digital", "admin"):
            for start, end in (("06:00", "06:01"), ("19:59", "20:00"), ("06:00", "20:00")):
                with self.subTest(user=user, start=start, end=end):
                    self.assertEqual(self.create(user, date=f"2026-10-{day}", start_time=start, end_time=end).status_code, 201)
                    day += 1
        before = json_store.read("vehicle_schedules")
        for user in ("digital", "admin"):
            for start, end in (("05:59", "06:30"), ("19:30", "20:01"), ("20:00", "21:00"), ("23:30", "24:00"), ("06:00", "24:00")):
                with self.subTest(user=user, start=start, end=end):
                    response = self.create(user, start_time=start, end_time=end)
                    self.assertEqual(response.status_code, 400)
                    self.assertIn("06:00~20:00", str(response.json()))
        self.assertEqual(json_store.read("vehicle_schedules"), before)

    def test_updates_cannot_move_existing_bookings_outside_operating_hours(self):
        item = self.create().json()
        before = json_store.read("vehicle_schedules")
        for user in ("digital", "admin"):
            for changes in ({"start_time": "05:59"}, {"end_time": "20:01"}, {"end_time": "24:00"}):
                with self.subTest(user=user, changes=changes):
                    self.assertEqual(self.change(item, user, **changes).status_code, 400)
                    self.assertEqual(json_store.read("vehicle_schedules"), before)
        self.assertEqual(self.change(item, start_time="06:00", end_time="20:00").status_code, 200)

    def test_historical_midnight_booking_remains_readable_without_blocking_daytime(self):
        item = self.create().json()
        item.update(start_time="23:30", end_time="24:00")
        json_store.write("vehicle_schedules", [item])
        self.assertEqual(self.day().json()["schedules"][0]["end_time"], "24:00")
        self.assertEqual(self.create(start_time="06:00", end_time="07:00").status_code, 201)

    def test_driver_cannot_book_two_vehicles_simultaneously(self):
        vehicles = json_store.read("vehicles")
        vehicles.append({**vehicles[0], "id": "EXTRA-DIGITAL", "plate_number": "TEST-04"})
        json_store.write("vehicles", vehicles)
        self.create()
        self.assertEqual(self.create(vehicle_id="EXTRA-DIGITAL").status_code, 409)

    def test_update_cancel_permissions_and_persistence(self):
        item = self.create().json()
        self.assertEqual(self.change(item, "digital2", purpose="변경").status_code, 403)
        self.assertEqual(self.change(item, "cold-dx", purpose="변경").status_code, 404)
        self.assertEqual(self.change(item, vehicle_id="V007").status_code, 400)
        response = self.change(item, start_time="11:00", end_time="12:00", purpose="회의")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json_store.read("vehicle_schedules")[0]["purpose"], "회의")
        self.assertEqual(self.client.delete(f"/api/vehicle-schedules/{item['id']}/", **self.headers("digital2")).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/vehicle-schedules/{item['id']}/", **self.headers("cold-dx")).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/vehicle-schedules/{item['id']}/", **self.headers("digital")).status_code, 204)
        self.assertEqual(self.day().json()["schedules"], [])
        self.assertEqual(self.create().status_code, 201)

    def test_admin_can_assign_and_manage_all_sections(self):
        item = self.create("admin", vehicle_id="V007", driver_id="cold-dx").json()
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

    def test_weekday_series_is_bounded_read_only_and_section_scoped(self):
        response = self.create(date="2026-10-12", repeat_weekdays=True, repeat_until="2026-11-11")
        self.assertEqual(response.status_code, 201)
        item = response.json()
        before = json_store.read("vehicle_schedules")
        for day in ("2026-10-12", "2026-10-13", "2026-11-11"):
            data = self.day("digital2", f"date={day}&team_id=SECTION_COLD_DX").json()
            self.assertEqual([row["id"] for row in data["schedules"]], [item["id"]])
            self.assertEqual(data["schedules"][0]["date"], "2026-10-12")
            self.assertFalse(data["schedules"][0]["can_edit"])
            self.assertEqual(self.day("cold-dx", f"date={day}").json()["schedules"], [])
            self.assertEqual(len(self.day("admin", f"date={day}").json()["schedules"]), 1)
        for day in ("2026-10-11", "2026-10-17", "2026-10-18", "2026-11-12", "2030-01-01"):
            self.assertEqual(self.day(query=f"date={day}").json()["schedules"], [])
        self.assertEqual(json_store.read("vehicle_schedules"), before)
        self.assertEqual(len(before), 1)
        self.assertNotIn("repeat_daily", before[0])

    def test_calendar_month_limit_including_leap_day_and_year_boundaries(self):
        for start, end, too_late in (("2026-10-12", "2026-11-11", "2026-11-12"),
                                    ("2026-12-15", "2027-01-14", "2027-01-15"),
                                    ("2027-01-31", "2027-02-27", "2027-02-28"),
                                    ("2024-01-31", "2024-02-28", "2024-02-29"),
                                    ("2024-02-29", "2024-03-28", "2024-03-29")):
            with self.subTest(start=start):
                json_store.write("vehicle_schedules", [])
                self.assertEqual(self.create(date=start, repeat_weekdays=True, repeat_until=end).status_code, 201)
                before = json_store.read("vehicle_schedules")
                self.assertEqual(self.create(date=start, repeat_weekdays=True, repeat_until=too_late).status_code, 400)
                self.assertEqual(json_store.read("vehicle_schedules"), before)

    def test_invalid_recurrence_and_removed_all_options_are_rejected(self):
        for changes in ({"repeat_weekdays": "true"}, {"repeat_weekdays": 1},
                        {"date": "ALL"}, {"repeat_daily": True}, {"repeat_daily": False},
                        {"repeat_weekdays": True},
                        {"repeat_weekdays": True, "repeat_until": "2026-02-30"},
                        {"repeat_weekdays": True, "repeat_until": "2026-09-25"},
                        {"repeat_weekdays": True, "repeat_until": "2026-09-27"},
                        {"date": "2026-10-12", "repeat_weekdays": True, "repeat_until": "2026-10-16", "start_time": "05:59"},
                        {"date": "2026-10-12", "repeat_weekdays": True, "repeat_until": "2026-10-16", "end_time": "20:01"}):
            with self.subTest(changes=changes):
                self.assertEqual(self.create(**changes).status_code, 400)
                self.assertEqual(json_store.read("vehicle_schedules"), [])
        self.assertEqual(self.day(query="date=ALL").status_code, 400)
        # Single weekend reservations still work, as do weekday-only one-day series.
        self.assertEqual(self.create().status_code, 201)
        self.assertEqual(self.create(date="2026-09-28", repeat_weekdays=True, repeat_until="2026-09-28").status_code, 201)

    def test_conflicts_use_actual_weekdays_and_allow_touching_times(self):
        self.assertEqual(self.create(date="2026-10-12", repeat_weekdays=True, repeat_until="2026-10-25").status_code, 201)
        # Vehicle and driver checks apply on every occurrence, including the last.
        for day in ("2026-10-12", "2026-10-23"):
            self.assertEqual(self.create("digital2", driver_id="digital2", date=day).status_code, 409)
            self.assertEqual(self.create(vehicle_id="V002", date=day).status_code, 409)
        self.assertEqual(self.create(date="2026-10-23", start_time="10:00", end_time="11:00").status_code, 201)
        for day in ("2026-10-11", "2026-10-17", "2026-10-18", "2026-10-24"):
            self.assertEqual(self.create(date=day).status_code, 201)
        # Two repeated periods overlap only across a weekend: no conflict.
        self.assertEqual(self.create(date="2026-10-24", repeat_weekdays=True, repeat_until="2026-10-30").status_code, 201)
        self.assertEqual(self.create(date="2026-10-19", repeat_weekdays=True, repeat_until="2026-10-26").status_code, 409)

    def test_conflict_late_in_period_rejects_entire_registration_and_update(self):
        self.create(date="2026-11-05")
        before = json_store.read("vehicle_schedules")
        self.assertEqual(self.create(date="2026-10-12", repeat_weekdays=True, repeat_until="2026-11-11").status_code, 409)
        self.assertEqual(json_store.read("vehicle_schedules"), before)
        item = self.create(date="2026-10-12", repeat_weekdays=True, repeat_until="2026-10-30").json()
        before = json_store.read("vehicle_schedules")
        self.assertEqual(self.change(item, repeat_until="2026-11-11").status_code, 409)
        self.assertEqual(json_store.read("vehicle_schedules"), before)
        self.assertEqual(self.change(item, repeat_until="2026-11-12").status_code, 400)
        self.assertEqual(json_store.read("vehicle_schedules"), before)

    def test_series_edit_convert_cancel_and_owner_checks(self):
        item = self.create(date="2026-10-12", repeat_weekdays=True, repeat_until="2026-11-11").json()
        occurrence = self.day(query="date=2026-10-20").json()["schedules"][0]
        self.assertEqual(self.change(occurrence, "digital2", end_time="11:00").status_code, 403)
        self.assertEqual(self.change(occurrence, "cold-dx").status_code, 404)
        self.assertEqual(self.change(occurrence, end_time="11:00").status_code, 200)
        self.assertEqual(json_store.read("vehicle_schedules")[0]["date"], "2026-10-12")
        self.assertEqual(self.day(query="date=2026-11-11").json()["schedules"][0]["end_time"], "11:00")
        result = self.change(occurrence, "admin", date="2026-10-20", repeat_weekdays=False)
        self.assertEqual(result.status_code, 200)
        self.assertIsNone(result.json()["repeat_until"])
        self.assertEqual(self.day(query="date=2026-10-12").json()["schedules"], [])
        self.assertEqual(len(self.day(query="date=2026-10-20").json()["schedules"]), 1)
        result = self.change(result.json(), repeat_weekdays=True, repeat_until="2026-11-19")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.client.delete(f"/api/vehicle-schedules/{item['id']}/", **self.headers("digital")).status_code, 204)
        self.assertEqual(self.day(query="date=2026-11-19").json()["schedules"], [])

    def test_simultaneous_series_requests_cannot_double_book(self):
        barrier = Barrier(2)
        def reserve(user):
            barrier.wait(timeout=10)
            payload = {**self.payload, "driver_id": user, "date": "2026-10-12", "repeat_weekdays": True, "repeat_until": "2026-11-11"}
            return Client().post("/api/vehicle-schedules/", payload, content_type="application/json", **self.headers(user)).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, ["digital", "digital2"]))
        self.assertEqual(sorted(results), [201, 409])
        self.assertEqual(len(json_store.read("vehicle_schedules")), 1)

    def test_initial_scenario_inventory_has_three_digital_vehicles_and_no_old_bookings(self):
        json_store.write("vehicle_schedules", self.demo_records)
        data = self.day(query="date=2026-10-12").json()
        self.assertEqual({v["plate_number"] for v in data["vehicles"]}, {"11가1111", "22나2222", "33다3333"})
        self.assertEqual(data["schedules"], [])
        self.assertEqual(self.demo_records, [])
        self.assertEqual(self.day(query="date=2026-10-10").json()["schedules"], [])
        self.assertEqual(self.day(query="date=2026-11-10").json()["schedules"], [])
