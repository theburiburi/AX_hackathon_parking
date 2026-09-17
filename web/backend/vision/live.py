"""Shared continuous inference over the configured recorded CCTV cameras."""
import base64
import logging
from threading import Event, Lock, Thread
import time

import cv2

from tracking.project_media import registry
from src.playback.reader import SynchronizedVideoReader
from .processor import detect_batch

LABELS = {2: ("car", "승용차"), 5: ("bus", "버스"), 7: ("truck", "트럭")}


def render_cameras(cameras, frames, batches):
    result = []
    for camera, frame, detections in zip(cameras, frames, batches):
        output = frame.copy()
        observations = []
        counts = {"승용차": 0, "버스": 0, "트럭": 0}
        for index, vehicle in enumerate(detections, 1):
            english, label = LABELS.get(vehicle.class_id, (str(vehicle.class_id), str(vehicle.class_id)))
            counts[label] = counts.get(label, 0) + 1
            x1, y1, x2, y2 = vehicle.bbox
            color = {2: (60, 220, 60), 5: (255, 180, 40), 7: (30, 160, 255)}.get(vehicle.class_id, (60, 220, 60))
            cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)
            cv2.putText(output, f"{english} {vehicle.confidence:.0%}", (x1, max(20, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, .7, color, 2)
            observations.append({"detection_id": index, "class_id": vehicle.class_id, "label": label,
                                 "confidence": vehicle.confidence, "bbox": list(vehicle.bbox)})
        height, width = output.shape[:2]
        if width > 640:
            output = cv2.resize(output, (640, max(1, round(height * 640 / width))))
        ok, jpeg = cv2.imencode(".jpg", output, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ok:
            raise ValueError(f"Failed to encode camera {camera.camera_id}")
        result.append({"id": camera.camera_id, "image": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode(),
                       "detections": observations, "counts": counts})
    return result


class LiveDetection:
    def __init__(self, idle_seconds=12):
        self.lock = Lock()
        self.stop_event = Event()
        self.thread = None
        self.last_access = 0
        self.idle_seconds = idle_seconds
        self.snapshot = {"status": "idle", "cameras": [], "sequence": 0}

    def get(self, retry=False):
        with self.lock:
            self.last_access = time.monotonic()
            if (self.thread is None or not self.thread.is_alive()) and (retry or self.snapshot["status"] != "error"):
                self.stop_event.clear()
                self.snapshot = {"status": "starting", "cameras": [], "sequence": 0}
                self.thread = Thread(target=self.run, name="live-yolo", daemon=True)
                self.thread.start()
            return dict(self.snapshot)

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=10)

    def run(self):
        try:
            config = registry()
            with SynchronizedVideoReader([c.video for c in config.cameras], [c.offset_seconds for c in config.cameras]) as reader:
                anchor = time.monotonic()
                sequence = 0
                while not self.stop_event.is_set():
                    started = time.monotonic()
                    with self.lock:
                        if started - self.last_access > self.idle_seconds:
                            break
                    timestamp = reader.start_ms + ((started - anchor) * 1000) % (reader.end_ms - reader.start_ms)
                    frames = reader.read_at(timestamp)
                    batches = detect_batch(frames)
                    cameras = render_cameras(config.cameras, frames, batches)
                    elapsed = time.monotonic() - started
                    sequence += 1
                    with self.lock:
                        self.snapshot = {"status": "running", "cameras": cameras, "sequence": sequence,
                            "timestamp_seconds": round(timestamp / 1000, 2), "processing_ms": round(elapsed * 1000),
                            "fps": round(1 / max(.2, elapsed), 1)}
                    self.stop_event.wait(max(0, .2 - elapsed))
            with self.lock:
                self.snapshot = {**self.snapshot, "status": "idle"}
        except Exception as error:
            logging.exception("Live detection failed")
            with self.lock:
                self.snapshot = {"status": "error", "error": str(error), "cameras": [], "sequence": 0}
