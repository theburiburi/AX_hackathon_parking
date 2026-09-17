"""Display synchronized CCTV cameras with optional vehicle detection."""

import argparse
from pathlib import Path
import sys
import time

import cv2
import numpy as np
import yaml

from .association import AssociationObservation, GlobalVehicleAssociator
from .camera_config import load_camera_registry
from .calibration.cameras import camera_homographies
from .calibration.homography import project_point
from .playback.reader import SynchronizedVideoReader
from .tracking import BatchVehicleDetector, DetectedVehicle
from .visualization import (
    compose_multi_camera_bev,
    draw_camera_detections,
    draw_bev_positions,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Display synchronized CCTV cameras with optional vehicle detection."
    )
    parser.add_argument("--cameras-config", type=Path, default=Path("cameras.yaml"))
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--width", type=int, default=700)
    parser.add_argument("--height", type=int, default=500)
    parser.add_argument("--no-yolo", action="store_true", help="play videos without loading YOLO")
    parser.add_argument(
        "--select-entry-region",
        action="store_true",
        help="select and save the cam01 entry region from the first frame",
    )
    return parser.parse_args()


def load_runtime_config(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"runtime config not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    if not isinstance(config, dict) or not isinstance(config.get("detection"), dict):
        raise ValueError("runtime config must contain a detection section")
    return config


def read_image(path: Path) -> np.ndarray:
    """Read an image through bytes so Windows Unicode paths work reliably."""
    if not path.is_file():
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is not None:
            return image
        raise ValueError(f"failed to decode image: {path}")
    image_bytes = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(image_bytes, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"failed to decode image: {path}")
    return image


def point_in_region(point: tuple[float, float], region: tuple[int, int, int, int]) -> bool:
    x, y = point
    left, top, right, bottom = region
    return left <= x <= right and top <= y <= bottom


def filter_entry_detections(
    detections: list[DetectedVehicle],
    region: tuple[int, int, int, int] | None,
) -> list[DetectedVehicle]:
    if region is None:
        return detections
    return [vehicle for vehicle in detections if point_in_region(vehicle.ground_point, region)]


def parse_entry_region(value) -> tuple[int, int, int, int] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("detection.entry_region must be [left, top, right, bottom]")
    left, top, right, bottom = (int(item) for item in value)
    if left >= right or top >= bottom:
        raise ValueError("detection.entry_region must describe a non-empty rectangle")
    return left, top, right, bottom


def select_entry_region(frame: np.ndarray) -> tuple[int, int, int, int]:
    selection = cv2.selectROI(
        "Select cam01 entry region - ENTER confirm / ESC cancel",
        frame,
        fromCenter=False,
        showCrosshair=True,
    )
    cv2.destroyWindow("Select cam01 entry region - ENTER confirm / ESC cancel")
    x, y, width, height = (int(value) for value in selection)
    if width <= 0 or height <= 0:
        raise ValueError("an entry region must be selected")
    return x, y, x + width, y + height


def run(args: argparse.Namespace) -> None:
    if args.width < 640 or args.height < 480:
        raise ValueError("window size must be at least 640x480")
    registry = load_camera_registry(args.cameras_config)
    runtime = load_runtime_config(args.config)
    detection = runtime["detection"]
    enabled = detection.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("detection.enabled must be a YAML boolean (true/false)")
    enabled = enabled and not getattr(args, "no_yolo", False)
    entry_region = parse_entry_region(detection.get("entry_region"))
    matrices, missing = camera_homographies(registry) if enabled else ({}, [])
    if missing:
        print("WARNING: no BEV projection for uncalibrated cameras: " + ", ".join(missing), file=sys.stderr)
    bev_map = read_image(registry.bev_map)
    detector = None
    detect_every = max(1, int(detection.get("detect_every_n_frames", 1)))
    associator = GlobalVehicleAssociator(
        entry_camera=str(detection.get("entry_camera", "cam01")),
        max_distance=float(detection.get("global_id_max_distance", 90.0)),
        max_missed_updates=int(detection.get("global_id_max_missed_updates", 30)),
    )
    if enabled:
        detector = BatchVehicleDetector(
            model_name=detection.get("model", "models/detection/yolo11n.pt"),
            confidence=float(detection.get("confidence", 0.3)),
            iou=float(detection.get("iou", 0.5)),
            vehicle_classes=detection.get("vehicle_classes", [2, 5, 7]),
            image_size=int(detection.get("image_size", 640)),
            device=detection.get("device", "auto"),
        )

    paths = [camera.video for camera in registry.cameras]
    offsets = [camera.offset_seconds for camera in registry.cameras]
    window = "CCTV | Space pause | A/D +/-5s | Q quit"
    with SynchronizedVideoReader(paths, offsets) as reader:
        for camera, info in zip(registry.cameras, reader.infos):
            if abs(camera.fps - info.fps) > 0.01:
                raise ValueError(
                    f"FPS mismatch for {camera.camera_id}: config={camera.fps}, video={info.fps}"
                )
        position_ms = reader.start_ms
        if getattr(args, "select_entry_region", False):
            first_frames = reader.read_at(position_ms)
            entry_index = next(
                (index for index, camera in enumerate(registry.cameras)
                 if camera.camera_id == detection.get("entry_camera", "cam01")),
                None,
            )
            if entry_index is None:
                raise ValueError("entry camera is not present in cameras.yaml")
            entry_region = select_entry_region(first_frames[entry_index])
            detection["entry_region"] = list(entry_region)
            with args.config.open("w", encoding="utf-8", newline="\n") as file:
                yaml.safe_dump(runtime, file, sort_keys=False, allow_unicode=True)
            print(f"Saved cam01 entry region: {entry_region}")
        anchor_ms = position_ms
        anchor_wall = time.monotonic()
        playing = True
        cv2.namedWindow(window, cv2.WINDOW_NORMAL | cv2.WINDOW_FREERATIO)
        cv2.resizeWindow(window, args.width, args.height)
        display_width, display_height = args.width, args.height
        frame_tick = 0
        batches = [[] for _ in registry.cameras]
        while True:
            if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                break
            _x, _y, width, height = cv2.getWindowImageRect(window)
            # Minimized windows may temporarily report an empty drawable area.
            if width >= 32 and height >= 32:
                display_width, display_height = width, height
            if playing:
                position_ms = anchor_ms + (time.monotonic() - anchor_wall) * 1000.0
            if position_ms >= reader.end_ms:
                position_ms = reader.end_ms - 0.001
                playing = False

            frames = reader.read_at(position_ms)
            if detector is not None and frame_tick % detect_every == 0:
                batches = detector.detect(frames)
            frame_tick += 1
            camera_views = []
            projected = []
            for camera, frame, detections in zip(registry.cameras, frames, batches):
                if camera.camera_id == associator.entry_camera:
                    detections = filter_entry_detections(detections, entry_region)
                matrix = matrices.get(camera.camera_id)
                camera_views.append(
                    draw_camera_detections(
                        frame,
                        camera.camera_id,
                        detections,
                        calibrated=matrix is not None,
                        highlight=camera.camera_id == associator.entry_camera,
                    )
                )
                if matrix is not None:
                    for index, vehicle in enumerate(detections, start=1):
                        try:
                            point = project_point(vehicle.ground_point, matrix)
                        except ValueError:
                            continue
                        projected.append(AssociationObservation(
                            camera_id=camera.camera_id,
                            local_id=index,
                            class_id=vehicle.class_id,
                            point=point,
                            confidence=vehicle.confidence,
                        ))
            assignments = associator.update(projected)
            positions = [
                (observation.camera_id, assignments[key], observation.point)
                for observation in projected
                if (key := (observation.camera_id, observation.local_id)) in assignments
            ]
            bev_view = draw_bev_positions(
                bev_map, positions, highlight_cameras={associator.entry_camera}
            )
            combined = compose_multi_camera_bev(
                camera_views, bev_view, display_width, display_height, bev_in_spare_space=True
            )
            cv2.putText(
                combined,
                f"t={position_ms / 1000:.2f}s | {'PLAY' if playing else 'PAUSE'} | YOLO {'ON' if enabled else 'OFF'}",
                (12, display_height - 14),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            cv2.imshow(window, combined)
            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break
            if key == ord(" "):
                playing = not playing
                anchor_ms = position_ms
                anchor_wall = time.monotonic()
            elif key in (ord("a"), ord("d")):
                delta = -5000.0 if key == ord("a") else 5000.0
                position_ms = min(reader.end_ms - 0.001, max(reader.start_ms, position_ms + delta))
                anchor_ms = position_ms
                anchor_wall = time.monotonic()
    cv2.destroyAllWindows()


def main() -> int:
    try:
        run(parse_args())
    except (FileNotFoundError, KeyError, TypeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
