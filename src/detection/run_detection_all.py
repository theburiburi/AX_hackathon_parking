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


from src.calibration import CameraProjector
from src.detection.detector import VehicleDetector
from src.video.sync_reader import SynchronizedVideoReader


CONFIG_PATH = (
    ROOT
    / "config"
    / "detection.yaml"
)

BEV_MAP_PATH = (
    ROOT
    / "data"
    / "maps"
    / "map.png"
)

WINDOW_NAME = (
    "AX Parking - 7 Camera YOLO + BEV"
)


CAMERA_COLORS = {
    "cam01": (
        0,
        0,
        255,
    ),
    "cam02": (
        0,
        165,
        255,
    ),
    "cam03": (
        0,
        255,
        255,
    ),
    "cam05": (
        0,
        255,
        0,
    ),
    "cam06": (
        255,
        255,
        0,
    ),
    "cam07": (
        255,
        0,
        0,
    ),
    "cam08": (
        255,
        0,
        255,
    ),
}


@dataclass
class TimingStats:
    count: int = 0

    read_total_ms: float = 0.0
    queue_wait_total_ms: float = 0.0
    inference_total_ms: float = 0.0

    projection_total_ms: float = 0.0

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
        projection_ms: float,
        draw_ms: float,
        grid_ms: float,
        display_ms: float,
        consumer_loop_ms: float,
    ) -> None:

        self.count += 1

        self.read_total_ms += read_ms
        self.queue_wait_total_ms += (
            queue_wait_ms
        )
        self.inference_total_ms += (
            inference_ms
        )

        self.projection_total_ms += (
            projection_ms
        )

        self.draw_total_ms += draw_ms
        self.grid_total_ms += grid_ms
        self.display_total_ms += (
            display_ms
        )

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


@dataclass
class BEVDetection:
    camera_id: str

    class_name: str

    confidence: float

    image_x: float
    image_y: float

    bev_x: float
    bev_y: float


def load_config() -> dict:

    with CONFIG_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:

        return yaml.safe_load(
            file
        )


def load_bev_map() -> np.ndarray:

    bev_map = cv2.imread(
        str(
            BEV_MAP_PATH
        ),
        cv2.IMREAD_COLOR,
    )

    if bev_map is None:

        raise RuntimeError(
            "Failed to load BEV map: "
            f"{BEV_MAP_PATH}"
        )

    return bev_map


def load_projectors(
    camera_ids: list[str],
) -> dict[
    str,
    CameraProjector,
]:

    projectors = {}

    print()

    print(
        "======================================"
    )

    print(
        "CAMERA CALIBRATION"
    )

    print(
        "======================================"
    )

    for camera_id in camera_ids:

        try:

            projector = (
                CameraProjector(
                    camera_id=(
                        camera_id
                    )
                )
            )

            projectors[
                camera_id
            ] = projector

            print(
                f"{camera_id}: loaded"
            )

        except Exception as exc:

            print(
                f"{camera_id}: unavailable"
            )

            print(
                f"  {exc}"
            )

    print(
        "======================================"
    )

    print()

    return projectors


def project_detections(
    camera_ids: list[str],
    all_detections,
    projectors: dict[
        str,
        CameraProjector,
    ],
) -> list[
    list[BEVDetection]
]:

    all_bev_detections = []

    for (
        camera_id,
        detections,
    ) in zip(
        camera_ids,
        all_detections,
    ):

        camera_bev_detections = []

        projector = projectors.get(
            camera_id
        )

        if projector is None:

            all_bev_detections.append(
                camera_bev_detections
            )

            continue

        for detection in detections:

            ground_x = (
                float(
                    detection.x1
                )
                +
                float(
                    detection.x2
                )
            ) / 2.0

            ground_y = float(
                detection.y2
            )

            try:

                bev_x, bev_y = (
                    projector
                    .project(
                        ground_x,
                        ground_y,
                    )
                )

            except Exception:

                continue

            if (
                not math.isfinite(
                    bev_x
                )
                or
                not math.isfinite(
                    bev_y
                )
            ):

                continue

            camera_bev_detections.append(
                BEVDetection(
                    camera_id=(
                        camera_id
                    ),

                    class_name=(
                        detection.class_name
                    ),

                    confidence=float(
                        detection.confidence
                    ),

                    image_x=(
                        ground_x
                    ),

                    image_y=(
                        ground_y
                    ),

                    bev_x=(
                        bev_x
                    ),

                    bev_y=(
                        bev_y
                    ),
                )
            )

        all_bev_detections.append(
            camera_bev_detections
        )

    return all_bev_detections


def draw_detections(
    frame: np.ndarray,
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
            (
                x1,
                y1,
            ),
            (
                x2,
                y2,
            ),
            (
                0,
                255,
                0,
            ),
            line_width,
        )

        ground_x = int(
            round(
                (
                    detection.x1
                    +
                    detection.x2
                )
                /
                2.0
            )
        )

        ground_y = int(
            round(
                detection.y2
            )
        )

        cv2.circle(
            frame,
            (
                ground_x,
                ground_y,
            ),
            5,
            (
                0,
                0,
                255,
            ),
            -1,
            cv2.LINE_AA,
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
            (
                0,
                255,
                0,
            ),
            2,
            cv2.LINE_AA,
        )


