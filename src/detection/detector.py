from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
import yaml
from ultralytics import YOLO


ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Detection:
    class_id: int
    class_name: str
    confidence: float

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def bbox(self) -> dict[str, float]:
        return {
            "x1": self.x1,
            "y1": self.y1,
            "x2": self.x2,
            "y2": self.y2,
        }


class VehicleDetector:
    def __init__(
        self,
        config_path: str | Path,
    ):
        self.config_path = Path(
            config_path
        )

        if not self.config_path.is_absolute():
            self.config_path = (
                ROOT / self.config_path
            )

        self.config = self._load_config()

        model_config = self.config["model"]

        inference_config = self.config[
            "inference"
        ]

        class_config = self.config[
            "classes"
        ]

        self.weights = model_config[
            "weights"
        ]

        self.device = model_config.get(
            "device",
            0,
        )

        self.imgsz = int(
            inference_config.get(
                "imgsz",
                640,
            )
        )

        self.conf = float(
            inference_config.get(
                "conf",
                0.25,
            )
        )

        self.iou = float(
            inference_config.get(
                "iou",
                0.70,
            )
        )

        self.half = bool(
            inference_config.get(
                "half",
                True,
            )
        )

        self.batch_size = int(
            inference_config.get(
                "batch_size",
                1,
            )
        )

        self.target_class_names = set(
            class_config.get(
                "names",
                [],
            )
        )

        self._validate_device()

        print(
            f"Loading YOLO model: "
            f"{self.weights}"
        )

        self.model = YOLO(
            self.weights
        )

        self.class_ids = (
            self._resolve_class_ids()
        )

        print(
            f"Target classes: "
            f"{sorted(self.target_class_names)}"
        )

        print(
            f"YOLO batch size: "
            f"{self.batch_size}"
        )

    def _load_config(
        self,
    ) -> dict[str, Any]:

        if not self.config_path.exists():

            raise FileNotFoundError(
                f"Detection config not found: "
                f"{self.config_path}"
            )

        with self.config_path.open(
            "r",
            encoding="utf-8",
        ) as file:

            return yaml.safe_load(
                file
            )

    def _validate_device(
        self,
    ) -> None:

        if not isinstance(
            self.device,
            int,
        ):
            raise ValueError(
                "현재 프로젝트는 CUDA GPU 사용을 "
                "전제로 합니다. "
                "device는 GPU 번호여야 합니다."
            )

        if not torch.cuda.is_available():

            raise RuntimeError(
                "CUDA GPU를 사용할 수 없습니다.\n"
                "torch.cuda.is_available() == False"
            )

        gpu_count = (
            torch.cuda.device_count()
        )

        if (
            self.device
            >=
            gpu_count
        ):

            raise RuntimeError(
                f"GPU device {self.device}가 없습니다. "
                f"사용 가능한 GPU 수: {gpu_count}"
            )

        gpu_name = (
            torch.cuda.get_device_name(
                self.device
            )
        )

        total_memory = (
            torch.cuda.get_device_properties(
                self.device
            ).total_memory
            /
            1024**3
        )

        print(
            f"CUDA device: "
            f"{self.device}"
        )

        print(
            f"GPU: "
            f"{gpu_name}"
        )

        print(
            f"VRAM: "
            f"{total_memory:.2f} GB"
        )

    def _resolve_class_ids(
        self,
    ) -> list[int]:

        names = self.model.names

        class_ids = []

        for class_id, name in names.items():

            if (
                name
                in
                self.target_class_names
            ):

                class_ids.append(
                    int(class_id)
                )

        resolved_names = {
            names[class_id]
            for class_id
            in class_ids
        }

        missing = (
            self.target_class_names
            -
            resolved_names
        )

        if missing:

            raise ValueError(
                "YOLO 모델에 없는 클래스가 있습니다: "
                f"{sorted(missing)}"
            )

        return class_ids

    def _convert_result(
        self,
        result,
    ) -> list[Detection]:

        boxes = result.boxes

        if boxes is None:

            return []

        detections = []

        for box in boxes:

            class_id = int(
                box.cls[0].item()
            )

            confidence = float(
                box.conf[0].item()
            )

            x1, y1, x2, y2 = (
                box.xyxy[0]
                .detach()
                .cpu()
                .tolist()
            )

            detections.append(
                Detection(
                    class_id=class_id,
                    class_name=self.model.names[
                        class_id
                    ],
                    confidence=confidence,
                    x1=float(x1),
                    y1=float(y1),
                    x2=float(x2),
                    y2=float(y2),
                )
            )

        return detections

    def detect(
        self,
        frame,
    ) -> list[Detection]:

        results = self.model.predict(
            source=frame,
            imgsz=self.imgsz,
            conf=self.conf,
            iou=self.iou,
            classes=self.class_ids,
            device=self.device,
            half=self.half,
            verbose=False,
        )

        if not results:

            return []

        return self._convert_result(
            results[0]
        )

    def detect_batch(
        self,
        frames: list,
    ) -> list[list[Detection]]:

        if not frames:

            return []

        all_detections = []

        for start in range(
            0,
            len(frames),
            self.batch_size,
        ):

            batch = frames[
                start:
                start + self.batch_size
            ]

            results = self.model.predict(
                source=batch,
                imgsz=self.imgsz,
                conf=self.conf,
                iou=self.iou,
                classes=self.class_ids,
                device=self.device,
                half=self.half,
                verbose=False,
            )

            for result in results:

                all_detections.append(
                    self._convert_result(
                        result
                    )
                )

        return all_detections