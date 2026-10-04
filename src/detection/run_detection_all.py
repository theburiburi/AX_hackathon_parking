from __future__ import annotations

import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import torch
import yaml


ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )


from src.detection.detector import (
    VehicleDetector,
)


CONFIG_PATH = (
    ROOT
    / "config"
    / "detection.yaml"
)


WINDOW_NAME = (
    "AX Parking - 7 Camera YOLO"
)


@dataclass
class CameraStream:
    camera_id: str
    path: Path
    capture: cv2.VideoCapture

    fps: float
    frame_count: int
    width: int
    height: int


def load_config() -> dict:

    with CONFIG_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:

        return yaml.safe_load(
            file
        )


def open_cameras(
    config: dict,
) -> list[CameraStream]:

    cameras = []

    for video_config in config[
        "videos"
    ]:

        camera_id = video_config[
            "camera_id"
        ]

        path = (
            ROOT
            /
            video_config[
                "path"
            ]
        )

        if not path.exists():

            raise FileNotFoundError(
                f"Video not found: "
                f"{path}"
            )

        capture = cv2.VideoCapture(
            str(path)
        )

        if not capture.isOpened():

            raise RuntimeError(
                f"Failed to open video: "
                f"{path}"
            )

        fps = capture.get(
            cv2.CAP_PROP_FPS
        )

        frame_count = int(
            capture.get(
                cv2.CAP_PROP_FRAME_COUNT
            )
        )

        width = int(
            capture.get(
                cv2.CAP_PROP_FRAME_WIDTH
            )
        )

        height = int(
            capture.get(
                cv2.CAP_PROP_FRAME_HEIGHT
            )
        )

        cameras.append(
            CameraStream(
                camera_id=camera_id,
                path=path,
                capture=capture,
                fps=fps,
                frame_count=frame_count,
                width=width,
                height=height,
            )
        )

    return cameras


