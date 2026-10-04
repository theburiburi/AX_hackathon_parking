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


from src.detection.detector import VehicleDetector


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


@dataclass
class TimingStats:
    count: int = 0

    read_total: float = 0.0
    inference_total: float = 0.0
    draw_total: float = 0.0
    grid_total: float = 0.0
    display_total: float = 0.0
    loop_total: float = 0.0

    def add(
        self,
        read_time: float,
        inference_time: float,
        draw_time: float,
        grid_time: float,
        display_time: float,
        loop_time: float,
    ) -> None:

        self.count += 1

        self.read_total += read_time
        self.inference_total += inference_time
        self.draw_total += draw_time
        self.grid_total += grid_time
        self.display_total += display_time
        self.loop_total += loop_time

    def average_ms(
        self,
        value: float,
    ) -> float:

        if self.count == 0:
            return 0.0

        return (
            value
            /
            self.count
            *
            1000.0
        )

    def percentage(
        self,
        value: float,
    ) -> float:

        if self.loop_total <= 0:
            return 0.0

        return (
            value
            /
            self.loop_total
            *
            100.0
        )


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


def validate_cameras(
    cameras: list[CameraStream],
) -> None:

    if not cameras:

        raise RuntimeError(
            "No cameras configured."
        )

    reference_fps = (
        cameras[0].fps
    )

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


def print_camera_info(
    cameras: list[CameraStream],
) -> None:

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


def print_gpu_memory() -> None:

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

    max_allocated = (
        torch.cuda.max_memory_allocated()
        /
        1024**3
    )

    max_reserved = (
        torch.cuda.max_memory_reserved()
        /
        1024**3
    )

    print(
        f"GPU memory | "
        f"allocated={allocated:.2f} GB | "
        f"reserved={reserved:.2f} GB | "
        f"peak allocated={max_allocated:.2f} GB | "
        f"peak reserved={max_reserved:.2f} GB"
    )


def draw_detections(
    frame,
    detections,
    show_confidence: bool,
    line_width: int,
) -> None:

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
                    y1 - 7,
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
        f"YOLO {inference_ms:.1f} ms | "
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


def print_timing_stats(
    stats: TimingStats,
    camera_count: int,
) -> None:

    if stats.count == 0:
        return

    read_ms = stats.average_ms(
        stats.read_total
    )

    inference_ms = stats.average_ms(
        stats.inference_total
    )

    draw_ms = stats.average_ms(
        stats.draw_total
    )

    grid_ms = stats.average_ms(
        stats.grid_total
    )

    display_ms = stats.average_ms(
        stats.display_total
    )

    loop_ms = stats.average_ms(
        stats.loop_total
    )

    loop_fps = (
        1000.0
        /
        loop_ms
        if loop_ms > 0
        else 0.0
    )

    camera_frames_per_second = (
        loop_fps
        *
        camera_count
    )

    print()

    print(
        "======================================"
    )

    print(
        "PERFORMANCE PROFILE"
    )

    print(
        "======================================"
    )

    print(
        f"Samples: "
        f"{stats.count}"
    )

    print()

    print(
        f"Video read     : "
        f"{read_ms:8.2f} ms "
        f"("
        f"{stats.percentage(stats.read_total):5.1f}%"
        f")"
    )

    print(
        f"YOLO inference : "
        f"{inference_ms:8.2f} ms "
        f"("
        f"{stats.percentage(stats.inference_total):5.1f}%"
        f")"
    )

    print(
        f"BBox drawing   : "
        f"{draw_ms:8.2f} ms "
        f"("
        f"{stats.percentage(stats.draw_total):5.1f}%"
        f")"
    )

    print(
        f"Grid compose   : "
        f"{grid_ms:8.2f} ms "
        f"("
        f"{stats.percentage(stats.grid_total):5.1f}%"
        f")"
    )

    print(
        f"imshow/waitKey : "
        f"{display_ms:8.2f} ms "
        f"("
        f"{stats.percentage(stats.display_total):5.1f}%"
        f")"
    )

    print(
        "--------------------------------------"
    )

    print(
        f"Whole loop     : "
        f"{loop_ms:8.2f} ms"
    )

    print()

    print(
        f"Synchronized sets/s : "
        f"{loop_fps:.2f}"
    )

    print(
        f"Camera frames/s     : "
        f"{camera_frames_per_second:.2f}"
    )

    print(
        "======================================"
    )


def main() -> None:

    config = load_config()

    display_config = config[
        "display"
    ]

    show = bool(
        display_config.get(
            "show",
            True,
        )
    )

    render = bool(
        display_config.get(
            "render",
            True,
        )
    )

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


    print(
        f"Render enabled: {render}"
    )

    print(
        f"Display enabled: {show}"
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


    stats = TimingStats()


    torch.cuda.reset_peak_memory_stats()


    if show and render:

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

            loop_start = (
                time.perf_counter()
            )


            # =============================================
            # 1. VIDEO READ
            # =============================================

            read_start = (
                time.perf_counter()
            )


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


            read_time = (
                time.perf_counter()
                -
                read_start
            )


            if failed:
                break


            # =============================================
            # 2. YOLO
            # =============================================

            inference_start = (
                time.perf_counter()
            )


            all_detections = (
                detector.detect_batch(
                    frames
                )
            )


            torch.cuda.synchronize()


            inference_time = (
                time.perf_counter()
                -
                inference_start
            )


            # =============================================
            # 3. OPTIONAL RENDER
            # =============================================

            draw_time = 0.0
            grid_time = 0.0
            display_time = 0.0

            key = 255


            if render:

                draw_start = (
                    time.perf_counter()
                )


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


                draw_time = (
                    time.perf_counter()
                    -
                    draw_start
                )


                grid_start = (
                    time.perf_counter()
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


                grid_time = (
                    time.perf_counter()
                    -
                    grid_start
                )


                if show:

                    display_start = (
                        time.perf_counter()
                    )


                    cv2.imshow(
                        WINDOW_NAME,
                        display,
                    )


                    key = (
                        cv2.waitKey(1)
                        &
                        0xFF
                    )


                    display_time = (
                        time.perf_counter()
                        -
                        display_start
                    )


            # =============================================
            # 4. TOTAL
            # =============================================

            loop_time = (
                time.perf_counter()
                -
                loop_start
            )


            stats.add(
                read_time=read_time,
                inference_time=inference_time,
                draw_time=draw_time,
                grid_time=grid_time,
                display_time=display_time,
                loop_time=loop_time,
            )


            if (
                stats.count
                %
                100
                ==
                0
            ):

                print_timing_stats(
                    stats,
                    len(cameras),
                )

                print_gpu_memory()


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
        "7-camera profiling finished."
    )


    print_timing_stats(
        stats,
        len(cameras),
    )


    print_gpu_memory()


if __name__ == "__main__":
    main()