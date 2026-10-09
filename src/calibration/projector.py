from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from .mapping import CalibrationMapping


ROOT = Path(__file__).resolve().parents[2]


class CameraProjector:
    """
    Camera image coordinate -> BEV coordinate projector.

    config/calibration/camXX.json 안의 "mapping"(Homography + TPS)이
    있으면 사용하고, 없거나 읽을 수 없으면 기존 "homography"만 사용한다.
    """

    def __init__(
        self,
        camera_id: str,
        calibration_dir: str | Path = "config/calibration",
    ):
        self.camera_id = camera_id

        calibration_dir = Path(
            calibration_dir
        )

        if not calibration_dir.is_absolute():
            calibration_dir = (
                ROOT
                /
                calibration_dir
            )

        self.calibration_path = (
            calibration_dir
            /
            f"{camera_id}.json"
        )

        self.mapping: (
            CalibrationMapping
            | None
        ) = None

        self.homography = (
            self._load_homography()
        )

    def _load_homography(
        self,
    ) -> np.ndarray:

        if not self.calibration_path.exists():

            raise FileNotFoundError(
                "Calibration file not found: "
                f"{self.calibration_path}"
            )

        with self.calibration_path.open(
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(
                file
            )

        homography = data.get(
            "homography"
        )

        if homography is None:

            raise RuntimeError(
                f"{self.camera_id}: "
                "homography is missing."
            )

        matrix = np.asarray(
            homography,
            dtype=np.float64,
        )

        if matrix.shape != (
            3,
            3,
        ):

            raise RuntimeError(
                f"{self.camera_id}: "
                "invalid homography shape "
                f"{matrix.shape}"
            )

        if not np.all(
            np.isfinite(
                matrix
            )
        ):

            raise RuntimeError(
                f"{self.camera_id}: "
                "homography contains "
                "invalid values."
            )

        mapping_data = data.get(
            "mapping"
        )

        if mapping_data is not None:

            try:

                self.mapping = (
                    CalibrationMapping.from_dict(
                        mapping_data
                    )
                )

            except Exception as error:

                print(
                    f"[CameraProjector] {self.camera_id}: "
                    f"invalid mapping, "
                    f"fallback to homography ({error})"
                )

                self.mapping = None

        return matrix

    @property
    def mapping_type(
        self,
    ) -> str:

        if self.mapping is not None:
            return self.mapping.type

        return "homography"

    def project(
        self,
        x: float,
        y: float,
    ) -> tuple[
        float,
        float,
    ]:

        if self.mapping is not None:

            return self.mapping.project(
                x,
                y,
            )

        src = np.array(
            [
                [
                    [
                        float(x),
                        float(y),
                    ]
                ]
            ],
            dtype=np.float32,
        )

        dst = cv2.perspectiveTransform(
            src,
            self.homography,
        )

        bev_x = float(
            dst[
                0,
                0,
                0,
            ]
        )

        bev_y = float(
            dst[
                0,
                0,
                1,
            ]
        )

        return (
            bev_x,
            bev_y,
        )

    def project_bbox_bottom_center(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
    ) -> tuple[
        float,
        float,
    ]:

        ground_x = (
            float(x1)
            +
            float(x2)
        ) / 2.0

        ground_y = float(
            y2
        )

        return self.project(
            ground_x,
            ground_y,
        )