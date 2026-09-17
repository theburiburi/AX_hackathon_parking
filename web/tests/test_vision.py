import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()

import cv2
import numpy as np
from fastapi.testclient import TestClient
from vision import main
from vision.auth import require_admin
from vision import processor
from src.tracking import DetectedVehicle


class VisionTests(unittest.TestCase):
    def test_yolo_reuses_model_and_serializes_frame_observations(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        vehicle = DetectedVehicle(class_id=2, confidence=.9, bbox=(10, 20, 40, 60))
        with patch.object(processor, "_detector", None), patch("src.tracking.BatchVehicleDetector") as factory, \
                patch("pathlib.Path.is_file", return_value=True), patch.dict(os.environ, {"WEB_VISION_MODE": "yolo"}):
            factory.return_value.detect.return_value = [[vehicle]]
            output, first = processor.process_frame(frame, 0, 0)
            _, second = processor.process_frame(frame, 1, .1)
            factory.assert_called_once()
            self.assertEqual(factory.return_value.detect.call_count, 2)
            self.assertEqual(first["detections"][0]["bbox"], [10, 20, 40, 60])
            self.assertEqual(first["mode"], "yolo")
            self.assertEqual(second["timestamp_seconds"], .1)
            self.assertTrue(np.any(output != frame))
            self.assertFalse(np.any(frame))

    def test_upload_analysis_download_and_validation(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "input.avi"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"MJPG"), 10, (160, 120))
            self.assertTrue(writer.isOpened())
            for index in range(5):
                frame = np.zeros((120, 160, 3), dtype=np.uint8)
                cv2.rectangle(frame, (index * 3, 20), (60, 60), (255, 255, 255), -1)
                writer.write(frame)
            writer.release()
            main.app.dependency_overrides[require_admin] = lambda: {"role": "ADMIN"}
            self.addCleanup(main.app.dependency_overrides.clear)
            with patch.object(main, "DATA", folder), patch.dict(os.environ, {"WEB_VISION_MODE": "edges"}), TestClient(main.app) as client:
                self.assertEqual(client.post("/api/videos", files={"file": ("bad.txt", b"invalid")}).status_code, 400)
                self.assertEqual(client.post("/api/videos", files={"file": ("broken.mp4", b"invalid")}).status_code, 400)
                response = client.post("/api/videos", files={"file": ("sample.avi", source.read_bytes())})
                self.assertEqual(response.status_code, 202)
                path = response.json()["status_url"]
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    job = client.get(path).json()
                    if job["status"] in ("completed", "failed"):
                        break
                    time.sleep(.02)
                self.assertEqual(job["status"], "completed", job)
                analysis = [json.loads(line) for line in client.get(job["analysis_url"]).content.splitlines()]
                self.assertEqual(len(analysis), 5)
                self.assertGreater(analysis[0]["edge_pixels"], 0)
                self.assertTrue(client.get(job["preview_url"]).content.startswith(b"\xff\xd8"))
                result = folder / "result.avi"
                result.write_bytes(client.get(job["result_url"]).content)
                capture = cv2.VideoCapture(str(result))
                self.assertEqual(int(capture.get(cv2.CAP_PROP_FRAME_COUNT)), 5)
                capture.release()
                self.assertEqual(client.get(path + "/files/source.avi").status_code, 404)

    def test_vision_requires_admin(self):
        # No lifespan shutdown: the processing worker is exercised by the test above.
        client = TestClient(main.app)
        with patch("vision.auth.current_user", return_value=None):
            self.assertEqual(client.post("/api/videos", files={"file": ("x.avi", b"x")}).status_code, 401)
        with patch("vision.auth.current_user", return_value={"role": "USER"}):
            self.assertEqual(client.get("/api/jobs/00000000-0000-0000-0000-000000000000").status_code, 403)
