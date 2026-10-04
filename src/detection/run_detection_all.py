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
from src.video.sync_reader import SynchronizedVideoReader


CONFIG_PATH = (
    ROOT
    / "config"
    / "detection.yaml"
)

WINDOW_NAME = (
    "AX Parking - 7 Camera YOLO"
)


@dataclass
class TimingStats:
    count: int = 0

    read_total_ms: float = 0.0
    queue_wait_total_ms: float = 0.0
    inference_total_ms: float = 0.0

    draw_total_ms: float = 0.0
    grid_total_ms: float = 0.0
    display_total_ms: float = 0.0

    consumer_loop_total_ms: float = 0.0

    started_at: float = 0.0

    def start(
        self,
    ) -> None:

        self.started_at = (
            time.perf_counter()
        )

    def add(
        self,
        read_ms: float,
        queue_wait_ms: float,
        inference_ms: float,
        draw_ms: float,
        grid_ms: float,
        display_ms: float,
        consumer_loop_ms: float,
    ) -> None:

        self.count += 1

        self.read_total_ms += read_ms
        self.queue_wait_total_ms += queue_wait_ms
        self.inference_total_ms += inference_ms

        self.draw_total_ms += draw_ms
        self.grid_total_ms += grid_ms
        self.display_total_ms += display_ms

        self.consumer_loop_total_ms += (
            consumer_loop_ms
        )

    def average(
        self,
        total: float,
    ) -> float:

        if self.count == 0:
            return 0.0

        return (
            total
            /
            self.count
        )

    @property
    def elapsed_seconds(
        self,
    ) -> float:

        if self.started_at <= 0:
            return 0.0

        return (
            time.perf_counter()
            -
            self.started_at
        )

    @property
    def throughput(
        self,
    ) -> float:

        elapsed = (
            self.elapsed_seconds
        )

        if elapsed <= 0:
            return 0.0

        return (
            self.count
            /
            elapsed
        )


def load_config() -> dict:

    with CONFIG_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:

        return yaml.safe_load(
            file
        )


