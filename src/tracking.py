"""Vehicle observations, YOLO detection and local tracking."""

from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class TrackedVehicle:
    track_id: int
    class_id: int
    confidence: float
    bbox: tuple[int, int, int, int]

    @property
    def ground_point(self) -> tuple[float, float]:
        """Bounding-box bottom center in CCTV pixel coordinates."""
        x1, _y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2.0, float(y2))


@dataclass(frozen=True)
class DetectedVehicle:
    class_id: int
    confidence: float
    bbox: tuple[int, int, int, int]

    @property
    def ground_point(self) -> tuple[float, float]:
        x1, _y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2.0, float(y2))


def select_device(configured_device: str | int) -> str | int:
    """Choose CUDA device 0 when available, otherwise CPU."""
    if configured_device != "auto":
        return configured_device

    import torch

    return 0 if torch.cuda.is_available() else "cpu"


class VehicleDetectorTracker:
    def __init__(
        self,
        model_name: str,
        confidence: float,
        iou: float,
        vehicle_classes: Sequence[int],
        tracker: str,
        device: str | int = "auto",
    ) -> None:
        # Import here so geometry/config tests do not require model startup.
        from ultralytics import YOLO

        self.model = YOLO(model_name)
        self.confidence = confidence
        self.iou = iou
        self.vehicle_classes = list(vehicle_classes)
        self.tracker = tracker
        self.device = select_device(device)

    def track(self, frame: np.ndarray) -> list[TrackedVehicle]:
        """Detect and track vehicles in one BGR frame."""
        results = self.model.track(
            source=frame,
            persist=True,
            tracker=self.tracker,
            classes=self.vehicle_classes,
            conf=self.confidence,
            iou=self.iou,
            device=self.device,
            verbose=False,
        )

        if not results or results[0].boxes is None:
            return []

        boxes = results[0].boxes
        if boxes.id is None:
            return []

        xyxy = boxes.xyxy.detach().cpu().numpy()
        ids = boxes.id.detach().cpu().numpy().astype(int)
        classes = boxes.cls.detach().cpu().numpy().astype(int)
        confidences = boxes.conf.detach().cpu().numpy()

        vehicles: list[TrackedVehicle] = []
        for box, track_id, class_id, confidence in zip(
            xyxy, ids, classes, confidences
        ):
            x1, y1, x2, y2 = (int(round(value)) for value in box)
            vehicles.append(
                TrackedVehicle(
                    track_id=int(track_id),
                    class_id=int(class_id),
                    confidence=float(confidence),
                    bbox=(x1, y1, x2, y2),
                )
            )
        return vehicles


class BatchVehicleDetector:
    """One YOLO model performing a batch inference over multiple cameras."""

    def __init__(
        self,
        model_name: str,
        confidence: float,
        iou: float,
        vehicle_classes: Sequence[int],
        image_size: int = 640,
        device: str | int = "auto",
    ) -> None:
        from ultralytics import YOLO

        self.model = YOLO(model_name)
        self.confidence = confidence
        self.iou = iou
        self.vehicle_classes = list(vehicle_classes)
        self.image_size = image_size
        self.device = select_device(device)

    def detect(self, frames: Sequence[np.ndarray]) -> list[list[DetectedVehicle]]:
        if not frames:
            return []
        results = self.model.predict(
            source=list(frames),
            classes=self.vehicle_classes,
            conf=self.confidence,
            iou=self.iou,
            imgsz=self.image_size,
            device=self.device,
            verbose=False,
        )
        batches: list[list[DetectedVehicle]] = []
        for result in results:
            vehicles: list[DetectedVehicle] = []
            boxes = result.boxes
            if boxes is not None:
                xyxy = boxes.xyxy.detach().cpu().numpy()
                classes = boxes.cls.detach().cpu().numpy().astype(int)
                confidences = boxes.conf.detach().cpu().numpy()
                for box, class_id, confidence in zip(xyxy, classes, confidences):
                    x1, y1, x2, y2 = (int(round(value)) for value in box)
                    vehicles.append(
                        DetectedVehicle(
                            class_id=int(class_id),
                            confidence=float(confidence),
                            bbox=(x1, y1, x2, y2),
                        )
                    )
            batches.append(vehicles)
        return batches
