import os
from pathlib import Path
import sys
from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
import numpy as np
from vision.live import LiveDetection, render_cameras
from src.tracking import DetectedVehicle
from vision.main import app
from fastapi.testclient import TestClient


class LiveTests(unittest.TestCase):
    def test_labels_counts_and_rendering(self):
        frame = np.zeros((80, 100, 3), dtype=np.uint8)
        results = render_cameras([SimpleNamespace(camera_id="cam01")], [frame], [[DetectedVehicle(7, .8, (10, 20, 50, 60))]])
        self.assertEqual(results[0]["counts"]["트럭"], 1)
        self.assertEqual(results[0]["detections"][0]["label"], "트럭")
        self.assertTrue(results[0]["image"].startswith("data:image/jpeg;base64,"))
        self.assertFalse(np.any(frame))

    def test_one_worker_shared_by_clients_and_released(self):
        camera = SimpleNamespace(camera_id="cam01", video=Path("test.mp4"), offset_seconds=.3)
        class Reader:
            start_ms, end_ms = 0, 10000
            closed = False
            def __init__(self, *args): pass
            def __enter__(self): return self
            def __exit__(self, *args): Reader.closed = True
            def read_at(self, timestamp): return [np.zeros((40, 50, 3), dtype=np.uint8)]
        service = LiveDetection()
        try:
            with patch("vision.live.registry", return_value=SimpleNamespace(cameras=[camera])), patch("vision.live.SynchronizedVideoReader", Reader) as reader, patch("vision.live.detect_batch", return_value=[[]]):
                service.get()
                worker = service.thread
                service.get()
                self.assertIs(service.thread, worker)
                deadline = time.monotonic() + 2
                while service.get()["status"] == "starting" and time.monotonic() < deadline: time.sleep(.01)
                self.assertEqual(service.get()["status"], "running")
                with service.lock:
                    service.last_access = time.monotonic() - 20
                worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(service.snapshot["status"], "idle")
                service.close()
                self.assertTrue(Reader.closed)
        finally: service.close()

    def test_missing_input_reports_error_and_requires_retry(self):
        service = LiveDetection()
        with patch("vision.live.registry", side_effect=FileNotFoundError("missing video")), patch("vision.live.logging.exception"):
            service.get()
            service.thread.join(2)
            worker = service.thread
            self.assertEqual(service.get()["status"], "error")
            self.assertIs(service.thread, worker)
            service.get(retry=True)
            self.assertIsNot(service.thread, worker)
            service.close()

    def test_live_endpoints_are_admin_only(self):
        client = TestClient(app)
        for user, code in [(None, 401), ({"role": "USER"}, 403)]:
            with patch("vision.auth.current_user", return_value=user):
                self.assertEqual(client.get("/api/live").status_code, code)
                self.assertEqual(client.post("/api/live/start").status_code, code)
