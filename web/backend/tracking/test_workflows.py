from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from . import json_store
from . import project_media
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

    def test_login_scope_and_approval_lifecycle(self):
        self.assertEqual(self.client.get("/api/auth/me/", **self.user).json()["username"], "digital")
        self.assertEqual(self.client.get("/api/vehicles/").status_code, 401)
        self.assertEqual(self.client.get("/api/tracking-logs/", **self.user).status_code, 403)
        for vehicle in self.client.get("/api/vehicles/?team_id=OTHER", **self.user).json():
            self.assertEqual(vehicle["team_id"], "SECTION_DIGITAL_COMMUNICATION")
        response = self.client.post("/api/vehicle-requests/", {"request_type": "CREATE", "vehicle": {
            "name": "Test", "plate_number": "TEST-123", "team_id": "SECTION_DIGITAL_COMMUNICATION"}}, content_type="application/json", **self.user)
        self.assertEqual(response.status_code, 201)
        request_id = response.json()["id"]
        path = f"/api/admin/vehicle-requests/{request_id}/decision/"
        self.assertEqual(self.client.post(path, {"decision": "APPROVED"}, content_type="application/json", **self.user).status_code, 403)
        self.assertEqual(self.client.post(path, {"decision": "APPROVED"}, content_type="application/json", **self.admin).status_code, 200)
        self.assertEqual(self.client.post(path, {"decision": "APPROVED"}, content_type="application/json", **self.admin).status_code, 409)
        vehicle = next(v for v in self.client.get("/api/vehicles/", **self.user).json() if v["plate_number"] == "TEST-123")
        response = self.client.post("/api/vehicle-requests/", {"request_type": "DELETE", "vehicle_id": vehicle["id"]}, content_type="application/json", **self.user)
        path = f"/api/admin/vehicle-requests/{response.json()['id']}/decision/"
        self.assertEqual(self.client.post(path, {"decision": "APPROVED"}, content_type="application/json", **self.admin).status_code, 200)
        self.assertEqual(self.client.get(f"/api/vehicles/{vehicle['id']}/", **self.user).status_code, 404)

    def test_rejection_requires_reason_and_preserves_vehicle_list(self):
        before = self.client.get("/api/vehicles/", **self.admin).json()
        response = self.client.post("/api/vehicle-requests/", {"request_type": "DELETE", "vehicle_id": "V001"}, content_type="application/json", **self.user)
        path = f"/api/admin/vehicle-requests/{response.json()['id']}/decision/"
        self.assertEqual(self.client.post(path, {"decision": "REJECTED"}, content_type="application/json", **self.admin).status_code, 400)
        self.assertEqual(self.client.post(path, {"decision": "REJECTED", "rejection_reason": "Test reason"}, content_type="application/json", **self.admin).status_code, 200)
        self.assertEqual(self.client.get("/api/vehicles/", **self.admin).json(), before)

    def test_camera_manifest_uses_project_offsets_and_exact_file(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        video = Path(directory.name) / "configured.mp4"
        video.write_bytes(b"0123456789")
        camera = SimpleNamespace(camera_id="cam01", video=video, fps=30, offset_seconds=.3)
        registry = SimpleNamespace(cameras=[camera], bev_map=Path(directory.name) / "missing.png")
        with patch.object(project_media, "registry", return_value=registry):
            manifest = self.client.get("/api/admin/media/", **self.admin).json()
            self.assertEqual(manifest["cameras"][0]["offset_seconds"], .3)
            self.assertEqual(manifest["cameras"][0]["id"], "cam01")
            response = self.client.get("/api" + manifest["cameras"][0]["url"], HTTP_RANGE="bytes=2-4", **self.admin)
            try:
                self.assertEqual(response.status_code, 206)
                self.assertEqual(b"".join(response.streaming_content), b"234")
            finally:
                response.close()
            self.assertEqual(self.client.get("/api/admin/media/cctv/cam01/other.mp4", **self.admin).status_code, 404)
