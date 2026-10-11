from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import os

from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory

from . import views
from .media_stream import media_response


class MediaRangeTests(SimpleTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "sample.mp4"
        self.payload = bytes(range(256)) * 4
        self.path.write_bytes(self.payload)
        self.factory = APIRequestFactory()

    def test_ranges_return_exact_bytes(self):
        for header, start, end in [("bytes=0-99", 0, 99), ("bytes=900-", 900, 1023), ("bytes=-128", 896, 1023), ("bytes=1000-9999", 1000, 1023), ("bytes=-9999", 0, 1023)]:
            with self.subTest(header=header):
                response = media_response(self.factory.get("/", HTTP_RANGE=header), self.path, "video/mp4")
                try:
                    self.assertEqual(response.status_code, 206)
                    self.assertEqual(response["Content-Range"], f"bytes {start}-{end}/1024")
                    self.assertEqual(int(response["Content-Length"]), end-start+1)
                    self.assertEqual(b"".join(response.streaming_content), self.payload[start:end+1])
                finally:
                    response.close()

    def test_invalid_ranges(self):
        for header in ["bytes=1024-", "bytes=200-100", "bytes=-0", "bytes=-", "bytes=0-1,5-6"]:
            response = media_response(self.factory.get("/", HTTP_RANGE=header), self.path, "video/mp4")
            self.assertEqual(response.status_code, 416)
            self.assertEqual(response["Content-Range"], "bytes */1024")
            response.close()

    def test_full_file_and_head(self):
        response = media_response(self.factory.get("/"), self.path, "video/mp4")
        try:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Accept-Ranges"], "bytes")
            self.assertEqual(b"".join(response.streaming_content), self.payload)
        finally:
            response.close()
        response = media_response(self.factory.head("/"), self.path, "video/mp4")
        self.assertEqual(response.content, b"")
        self.assertEqual(response["Content-Length"], "1024")



class MapPositionTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.records = [{"id": "V1", "plate_number": "TEST", "map_position": {"map_id": "parkinglot_map.jpg", "x": 10, "y": 10}}]
        self.body = {"plate_number": "TEST", "camera_id": "camera_01", "zone_id": "A", "status": "MOVING"}

    def submit(self, extra):
        collections = {"vehicles": deepcopy(self.records), "vehicle_replay_state": {}, "tracking_logs": [], "map_layout": {"map_id": "parkinglot_map.jpg"}}
        with patch.object(views, "current_user", return_value={"role": "ADMIN"}), patch.object(views, "read", side_effect=lambda name: collections[name]), patch.object(views, "write") as write, patch.object(views, "current_map_layout", return_value={"map_id": "parkinglot_map.jpg", "zones": [{"id": z} for z in "ABCDEFGHIJKLMN"]}):
            response = views.tracking_event(self.factory.post("/api/tracking-events/", {**self.body, **extra}, format="json"))
            return response, write.call_args_list

    def test_coordinates_persist_in_vehicle_and_log_including_map_edges(self):
        for x, y in [(0, 100), (100, 0), (57.5, 23.2)]:
            with self.subTest(x=x, y=y):
                position = {"map_id": "parkinglot_map.jpg", "x": x, "y": y}
                response, writes = self.submit({"map_position": position})
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.data["map_position"], position)
                self.assertEqual(writes[0].args[1][0]["map_position"], position)
                self.assertEqual(writes[1].args[1][-1]["map_position"], position)

    def test_invalid_positions_never_write_data(self):
        invalid = [[], {}, {"map_id": "wrong", "x": 1, "y": 2}]
        for x in [-1, 101, "10", True, None]:
            invalid.append({"map_id": "parkinglot_map.jpg", "x": x, "y": 50})
        for position in invalid:
            with self.subTest(position=position):
                response, writes = self.submit({"map_position": position})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(writes, [])

    def test_legacy_events_clear_old_position(self):
        for extra in [{}, {"map_position": None}]:
            response, writes = self.submit(extra)
            self.assertEqual(response.status_code, 201)
            self.assertIsNone(writes[0].args[1][0]["map_position"])

    def test_tracking_event_uses_current_external_map_id_and_zone_catalog(self):
        layout = {"map_id": "map.png", "zones": [{"id": "EXTERNAL"}]}
        with patch.object(views, "current_map_layout", return_value=layout):
            # submit patches the demo layout, so call the view with an isolated store here.
            collections = {"vehicles": deepcopy(self.records), "vehicle_replay_state": {}, "tracking_logs": []}
            with patch.object(views, "current_user", return_value={"role": "ADMIN"}), patch.object(views, "read", side_effect=lambda name: collections[name]), patch.object(views, "write") as write:
                response = views.tracking_event(self.factory.post("/api/tracking-events/", {
                    **self.body, "zone_id": "EXTERNAL", "map_position": {"map_id": "map.png", "x": 10, "y": 20},
                }, format="json"))
                self.assertEqual(response.status_code, 201)
                self.assertEqual(write.call_args_list[0].args[1][0]["current_zone_id"], "EXTERNAL")

    def test_all_legend_zones_are_accepted(self):
        for zone in "ABCDEFGHIJKLMN":
            response, writes = self.submit({"zone_id": zone})
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.data["zone_id"], zone)
            self.assertEqual(writes[0].args[1][0]["current_zone_id"], zone)

    def test_removed_numbered_zones_are_rejected_without_writing(self):
        for zone in ["P1", "P7", "1", "7", "A-01", "B-02"]:
            response, writes = self.submit({"zone_id": zone})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(writes, [])

    def test_unknown_zone_and_plate_do_not_change_any_vehicle(self):
        for fields, expected in [({"zone_id": "P8"}, 400), ({"plate_number": "UNREGISTERED", "vehicle_id": "V1"}, 404)]:
            response, writes = self.submit(fields)
            self.assertEqual(response.status_code, expected)
            self.assertEqual(writes, [])

    def test_tracking_matches_plate_even_when_another_id_is_supplied(self):
        response, writes = self.submit({"vehicle_id": "NOT-V1"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["vehicle_id"], "V1")

    def test_position_updates_require_admin(self):
        with patch.object(views, "current_user", return_value={"role": "USER"}), patch.object(views, "write") as write, patch.object(views, "current_map_layout", return_value={"map_id": "parkinglot_map.jpg", "zones": [{"id": z} for z in "ABCDEFGHIJKLMN"]}):
            response = views.tracking_event(self.factory.post("/api/tracking-events/", self.body, format="json"))
            self.assertEqual(response.status_code, 403)
            write.assert_not_called()


class UserParkingMapTests(SimpleTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        media = Path(self.directory.name)
        (media / "maps").mkdir()
        (media / "maps" / "parkinglot_map.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        self.patch_media = patch.object(views, "MEDIA_DIR", media)
        self.patch_media.start()
        self.addCleanup(self.patch_media.stop)
        self.patch_map = patch.dict(os.environ, {"WEB_BEV_MAP": str(media / "missing-project-map.png")})
        self.patch_map.start()
        self.addCleanup(self.patch_map.stop)
        self.store = {
            "vehicle_replay_state": {},
            "map_layout": {"map_id": "parkinglot_map.jpg", "zones": [{"id": "A", "label": [50, 50]}]},
            "vehicles": [
                {"id": "V1", "plate_number": "OWN", "team_id": "TEAM_A", "status": "PARKED", "map_position": None},
                {"id": "V2", "plate_number": "OTHER", "team_id": "TEAM_B", "status": "PARKED", "map_position": {"map_id": "parkinglot_map.jpg", "x": 1, "y": 2}},
            ],
            "tracking_logs": [],
        }
        self.patch_read = patch.object(views, "read", side_effect=lambda name: deepcopy(self.store[name]))
        self.patch_read.start()
        self.addCleanup(self.patch_read.stop)
        self.user = {"role": "USER", "team_id": "TEAM_A"}

    def test_user_can_load_map_but_not_admin_media(self):
        with patch.object(views, "current_user", return_value=self.user):
            response = self.client.get("/api/parking-map/")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("cameras", response.json())
            self.assertEqual(response.json()["layout"]["map_id"], "parkinglot_map.jpg")
            image = self.client.get("/api" + response.json()["map"]["url"])
            try:
                self.assertEqual(image.status_code, 200)
                self.assertEqual(image["Content-Type"], "image/jpeg")
                self.assertEqual(b"".join(image.streaming_content), b"\xff\xd8\xff\xd9")
            finally:
                image.close()
            for path in ["/api/tracking-logs/"]:
                self.assertEqual(self.client.get(path).status_code, 403)

    def test_anonymous_cannot_read_map_or_positions(self):
        with patch.object(views, "current_user", return_value=None):
            for path in ["/api/parking-map/", "/api/parking-map/image/", "/api/vehicles/"]:
                self.assertEqual(self.client.get(path).status_code, 401)

    def test_user_poll_receives_new_positions_for_own_team_only(self):
        position = {"map_id": "parkinglot_map.jpg", "x": 57.5, "y": 23.2}
        with patch.object(views, "current_user", return_value={"role": "ADMIN"}), patch.object(views, "write", side_effect=lambda name, records: self.store.update({name: deepcopy(records)})):
            event = self.client.post("/api/tracking-events/", {"plate_number": "OWN", "camera_id": "camera_01", "zone_id": "A", "map_position": position}, content_type="application/json")
            self.assertEqual(event.status_code, 201)
        with patch.object(views, "current_user", return_value=self.user):
            for query in ["", "?team_id=TEAM_B"]:
                response = self.client.get("/api/vehicles/" + query)
                self.assertEqual([v["id"] for v in response.json()], ["V1"])
                self.assertEqual(response.json()[0]["map_position"], position)
            self.assertEqual(self.client.get("/api/vehicles/V2/").status_code, 404)

    def test_missing_map_returns_empty_manifest_and_image_404(self):
        with patch.object(views, "current_user", return_value=self.user), patch.object(views, "first_media", return_value=None):
            self.assertIsNone(self.client.get("/api/parking-map/").json()["map"])
            self.assertEqual(self.client.get("/api/parking-map/image/").status_code, 404)
