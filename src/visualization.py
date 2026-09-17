"""OpenCV drawing utilities for CCTV and BEV views."""

from collections.abc import Sequence

import cv2
import numpy as np

from .tracking import DetectedVehicle


def color_for_id(track_id: int) -> tuple[int, int, int]:
    """Return a deterministic bright BGR color for a track ID."""
    return (
        64 + (track_id * 37) % 192,
        64 + (track_id * 67) % 192,
        64 + (track_id * 97) % 192,
    )


def _fit_in_cell(image: np.ndarray, width: int, height: int) -> np.ndarray:
    """Aspect-fit an image into a black cell without cropping."""
    if width < 1 or height < 1:
        raise ValueError("display cell dimensions must be positive")
    image_height, image_width = image.shape[:2]
    scale = min(width / image_width, height / image_height)
    resized_width = max(1, int(round(image_width * scale)))
    resized_height = max(1, int(round(image_height * scale)))
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    resized = cv2.resize(image, (resized_width, resized_height), interpolation=interpolation)
    cell = np.zeros((height, width, 3), dtype=np.uint8)
    x = (width - resized_width) // 2
    y = (height - resized_height) // 2
    cell[y : y + resized_height, x : x + resized_width] = resized
    return cell


def draw_camera_detections(
    frame: np.ndarray,
    camera_id: str,
    detections: Sequence[DetectedVehicle],
    calibrated: bool,
    highlight: bool = False,
) -> np.ndarray:
    output = frame.copy()
    color = (0, 255, 255) if highlight else color_for_id(sum(ord(char) for char in camera_id))
    for index, detection in enumerate(detections, start=1):
        x1, y1, x2, y2 = detection.bbox
        ground = tuple(int(round(value)) for value in detection.ground_point)
        cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)
        cv2.circle(output, ground, 5, color, -1, cv2.LINE_AA)
        cv2.putText(
            output,
            f"#{index} {detection.confidence:.2f}",
            (x1, max(22, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
            cv2.LINE_AA,
        )
    state = "CALIBRATED" if calibrated else "UNCALIBRATED"
    cv2.rectangle(output, (0, 0), (output.shape[1], 34), (0, 0, 0), -1)
    cv2.putText(
        output,
        f"{camera_id} | {state} | vehicles {len(detections)}",
        (10, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.62,
        (255, 255, 255) if calibrated else (0, 180, 255),
        2,
        cv2.LINE_AA,
    )
    return output


def draw_bev_positions(base_map, positions, highlight_cameras=()):
    """Draw this frame's projected detections without modifying the source map."""
    output = base_map.copy()
    height, width = output.shape[:2]
    for camera_id, index, (x, y) in positions:
        if not (0 <= x < width and 0 <= y < height):
            continue
        point = (int(x), int(y))
        color = ((0, 255, 255) if camera_id in highlight_cameras
             else color_for_id(sum(ord(char) for char in camera_id)))
        cv2.circle(output, point, 8, color, -1, cv2.LINE_AA)
        cv2.putText(output, f"{camera_id}:#{index}", (point[0] + 10, point[1] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2, cv2.LINE_AA)
    return output


def compose_multi_camera_bev(
    camera_views: Sequence[np.ndarray],
    bev_view: np.ndarray | None,
    max_width: int = 1400,
    max_height: int = 1000,
    columns: int = 3,
    bev_in_spare_space: bool = False,
) -> np.ndarray:
    """Pack aspect-preserving camera rows at the top left, with BEV on the right."""
    if not camera_views or columns < 1:
        raise ValueError("at least one camera view and one column are required")
    rows = max(columns, (len(camera_views) + columns - 1) // columns)
    camera_width = max_width if bev_view is None or bev_in_spare_space else max_width // 2
    cell_width = camera_width // columns
    if cell_width < 2 or max_height < rows:
        raise ValueError("window dimensions are too small for the camera grid")
    # Use the actual image aspect ratios, not a fraction of the window height.
    row_ratios = [max((view.shape[0] / view.shape[1]
                      for view in camera_views[row * columns:(row + 1) * columns]),
                     default=camera_views[0].shape[0] / camera_views[0].shape[1])
                  for row in range(rows)]
    cell_width = min(cell_width, max(1, int(max_height / sum(row_ratios))))
    row_heights = [max(1, int(cell_width * ratio)) for ratio in row_ratios]
    canvas = np.zeros((max_height, max_width, 3), dtype=np.uint8)
    for index, view in enumerate(camera_views):
        row, column = divmod(index, columns)
        x = column * cell_width
        y = sum(row_heights[:row])
        scale = min(cell_width / view.shape[1], row_heights[row] / view.shape[0])
        width = max(1, int(round(view.shape[1] * scale)))
        height = max(1, int(round(view.shape[0] * scale)))
        canvas[y:y + height, x:x + width] = cv2.resize(
            view, (width, height), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
        )
    bev_x = camera_width
    if bev_view is not None and bev_in_spare_space:
        # Choose the largest aspect-fit rectangle that contains no camera pixels.
        used_rows = (len(camera_views) + columns - 1) // columns
        bottom = max_height - 36  # keep playback status readable
        grid_bottom = sum(row_heights[:used_rows])
        spaces = [(0, grid_bottom, max_width, bottom - grid_bottom)]
        last_count = len(camera_views) % columns
        if last_count:
            x = last_count * cell_width
            y = sum(row_heights[:used_rows - 1])
            spaces.append((x, y, max_width - x, bottom - y))
        spaces = [space for space in spaces if space[2] > 0 and space[3] > 0]
        if spaces:
            x, y, width, height = max(spaces, key=lambda space: min(
                space[2] / bev_view.shape[1], space[3] / bev_view.shape[0]))
            canvas[y:y + height, x:x + width] = _fit_in_cell(bev_view, width, height)
    elif bev_view is not None:
        canvas[:, bev_x:] = _fit_in_cell(bev_view, max_width - bev_x, max_height)
    return canvas
