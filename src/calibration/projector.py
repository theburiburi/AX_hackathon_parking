from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[2]


class CameraProjector:
    """
    Camera image coordinate -> BEV coordinate projector.

    Modes
    -----
    homography:
        기존 단일 Homography만 사용.

    nonlinear:
        Homography를 기본값으로 사용하고,
        calibration point에서 측정된 residual을
        IDW(Inverse Distance Weighting) 방식으로
        부드럽게 보정한다.
    """

    def __init__(
        self,
        camera_id: str,
        calibration_dir: str | Path = "config/calibration",
        mode: str = "nonlinear",
        power: float = 2.0,
        radius: float = 500.0,
        min_neighbors: int = 3,
        exact_threshold: float = 3.0,
    ):
        self.camera_id = camera_id

        self.mode = mode

        self.power = float(
            power
        )

        self.radius = float(
            radius
        )

        self.min_neighbors = int(
            min_neighbors
        )

        self.exact_threshold = float(
            exact_threshold
        )

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

        (
            self.homography,
            self.image_points,
            self.bev_points,
        ) = self._load_calibration()

        self.homography_predictions = (
            self._project_homography_batch(
                self.image_points
            )
        )

        self.residuals = (
            self.bev_points
            -
            self.homography_predictions
        )

        self._print_info()

    def _load_calibration(
        self,
    ) -> tuple[
        np.ndarray,
        np.ndarray,
        np.ndarray,
    ]:

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

        homography_data = (
            data.get(
                "homography"
            )
        )

        if homography_data is None:

            raise RuntimeError(
                f"{self.camera_id}: "
                "Homography is missing."
            )

        homography = np.array(
            homography_data,
            dtype=np.float64,
        )

        if homography.shape != (
            3,
            3,
        ):

            raise RuntimeError(
                f"{self.camera_id}: "
                "Invalid homography matrix."
            )

        points = data.get(
            "points",
            [],
        )

        if len(points) < 4:

            raise RuntimeError(
                f"{self.camera_id}: "
                "At least 4 calibration points "
                "are required."
            )

        image_points = np.array(
            [
                point["image"]
                for point
                in points
            ],
            dtype=np.float64,
        )

        bev_points = np.array(
            [
                point["bev"]
                for point
                in points
            ],
            dtype=np.float64,
        )

        return (
            homography,
            image_points,
            bev_points,
        )

    def _project_homography_batch(
        self,
        points: np.ndarray,
    ) -> np.ndarray:

        if len(points) == 0:

            return np.empty(
                (
                    0,
                    2,
                ),
                dtype=np.float64,
            )

        src = np.asarray(
            points,
            dtype=np.float32,
        ).reshape(
            -1,
            1,
            2,
        )

        projected = (
            cv2.perspectiveTransform(
                src,
                self.homography,
            )
            .reshape(
                -1,
                2,
            )
            .astype(
                np.float64
            )
        )

        return projected

    def project_homography(
        self,
        x: float,
        y: float,
    ) -> tuple[
        float,
        float,
    ]:

        point = np.array(
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

        projected = (
            cv2.perspectiveTransform(
                point,
                self.homography,
            )[0][0]
        )

        return (
            float(
                projected[0]
            ),
            float(
                projected[1]
            ),
        )

    def _calculate_residual(
        self,
        x: float,
        y: float,
    ) -> np.ndarray:

        query = np.array(
            [
                float(x),
                float(y),
            ],
            dtype=np.float64,
        )

        differences = (
            self.image_points
            -
            query
        )

        distances = np.linalg.norm(
            differences,
            axis=1,
        )

        # calibration point 그 자체를 조회한 경우
        # 해당 지점의 residual을 그대로 사용한다.
        nearest_index = int(
            np.argmin(
                distances
            )
        )

        nearest_distance = float(
            distances[
                nearest_index
            ]
        )

        if (
            nearest_distance
            <=
            self.exact_threshold
        ):

            return (
                self.residuals[
                    nearest_index
                ]
                .copy()
            )

        # radius 안의 점만 우선 사용한다.
        neighbor_indices = np.where(
            distances
            <=
            self.radius
        )[0]

        # 주변 점이 너무 적으면
        # 가장 가까운 min_neighbors개를 사용한다.
        if (
            len(
                neighbor_indices
            )
            <
            self.min_neighbors
        ):

            sorted_indices = np.argsort(
                distances
            )

            neighbor_count = min(
                self.min_neighbors,
                len(
                    sorted_indices
                ),
            )

            neighbor_indices = (
                sorted_indices[
                    :neighbor_count
                ]
            )

        neighbor_distances = (
            distances[
                neighbor_indices
            ]
        )

        neighbor_residuals = (
            self.residuals[
                neighbor_indices
            ]
        )

        safe_distances = np.maximum(
            neighbor_distances,
            1.0,
        )

        weights = (
            1.0
            /
            np.power(
                safe_distances,
                self.power,
            )
        )

        # radius 경계에서 보정값이 갑자기
        # 끊기지 않도록 거리 감쇠를 추가한다.
        if self.radius > 0:

            taper = (
                1.0
                -
                np.clip(
                    neighbor_distances
                    /
                    self.radius,
                    0.0,
                    1.0,
                )
            )

            taper = (
                taper
                *
                taper
            )

            weights *= np.maximum(
                taper,
                0.05,
            )

        weight_sum = float(
            np.sum(
                weights
            )
        )

        if weight_sum <= 0:

            return np.zeros(
                2,
                dtype=np.float64,
            )

        correction = np.sum(
            neighbor_residuals
            *
            weights[:, None],
            axis=0,
        ) / weight_sum

        return correction

    def project_nonlinear(
        self,
        x: float,
        y: float,
    ) -> tuple[
        float,
        float,
    ]:

        homography_point = np.array(
            self.project_homography(
                x,
                y,
            ),
            dtype=np.float64,
        )

        correction = (
            self._calculate_residual(
                x,
                y,
            )
        )

        corrected = (
            homography_point
            +
            correction
        )

        return (
            float(
                corrected[0]
            ),
            float(
                corrected[1]
            ),
        )

    def project(
        self,
        x: float,
        y: float,
    ) -> tuple[
        float,
        float,
    ]:

        if self.mode == "homography":

            return (
                self.project_homography(
                    x,
                    y,
                )
            )

        if self.mode == "nonlinear":

            return (
                self.project_nonlinear(
                    x,
                    y,
                )
            )

        raise ValueError(
            f"Unknown projection mode: "
            f"{self.mode}"
        )

    def get_control_point_errors(
        self,
    ) -> dict:

        homography_errors = []

        nonlinear_errors = []

        for (
            image_point,
            actual_bev,
        ) in zip(
            self.image_points,
            self.bev_points,
        ):

            x = float(
                image_point[0]
            )

            y = float(
                image_point[1]
            )

            homography_prediction = (
                np.array(
                    self.project_homography(
                        x,
                        y,
                    )
                )
            )

            nonlinear_prediction = (
                np.array(
                    self.project_nonlinear(
                        x,
                        y,
                    )
                )
            )

            homography_error = float(
                np.linalg.norm(
                    homography_prediction
                    -
                    actual_bev
                )
            )

            nonlinear_error = float(
                np.linalg.norm(
                    nonlinear_prediction
                    -
                    actual_bev
                )
            )

            homography_errors.append(
                homography_error
            )

            nonlinear_errors.append(
                nonlinear_error
            )

        return {
            "homography": {
                "mean": float(
                    np.mean(
                        homography_errors
                    )
                ),
                "median": float(
                    np.median(
                        homography_errors
                    )
                ),
                "max": float(
                    np.max(
                        homography_errors
                    )
                ),
            },

            "nonlinear": {
                "mean": float(
                    np.mean(
                        nonlinear_errors
                    )
                ),
                "median": float(
                    np.median(
                        nonlinear_errors
                    )
                ),
                "max": float(
                    np.max(
                        nonlinear_errors
                    )
                ),
            },
        }

    def _print_info(
        self,
    ) -> None:

        residual_lengths = (
            np.linalg.norm(
                self.residuals,
                axis=1,
            )
        )

        print()
        print(
            "======================================"
        )
        print(
            "Camera Projector"
        )
        print(
            "======================================"
        )

        print(
            f"Camera        : "
            f"{self.camera_id}"
        )

        print(
            f"Mode          : "
            f"{self.mode}"
        )

        print(
            f"Control points: "
            f"{len(self.image_points)}"
        )

        print(
            f"IDW power     : "
            f"{self.power:.2f}"
        )

        print(
            f"IDW radius    : "
            f"{self.radius:.1f} px"
        )

        print(
            f"Residual mean : "
            f"{np.mean(residual_lengths):.2f} px"
        )

        print(
            f"Residual max  : "
            f"{np.max(residual_lengths):.2f} px"
        )

        print(
            "======================================"
        )
        print()