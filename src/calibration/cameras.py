"""Build per-camera transforms from existing calibration settings."""

from .homography import compute_homography


def camera_homographies(registry) -> tuple[dict[str, object], list[str]]:
    matrices = {}
    missing = []
    for camera in registry.cameras:
        calibration = camera.calibration
        if calibration.get("is_sample", True):
            missing.append(camera.camera_id)
            continue
        try:
            matrix, _mask = compute_homography(
                calibration.get("image_points", []),
                calibration.get("bev_points", []),
                calibration.get("ransac_reproj_threshold", 5.0),
            )
        except ValueError as error:
            raise ValueError(f"invalid calibration for {camera.camera_id}: {error}") from error
        matrices[camera.camera_id] = matrix
    return matrices, missing