def draw_detections(
    frame,
    detections,
    show_confidence: bool,
    line_width: int,
):

    for detection in detections:

        x1 = int(
            detection.x1
        )

        y1 = int(
            detection.y1
        )

        x2 = int(
            detection.x2
        )

        y2 = int(
            detection.y2
        )

        cv2.rectangle(
            frame,
            (x1, y1),
            (x2, y2),
            (0, 255, 0),
            line_width,
        )

        if show_confidence:

            label = (
                f"{detection.class_name} "
                f"{detection.confidence:.2f}"
            )

        else:

            label = (
                detection.class_name
            )

        cv2.putText(
            frame,
            label,
            (
                x1,
                max(
                    20,
                    y1 - 7
                ),
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )


def fit_frame(
    frame: np.ndarray,
    target_width: int,
    target_height: int,
) -> np.ndarray:

    height, width = (
        frame.shape[:2]
    )

    scale = min(
        target_width / width,
        target_height / height,
    )

    new_width = max(
        1,
        int(
            width * scale
        ),
    )

    new_height = max(
        1,
        int(
            height * scale
        ),
    )

    resized = cv2.resize(
        frame,
        (
            new_width,
            new_height,
        ),
        interpolation=cv2.INTER_AREA,
    )

    canvas = np.zeros(
        (
            target_height,
            target_width,
            3,
        ),
        dtype=np.uint8,
    )

    x = (
        target_width
        -
        new_width
    ) // 2

    y = (
        target_height
        -
        new_height
    ) // 2

    canvas[
        y:
        y + new_height,

        x:
        x + new_width,
    ] = resized

    return canvas


def make_placeholder(
    width: int,
    height: int,
) -> np.ndarray:

    return np.zeros(
        (
            height,
            width,
            3,
        ),
        dtype=np.uint8,
    )


def compose_grid(
    frames: list[np.ndarray],
    camera_ids: list[str],
    detection_counts: list[int],
    frame_index: int,
    timestamp: float,
    inference_ms: float,
    display_width: int,
    display_height: int,
    columns: int,
) -> np.ndarray:

    rows = math.ceil(
        len(frames)
        /
        columns
    )

    header_height = 34

    cell_width = (
        display_width
        //
        columns
    )

    cell_height = (
        display_height
        //
        rows
    )

    tiles = []

    for index, frame in enumerate(
        frames
    ):

        content_height = (
            cell_height
            -
            header_height
        )

        content = fit_frame(
            frame,
            cell_width,
            content_height,
        )

        header = np.zeros(
            (
                header_height,
                cell_width,
                3,
            ),
            dtype=np.uint8,
        )

        title = (
            f"{camera_ids[index]} | "
            f"vehicles "
            f"{detection_counts[index]}"
        )

        cv2.putText(
            header,
            title,
            (8, 23),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

        tile = np.vstack(
            [
                header,
                content,
            ]
        )

        tiles.append(
            tile
        )

    while (
        len(tiles)
        <
        rows * columns
    ):

        tiles.append(
            make_placeholder(
                cell_width,
                cell_height,
            )
        )

    grid_rows = []

    for row in range(
        rows
    ):

        start = (
            row
            *
            columns
        )

        end = (
            start
            +
            columns
        )

        grid_rows.append(
            np.hstack(
                tiles[
                    start:end
                ]
            )
        )

    grid = np.vstack(
        grid_rows
    )

    info = (
        f"frame {frame_index} | "
        f"time {timestamp:.2f}s | "
        f"YOLO batch {inference_ms:.1f} ms | "
        f"Q/ESC: quit"
    )

    cv2.putText(
        grid,
        info,
        (
            15,
            grid.shape[0] - 15,
        ),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )

    return grid


def print_camera_info(
    cameras: list[CameraStream],
):

    print()

    print(
        "======================================"
    )

    print(
        "Synchronized camera set"
    )

    print(
        "======================================"
    )

    for camera in cameras:

        duration = (
            camera.frame_count
            /
            camera.fps
            if camera.fps > 0
            else 0
        )

        print(
            f"{camera.camera_id}: "
            f"{camera.path.name} | "
            f"{camera.width}x{camera.height} | "
            f"{camera.fps:.3f} FPS | "
            f"{camera.frame_count} frames | "
            f"{duration:.2f}s"
        )

    print(
        "======================================"
    )

    print()


def validate_cameras(
    cameras: list[CameraStream],
):

    if not cameras:

        raise RuntimeError(
            "No cameras configured."
        )

    reference_fps = cameras[
        0
    ].fps

    for camera in cameras[1:]:

        if (
            abs(
                camera.fps
                -
                reference_fps
            )
            >
            0.01
        ):

            raise RuntimeError(
                "Camera FPS mismatch: "
                f"{cameras[0].camera_id}="
                f"{reference_fps:.3f}, "
                f"{camera.camera_id}="
                f"{camera.fps:.3f}"
            )


def print_gpu_memory():

    allocated = (
        torch.cuda.memory_allocated()
        /
        1024**3
    )

    reserved = (
        torch.cuda.memory_reserved()
        /
        1024**3
    )

    print(
        f"GPU memory | "
        f"allocated={allocated:.2f} GB | "
        f"reserved={reserved:.2f} GB"
    )


def main():

    config = load_config()

    display_config = config[
        "display"
    ]

    show_confidence = bool(
        display_config.get(
            "show_confidence",
            True,
        )
    )

    line_width = int(
        display_config.get(
            "line_width",
            2,
        )
    )

    columns = int(
        display_config.get(
            "grid_columns",
            4,
        )
    )

    display_width = int(
        display_config.get(
            "width",
            1600,
        )
    )

    display_height = int(
        display_config.get(
            "height",
            850,
        )
    )

    detector = VehicleDetector(
        CONFIG_PATH
    )

    cameras = open_cameras(
        config
    )

    validate_cameras(
        cameras
    )

    print_camera_info(
        cameras
    )

    reference_fps = (
        cameras[0].fps
    )

    common_frame_count = min(
        camera.frame_count
        for camera
        in cameras
    )

    camera_ids = [
        camera.camera_id
        for camera
        in cameras
    ]

    processed_sets = 0

    total_inference_time = 0.0

    cv2.namedWindow(
        WINDOW_NAME,
        cv2.WINDOW_NORMAL,
    )

    cv2.resizeWindow(
        WINDOW_NAME,
        display_width,
        display_height,
    )

    try:

        for frame_index in range(
            common_frame_count
        ):

            frames = []

            failed = False

            for camera in cameras:

                success, frame = (
                    camera.capture.read()
                )

                if not success:

                    print(
                        "Failed to read:",
                        camera.camera_id,
                        frame_index,
                    )

                    failed = True

                    break

                frames.append(
                    frame
                )

            if failed:
                break

            start_time = (
                time.perf_counter()
            )

            all_detections = (
                detector.detect_batch(
                    frames
                )
            )

            inference_time = (
                time.perf_counter()
                -
                start_time
            )

            total_inference_time += (
                inference_time
            )

            processed_sets += 1

            display_frames = []

            detection_counts = []

            for (
                frame,
                detections,
            ) in zip(
                frames,
                all_detections,
            ):

                output = (
                    frame.copy()
                )

                draw_detections(
                    frame=output,
                    detections=detections,
                    show_confidence=show_confidence,
                    line_width=line_width,
                )

                display_frames.append(
                    output
                )

                detection_counts.append(
                    len(detections)
                )

            timestamp = (
                frame_index
                /
                reference_fps
            )

            display = compose_grid(
                frames=display_frames,
                camera_ids=camera_ids,
                detection_counts=detection_counts,
                frame_index=frame_index,
                timestamp=timestamp,
                inference_ms=(
                    inference_time
                    *
                    1000
                ),
                display_width=display_width,
                display_height=display_height,
                columns=columns,
            )

            cv2.imshow(
                WINDOW_NAME,
                display,
            )

            if (
                processed_sets
                %
                30
                ==
                0
            ):

                set_fps = (
                    processed_sets
                    /
                    total_inference_time
                )

                camera_fps = (
                    set_fps
                    *
                    len(cameras)
                )

                print(
                    f"frame={frame_index} | "
                    f"sets/s={set_fps:.2f} | "
                    f"camera frames/s="
                    f"{camera_fps:.2f}"
                )

                print_gpu_memory()

            key = (
                cv2.waitKey(1)
                &
                0xFF
            )

            if key in (
                ord("q"),
                27,
            ):

                break

    finally:

        for camera in cameras:

            camera.capture.release()

        cv2.destroyAllWindows()

    print()

    print(
        "======================================"
    )

    print(
        "7-camera detection finished."
    )

    print(
        f"Synchronized sets: "
        f"{processed_sets}"
    )

    if processed_sets > 0:

        average_time = (
            total_inference_time
            /
            processed_sets
        )

        set_fps = (
            1.0
            /
            average_time
        )

        camera_fps = (
            set_fps
            *
            len(cameras)
        )

        print(
            f"Average inference/set: "
            f"{average_time * 1000:.2f} ms"
        )

        print(
            f"Synchronized sets/s: "
            f"{set_fps:.2f}"
        )

        print(
            f"Total camera frames/s: "
            f"{camera_fps:.2f}"
        )

    print_gpu_memory()

    print(
        "======================================"
    )


if __name__ == "__main__":
    main()