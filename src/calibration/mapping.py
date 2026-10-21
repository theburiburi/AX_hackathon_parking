from __future__ import annotations

import math

import cv2
import numpy as np


"""
Camera image coordinate -> BEV coordinate 비선형 mapping.

BEV(p) = Homography(p) + w(p) * TPS_residual(p)

- Homography : 모든 사용자 점으로 최소자승(RANSAC 없음) 계산한
               global perspective.
- TPS        : Homography로 설명되지 않는 잔차를
               Thin Plate Spline으로 정확히 보간한다.
               사용자 점에서는 지정한 BEV 위치를 그대로 통과한다.
- w(p)       : calibration point convex hull 안에서는 1,
               hull 밖에서는 거리에 따라 연속적으로 0에 가까워진다.
               (hull 경계에서 위치가 튀지 않음)

사용자가 찍은 점은 모두 정답으로 간주하며,
outlier 판정 / 제거 / 자동 수정은 하지 않는다.
"""


MAPPING_TYPE = "homography_tps"

# Homography만으로 4점은 정확히 맞으므로
# TPS 잔차 보정은 5점 이상부터 의미가 있다.
MIN_TPS_POINTS = 5

# hull 밖에서 TPS 보정이 줄어드는 거리 스케일(px).
# 칸 폭 FADE_REFERENCE_WIDTH(640px, 1920x1080 모자이크) 기준 값이며,
# 해상도가 다른 영상은 fade_px_for_width()로 칸 폭에 비례해 맞춘다.
DEFAULT_FADE_PX = 200.0

FADE_REFERENCE_WIDTH = 640.0


def fade_px_for_width(
    image_width: float,
) -> float:
    """
    칸 폭에 비례한 fade 거리. 해상도만 다른 영상에서 같은 mapping이 되도록 한다.
    """

    return DEFAULT_FADE_PX * float(image_width) / FADE_REFERENCE_WIDTH


# =========================================================
# Homography
# =========================================================


def fit_homography(
    image_points: np.ndarray,
    bev_points: np.ndarray,
) -> np.ndarray | None:
    """
    모든 점을 사용하는 최소자승 Homography.
    RANSAC을 쓰지 않으므로 사용자 점을 버리지 않는다.
    """

    if len(image_points) < 4:
        return None

    homography, _ = cv2.findHomography(
        np.asarray(image_points, dtype=np.float64),
        np.asarray(bev_points, dtype=np.float64),
        0,
    )

    if (
        homography is None
        or
        not np.all(np.isfinite(homography))
    ):
        return None

    return homography


def apply_homography(
    homography: np.ndarray,
    points: np.ndarray,
) -> np.ndarray:

    points = np.asarray(
        points,
        dtype=np.float64,
    ).reshape(-1, 1, 2)

    return cv2.perspectiveTransform(
        points,
        homography,
    ).reshape(-1, 2)


# =========================================================
# TPS
# =========================================================


def _tps_kernel(
    squared_distance: np.ndarray,
) -> np.ndarray:
    """
    U(r) = r^2 log(r^2), U(0) = 0
    """

    result = np.zeros_like(
        squared_distance
    )

    mask = squared_distance > 0.0

    result[mask] = (
        squared_distance[mask]
        *
        np.log(squared_distance[mask])
    )

    return result


def _hull_distance(
    hull: np.ndarray,
    point: tuple[float, float],
) -> float:
    """
    hull 안(경계 포함)이면 0, 밖이면 hull까지의 거리(px).
    """

    signed = cv2.pointPolygonTest(
        hull.reshape(-1, 1, 2).astype(np.float32),
        (
            float(point[0]),
            float(point[1]),
        ),
        True,
    )

    return max(
        0.0,
        -float(signed),
    )


