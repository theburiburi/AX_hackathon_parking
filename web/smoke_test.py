"""실행 중인 로컬 서버에 합성 영상을 업로드하여 실제 처리 경로를 검사합니다."""
import json
import os
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import cv2
import numpy as np

BASE = os.environ.get("VISION_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
TOKEN = ""


def fetch(path):
    with urlopen(Request(BASE + path, headers={"Authorization": "Bearer " + TOKEN}), timeout=10) as response:
        return response.read()


def upload(name, payload):
    boundary = "VisionSmokeTestBoundary"
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
    body += payload + f"\r\n--{boundary}--\r\n".encode()
    request = Request(BASE + "/api/videos", data=body,
                      headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Authorization": "Bearer " + TOKEN})
    with urlopen(request, timeout=30) as response:
        assert response.status == 202
        return json.load(response)


def main():
    global TOKEN
    password = os.environ.get("WEB_DEMO_PASSWORD")
    if not password:
        password_file = Path(__file__).resolve().parent / "backend/data/demo-password.txt"
        if not password_file.exists():
            raise RuntimeError("Set WEB_DEMO_PASSWORD to the initialized admin password.")
        password = password_file.read_text(encoding="utf-8").strip()
    parking = os.environ.get("PARKING_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    request = Request(parking + "/api/auth/login/", data=json.dumps({"username": "admin", "password": password}).encode(),
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=10) as response:
        TOKEN = json.load(response)["token"]
    assert json.loads(fetch("/api/health"))["status"] == "ok"
    assert b"<html" in fetch("/")
    assert "/api/videos" in json.loads(fetch("/openapi.json"))["paths"]
    for filename in ("bad.txt", "broken.mp4"):
        try:
            upload(filename, b"not a video")
        except HTTPError as error:
            assert error.code == 400
        else:
            raise AssertionError("Invalid upload accepted")
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "sample.avi"
        writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"MJPG"), 10, (160, 120))
        assert writer.isOpened()
        for index in range(20):
            frame = np.zeros((120, 160, 3), dtype=np.uint8)
            cv2.rectangle(frame, (index * 3, 20), (index * 3 + 30, 60), (255, 255, 255), -1)
            writer.write(frame)
        writer.release()
        task = upload("sample.avi", source.read_bytes())
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            job = json.loads(fetch(task["status_url"]))
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.2)
        assert job["status"] == "completed", job
        assert job["processed_frames"] == 20
        analysis = [json.loads(line) for line in fetch(job["analysis_url"]).splitlines()]
        assert len(analysis) == 20 and analysis[0]["edge_pixels"] > 0
        assert fetch(job["preview_url"]).startswith(b"\xff\xd8")
        result = Path(tmp) / "result.avi"
        result.write_bytes(fetch(job["result_url"]))
        capture = cv2.VideoCapture(str(result))
        frames = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            assert frame.shape == (120, 160, 3)
            frames += 1
        capture.release()
        assert frames == 20
    print("PASS: health, UI response, API schema, invalid uploads, 20-frame processing, preview, analysis, output decoding")


if __name__ == "__main__":
    main()
