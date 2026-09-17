"""Validate real configured cameras and YOLO without starting another web server."""
import base64
import os
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
import cv2
import numpy as np
from vision.main import live


def main():
    try:
        live.get(retry=True)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            result = live.get()
            if result["status"] == "error":
                raise RuntimeError(result["error"])
            if result["sequence"] >= 2:
                assert result["cameras"]
                for camera in result["cameras"]:
                    jpeg = base64.b64decode(camera["image"].split(",", 1)[1])
                    frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
                    assert frame is not None
                    assert sum(camera["counts"].values()) == len(camera["detections"])
                print(f"PASS: {len(result['cameras'])} synchronized CCTV cameras, real YOLO inference, JPEG frames; {result['fps']} FPS")
                return
            time.sleep(.25)
        raise TimeoutError("Live inference did not produce two batches within 90 seconds")
    finally:
        live.close()


if __name__ == "__main__":
    main()