class CalibrationMapping:
    """
    Homography + TPS residual mapping.

    from_points() 로 계산하고
    to_dict() / from_dict() 로 calibration JSON에 저장/복원한다.
    """

    def __init__(
        self,
        homography: np.ndarray,
        control_points: np.ndarray | None = None,
        weights: np.ndarray | None = None,
        affine: np.ndarray | None = None,
        norm_mean: np.ndarray | None = None,
        norm_scale: float = 1.0,
        hull: np.ndarray | None = None,
        fade_px: float = DEFAULT_FADE_PX,
    ):
        self.homography = np.asarray(
            homography,
            dtype=np.float64,
        )

        self.control_points = control_points
        self.weights = weights
        self.affine = affine
        self.norm_mean = norm_mean
        self.norm_scale = float(norm_scale)
        self.hull = hull
        self.fade_px = float(fade_px)

    # -----------------------------------------------------
    # Build
    # -----------------------------------------------------

    @property
    def has_tps(
        self,
    ) -> bool:

        return (
            self.control_points is not None
            and
            self.weights is not None
            and
            self.affine is not None
            and
            self.hull is not None
        )

    @property
    def type(
        self,
    ) -> str:

        if self.has_tps:
            return MAPPING_TYPE

        return "homography"

    @classmethod
    def from_points(
        cls,
        image_points,
        bev_points,
        fade_px: float = DEFAULT_FADE_PX,
    ) -> CalibrationMapping | None:
        """
        점이 4개 미만이거나 Homography 계산이 불가능하면 None.
        TPS를 만들 수 없으면 Homography 단독 mapping을 반환한다.
        """

        image_points = np.asarray(
            image_points,
            dtype=np.float64,
        ).reshape(-1, 2)

        bev_points = np.asarray(
            bev_points,
            dtype=np.float64,
        ).reshape(-1, 2)

        homography = fit_homography(
            image_points,
            bev_points,
        )

        if homography is None:
            return None

        mapping = cls(
            homography=homography,
            fade_px=fade_px,
        )

        if len(image_points) < MIN_TPS_POINTS:
            return mapping

        hull = cv2.convexHull(
            image_points.astype(np.float32)
        ).reshape(-1, 2).astype(np.float64)

        # 점들이 거의 일직선이면 TPS를 구성할 수 없다.
        if (
            len(hull) < 3
            or
            cv2.contourArea(hull.astype(np.float32)) < 1.0
        ):
            return mapping

        residual = (
            bev_points
            -
            apply_homography(
                homography,
                image_points,
            )
        )

        norm_mean = image_points.mean(
            axis=0
        )

        norm_scale = float(
            image_points.std()
        )

        if norm_scale <= 1e-9:
            return mapping

        normalized = (
            (image_points - norm_mean)
            /
            norm_scale
        )

        count = len(normalized)

        squared = (
            (
                normalized[:, None, :]
                -
                normalized[None, :, :]
            ) ** 2
        ).sum(axis=-1)

        system = np.zeros(
            (count + 3, count + 3),
            dtype=np.float64,
        )

        system[:count, :count] = _tps_kernel(
            squared
        )

        affine_basis = np.hstack(
            [
                np.ones((count, 1)),
                normalized,
            ]
        )

        system[:count, count:] = affine_basis
        system[count:, :count] = affine_basis.T

        target = np.zeros(
            (count + 3, 2),
            dtype=np.float64,
        )

        target[:count] = residual

        # 정규화(lambda) 없이 정확 보간한다.
        # 같은 영상 위치에 점이 중복된 경우처럼
        # 행렬이 특이하면 lstsq로 최선의 해를 구한다.
        try:
            solution = np.linalg.solve(
                system,
                target,
            )

        except np.linalg.LinAlgError:
            solution = np.linalg.lstsq(
                system,
                target,
                rcond=None,
            )[0]

        if not np.all(np.isfinite(solution)):
            return mapping

        mapping.control_points = normalized
        mapping.weights = solution[:count]
        mapping.affine = solution[count:]
        mapping.norm_mean = norm_mean
        mapping.norm_scale = norm_scale
        mapping.hull = hull

        return mapping

    # -----------------------------------------------------
    # Projection
    # -----------------------------------------------------

    def residual_weight(
        self,
        x: float,
        y: float,
    ) -> float:

        if not self.has_tps:
            return 0.0

        distance = _hull_distance(
            self.hull,
            (x, y),
        )

        if distance <= 0.0:
            return 1.0

        return math.exp(
            -(distance / self.fade_px) ** 2
        )

    def project_many(
        self,
        points,
    ) -> np.ndarray:

        points = np.asarray(
            points,
            dtype=np.float64,
        ).reshape(-1, 2)

        result = apply_homography(
            self.homography,
            points,
        )

        if not self.has_tps:
            return result

        normalized = (
            (points - self.norm_mean)
            /
            self.norm_scale
        )

        squared = (
            (
                normalized[:, None, :]
                -
                self.control_points[None, :, :]
            ) ** 2
        ).sum(axis=-1)

        residual = (
            _tps_kernel(squared) @ self.weights
            +
            np.hstack(
                [
                    np.ones((len(points), 1)),
                    normalized,
                ]
            ) @ self.affine
        )

        weights = np.array(
            [
                self.residual_weight(x, y)
                for x, y in points
            ],
            dtype=np.float64,
        )

        return result + residual * weights[:, None]

    def project(
        self,
        x: float,
        y: float,
    ) -> tuple[float, float]:

        result = self.project_many(
            [[x, y]]
        )[0]

        return (
            float(result[0]),
            float(result[1]),
        )

    # -----------------------------------------------------
    # Serialization
    # -----------------------------------------------------

    def to_dict(
        self,
    ) -> dict | None:
        """
        calibration JSON의 "mapping" 필드.
        TPS가 없으면 None (기존 homography 필드만으로 충분).
        """

        if not self.has_tps:
            return None

        return {
            "type": MAPPING_TYPE,
            "homography": self.homography.tolist(),
            "fade_px": self.fade_px,
            "norm_mean": self.norm_mean.tolist(),
            "norm_scale": self.norm_scale,
            "control_points": self.control_points.tolist(),
            "weights": self.weights.tolist(),
            "affine": self.affine.tolist(),
            "hull": self.hull.tolist(),
        }

    @classmethod
    def from_dict(
        cls,
        data: dict,
    ) -> CalibrationMapping:

        if data.get("type") != MAPPING_TYPE:
            raise ValueError(
                f"Unsupported mapping type: "
                f"{data.get('type')}"
            )

        def array(key, shape_tail):
            value = np.asarray(
                data[key],
                dtype=np.float64,
            )

            if (
                value.ndim != len(shape_tail) + 1
                or
                value.shape[1:] != shape_tail
                or
                not np.all(np.isfinite(value))
            ):
                raise ValueError(
                    f"Invalid mapping field: {key}"
                )

            return value

        homography = np.asarray(
            data["homography"],
            dtype=np.float64,
        )

        if (
            homography.shape != (3, 3)
            or
            not np.all(np.isfinite(homography))
        ):
            raise ValueError(
                "Invalid mapping homography"
            )

        control_points = array("control_points", (2,))
        weights = array("weights", (2,))
        affine = array("affine", (2,))
        hull = array("hull", (2,))

        if (
            len(control_points) != len(weights)
            or
            len(affine) != 3
        ):
            raise ValueError(
                "Mapping size mismatch"
            )

        return cls(
            homography=homography,
            control_points=control_points,
            weights=weights,
            affine=affine,
            norm_mean=np.asarray(
                data["norm_mean"],
                dtype=np.float64,
            ).reshape(2),
            norm_scale=float(data["norm_scale"]),
            hull=hull,
            fade_px=float(
                data.get("fade_px", DEFAULT_FADE_PX)
            ),
        )


