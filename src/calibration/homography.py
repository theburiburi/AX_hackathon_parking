"""CCTV image-to-BEV homography helpers."""

from collections.abc import Sequence

import cv2
import numpy as np


def compute_homography(
    image_points: Sequence[Sequence[float]],
    bev_points: Sequence[Sequence[float]],
    ransac_reproj_threshold: float = 5.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute image-to-BEV H and the RANSAC inlier mask."""
    source = np.asarray(image_points, dtype=np.float32)
    destination = np.asarray(bev_points, dtype=np.float32)

    if source.ndim != 2 or source.shape[1:] != (2,):
        raise ValueError("calibration.image_points must be a list of [u, v] pairs")
    if destination.ndim != 2 or destination.shape[1:] != (2,):
        raise ValueError("calibration.bev_points must be a list of [x, y] pairs")
    if len(source) != len(destination):
        raise ValueError("image_points and bev_points must contain the same number of points")
    if len(source) < 4:
        raise ValueError("at least 4 matching calibration points are required")
    if not np.isfinite(source).all() or not np.isfinite(destination).all():
        raise ValueError("calibration points must contain only finite numbers")

    matrix, mask = cv2.findHomography(
        source,
        destination,
        method=cv2.RANSAC,
        ransacReprojThreshold=float(ransac_reproj_threshold),
    )
    if matrix is None or mask is None:
        raise ValueError("homography could not be computed; check the calibration points")
    return matrix, mask.ravel().astype(bool)


def project_point(point: tuple[float, float], matrix: np.ndarray) -> tuple[float, float]:
    """Project one CCTV pixel coordinate onto the BEV image."""
    source = np.asarray([[point]], dtype=np.float32)
    projected = cv2.perspectiveTransform(source, matrix)[0, 0]
    if not np.isfinite(projected).all():
        raise ValueError("homography produced a non-finite BEV coordinate")
    return float(projected[0]), float(projected[1])