def draw_bev_detections(
    bev_map: np.ndarray,
    all_bev_detections: list[
        list[BEVDetection]
    ],
) -> np.ndarray:

    output = bev_map.copy()

    height, width = (
        output.shape[:2]
    )

    total_valid = 0

    for camera_detections in (
        all_bev_detections
    ):

        for detection in (
            camera_detections
        ):

            x = int(
                round(
                    detection.bev_x
                )
            )

            y = int(
                round(
                    detection.bev_y
                )
            )

            if (
                x < 0
                or
                x >= width
                or
                y < 0
                or
                y >= height
            ):

                continue

            total_valid += 1

            color = CAMERA_COLORS.get(
                detection.camera_id,
                (
                    255,
                    255,
                    255,
                ),
            )

            cv2.circle(
                output,
                (
                    x,
                    y,
                ),
                10,
                (
                    255,
                    255,
                    255,
                ),
                -1,
                cv2.LINE_AA,
            )

            cv2.circle(
                output,
                (
                    x,
                    y,
                ),
                7,
                color,
                -1,
                cv2.LINE_AA,
            )

            cv2.putText(
                output,
                detection.camera_id,
                (
                    x + 10,
                    y - 8,
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                color,
                2,
                cv2.LINE_AA,
            )

    cv2.putText(
        output,
        (
            f"BEV vehicles: "
            f"{total_valid}"
        ),
        (
            15,
            30,
        ),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (
            255,
            255,
            255,
        ),
        2,
        cv2.LINE_AA,
    )

    return output


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
            width
            *
            scale
        ),
    )

    new_height = max(
        1,
        int(
            height
            *
            scale
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
    bev_frame: np.ndarray,
    frame_index: int,
    timestamp: float,
    inference_ms: float,
    display_width: int,
    display_height: int,
    columns: int,
) -> np.ndarray:

    all_frames = list(
        frames
    )

    all_camera_ids = list(
        camera_ids
    )

    all_detection_counts = list(
        detection_counts
    )

    all_frames.append(
        bev_frame
    )

    all_camera_ids.append(
        "BEV MAP"
    )

    all_detection_counts.append(
        sum(
            detection_counts
        )
    )

    rows = math.ceil(
        len(
            all_frames
        )
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
        all_frames
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

        if (
            all_camera_ids[index]
            ==
            "BEV MAP"
        ):

            title = (
                "BEV MAP | "
                f"detections "
                f"{all_detection_counts[index]}"
            )

        else:

            title = (
                f"{all_camera_ids[index]} | "
                f"vehicles "
                f"{all_detection_counts[index]}"
            )

        cv2.putText(
            header,
            title,
            (
                8,
                23,
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (
                255,
                255,
                255,
            ),
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
        len(
            tiles
        )
        <
        rows
        *
        columns
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
        (
            255,
            255,
            255,
        ),
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

    avg_projection = stats.average(
        stats.projection_total_ms
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
        f"BEV projection      : "
        f"{avg_projection:8.2f} ms"
    )

    print(
        f"BBox/BEV drawing    : "
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
                config[
                    "videos"
                ]
            ),
            root=ROOT,
            queue_size=(
                queue_size
            ),
        )
    )

    reader.print_info()

    bev_map = load_bev_map()

    projectors = load_projectors(
        reader.camera_ids
    )

    print(
        f"BEV map: "
        f"{BEV_MAP_PATH}"
    )

    print(
        f"BEV size: "
        f"{bev_map.shape[1]}x"
        f"{bev_map.shape[0]}"
    )

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

            frame_set = (
                reader.get()
            )

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
            # 3. CAMERA -> BEV PROJECTION
            # =============================================

            projection_start = (
                time.perf_counter()
            )

            all_bev_detections = (
                project_detections(
                    camera_ids=(
                        reader.camera_ids
                    ),
                    all_detections=(
                        all_detections
                    ),
                    projectors=(
                        projectors
                    ),
                )
            )

            projection_ms = (
                (
                    time.perf_counter()
                    -
                    projection_start
                )
                *
                1000.0
            )

            # =============================================
            # 4. OPTIONAL RENDER
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
                        detections=(
                            detections
                        ),
                        show_confidence=(
                            show_confidence
                        ),
                        line_width=(
                            line_width
                        ),
                    )

                    display_frames.append(
                        output
                    )

                    detection_counts.append(
                        len(
                            detections
                        )
                    )

                bev_output = (
                    draw_bev_detections(
                        bev_map=bev_map,
                        all_bev_detections=(
                            all_bev_detections
                        ),
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
                # 5. GRID
                # =========================================

                grid_start = (
                    time.perf_counter()
                )

                display_frame = (
                    compose_grid(
                        frames=(
                            display_frames
                        ),
                        camera_ids=(
                            reader.camera_ids
                        ),
                        detection_counts=(
                            detection_counts
                        ),
                        bev_frame=(
                            bev_output
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
                        columns=(
                            columns
                        ),
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
                # 6. DISPLAY
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
            # 7. STATS
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
                projection_ms=(
                    projection_ms
                ),
                draw_ms=(
                    draw_ms
                ),
                grid_ms=(
                    grid_ms
                ),
                display_ms=(
                    display_ms
                ),
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