# =========================================================
# Coverage
# =========================================================


def coverage_grid(
    image_points,
    width: int,
    height: int,
    step: int = 40,
    radius_px: float | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    영상 전체를 step 간격 grid로 샘플링하고
    가장 가까운 calibration point까지의 거리로 confidence를 계산한다.

    confidence = exp(-(d / radius)^2)
        1.0 : calibration point 바로 근처
        0.0 : calibration point에서 멀리 떨어진 영역

    returns:
        xs (W'), ys (H'), confidence (H', W')
    """

    if radius_px is None:
        radius_px = 0.10 * math.hypot(
            width,
            height,
        )

    xs = np.arange(
        step / 2.0,
        width,
        step,
        dtype=np.float64,
    )

    ys = np.arange(
        step / 2.0,
        height,
        step,
        dtype=np.float64,
    )

    points = np.asarray(
        image_points,
        dtype=np.float64,
    ).reshape(-1, 2)

    if len(points) == 0:
        return (
            xs,
            ys,
            np.zeros((len(ys), len(xs))),
        )

    grid_x, grid_y = np.meshgrid(
        xs,
        ys,
    )

    distance = np.sqrt(
        (
            (grid_x[..., None] - points[:, 0]) ** 2
            +
            (grid_y[..., None] - points[:, 1]) ** 2
        ).min(axis=-1)
    )

    confidence = np.exp(
        -(distance / radius_px) ** 2
    )

    return (
        xs,
        ys,
        confidence,
    )