def draw_detections(
    frame: np.ndarray,
    detections,
    show_confidence: bool,
    line_width: int,
) -> None:

    for detection in detections:

        x1 = int(detection.x1)
        y1 = int(detection.y1)
        x2 = int(detection.x2)
        y2 = int(detection.y2)

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
        y:y + new_height,
        x:x + new_width,
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

    for row_index in range(
        rows
    ):

        start = (
            row_index
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

    peak_allocated = (
        torch.cuda.max_memory_allocated()
        /
        1024**3
    )

    peak_reserved = (
        torch.cuda.max_memory_reserved()
        /
        1024**3
    )

    print(
        "GPU memory | "
        f"allocated="
        f"{allocated:.2f} GB | "
        f"reserved="
        f"{reserved:.2f} GB | "
        f"peak allocated="
        f"{peak_allocated:.2f} GB | "
        f"peak reserved="
        f"{peak_reserved:.2f} GB"
    )


def print_stats(
    stats: TimingStats,
    camera_count: int,
) -> None:

    if stats.count == 0:
        return

    avg_read = stats.average(
        stats.read_total_ms
    )

    avg_queue_wait = stats.average(
        stats.queue_wait_total_ms
    )

    avg_inference = stats.average(
        stats.inference_total_ms
    )

    avg_draw = stats.average(
        stats.draw_total_ms
    )

    avg_grid = stats.average(
        stats.grid_total_ms
    )

    avg_display = stats.average(
        stats.display_total_ms
    )

    avg_consumer_loop = (
        stats.average(
            stats.consumer_loop_total_ms
        )
    )

    sets_per_second = (
        stats.throughput
    )

    camera_frames_per_second = (
        sets_per_second
        *
        camera_count
    )

    print()

    print(
        "======================================"
    )

    print(
        "PIPELINE PERFORMANCE"
    )

    print(
        "======================================"
    )

    print(
        f"Samples             : "
        f"{stats.count}"
    )

    print()

    print(
        f"Video read/thread   : "
        f"{avg_read:8.2f} ms"
    )

    print(
        f"Queue wait/main     : "
        f"{avg_queue_wait:8.2f} ms"
    )

    print(
        f"YOLO inference      : "
        f"{avg_inference:8.2f} ms"
    )

    print(
        f"BBox drawing        : "
        f"{avg_draw:8.2f} ms"
    )

    print(
        f"Grid compose        : "
        f"{avg_grid:8.2f} ms"
    )

    print(
        f"imshow/waitKey      : "
        f"{avg_display:8.2f} ms"
    )

    print(
        f"Consumer loop       : "
        f"{avg_consumer_loop:8.2f} ms"
    )

    print(
        "--------------------------------------"
    )

    print(
        f"Real sets/s         : "
        f"{sets_per_second:.2f}"
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

    pipeline_config = (
        config.get(
            "pipeline",
            {},
        )
    )

    profile_config = (
        config.get(
            "profile",
            {},
        )
    )

    display_config = (
        config.get(
            "display",
            {},
        )
    )

    queue_size = int(
        pipeline_config.get(
            "queue_size",
            2,
        )
    )

    print_interval = int(
        profile_config.get(
            "print_interval",
            100,
        )
    )

    show = bool(
        display_config.get(
            "show",
            False,
        )
    )

    render = bool(
        display_config.get(
            "render",
            False,
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
        f"Render enabled: "
        f"{render}"
    )

    print(
        f"Display enabled: "
        f"{show}"
    )

    detector = VehicleDetector(
        CONFIG_PATH
    )

    reader = (
        SynchronizedVideoReader(
            video_configs=(
                config["videos"]
            ),
            root=ROOT,
            queue_size=queue_size,
        )
    )

    reader.print_info()

    print(
        f"Pipeline queue size: "
        f"{queue_size}"
    )

    print(
        "Video decode thread: enabled"
    )

    print(
        "YOLO worker: main thread"
    )

    print()

    torch.cuda.reset_peak_memory_stats()

    stats = TimingStats()

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

    reader.start()

    stats.start()

    try:

        while True:

            consumer_start = (
                time.perf_counter()
            )

            # =============================================
            # 1. GET SYNCHRONIZED FRAME SET
            # =============================================

            queue_wait_start = (
                time.perf_counter()
            )

            frame_set = reader.get()

            queue_wait_ms = (
                (
                    time.perf_counter()
                    -
                    queue_wait_start
                )
                *
                1000.0
            )

            if frame_set is None:
                break

            # =============================================
            # 2. YOLO
            # =============================================

            inference_start = (
                time.perf_counter()
            )

            all_detections = (
                detector.detect_batch(
                    frame_set.frames
                )
            )

            torch.cuda.synchronize()

            inference_ms = (
                (
                    time.perf_counter()
                    -
                    inference_start
                )
                *
                1000.0
            )

            # =============================================
            # 3. OPTIONAL BBOX RENDER
            # =============================================

            draw_ms = 0.0
            grid_ms = 0.0
            display_ms = 0.0

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
                    frame_set.frames,
                    all_detections,
                ):

                    output = (
                        frame.copy()
                    )

                    draw_detections(
                        frame=output,
                        detections=detections,
                        show_confidence=(
                            show_confidence
                        ),
                        line_width=line_width,
                    )

                    display_frames.append(
                        output
                    )

                    detection_counts.append(
                        len(
                            detections
                        )
                    )

                draw_ms = (
                    (
                        time.perf_counter()
                        -
                        draw_start
                    )
                    *
                    1000.0
                )

                # =========================================
                # 4. GRID
                # =========================================

                grid_start = (
                    time.perf_counter()
                )

                display_frame = (
                    compose_grid(
                        frames=display_frames,
                        camera_ids=(
                            reader.camera_ids
                        ),
                        detection_counts=(
                            detection_counts
                        ),
                        frame_index=(
                            frame_set.frame_index
                        ),
                        timestamp=(
                            frame_set.timestamp
                        ),
                        inference_ms=(
                            inference_ms
                        ),
                        display_width=(
                            display_width
                        ),
                        display_height=(
                            display_height
                        ),
                        columns=columns,
                    )
                )

                grid_ms = (
                    (
                        time.perf_counter()
                        -
                        grid_start
                    )
                    *
                    1000.0
                )

                # =========================================
                # 5. DISPLAY
                # =========================================

                if show:

                    display_start = (
                        time.perf_counter()
                    )

                    cv2.imshow(
                        WINDOW_NAME,
                        display_frame,
                    )

                    key = (
                        cv2.waitKey(1)
                        &
                        0xFF
                    )

                    display_ms = (
                        (
                            time.perf_counter()
                            -
                            display_start
                        )
                        *
                        1000.0
                    )

            # =============================================
            # 6. STATS
            # =============================================

            consumer_loop_ms = (
                (
                    time.perf_counter()
                    -
                    consumer_start
                )
                *
                1000.0
            )

            stats.add(
                read_ms=(
                    frame_set.read_time_ms
                ),
                queue_wait_ms=(
                    queue_wait_ms
                ),
                inference_ms=(
                    inference_ms
                ),
                draw_ms=draw_ms,
                grid_ms=grid_ms,
                display_ms=display_ms,
                consumer_loop_ms=(
                    consumer_loop_ms
                ),
            )

            if (
                stats.count
                %
                print_interval
                ==
                0
            ):

                print_stats(
                    stats,
                    len(
                        reader.cameras
                    ),
                )

                print_gpu_memory()

            if key in (
                ord("q"),
                27,
            ):
                break

    except KeyboardInterrupt:

        print()

        print(
            "Interrupted by user."
        )

    finally:

        reader.stop()

        cv2.destroyAllWindows()

    print()

    print(
        "7-camera pipeline finished."
    )

    print_stats(
        stats,
        len(
            reader.cameras
        ),
    )

    print_gpu_memory()


if __name__ == "__main__":
    main()