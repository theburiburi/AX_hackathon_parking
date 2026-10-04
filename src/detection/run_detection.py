from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
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


def load_config() -> dict:

    with CONFIG_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:

        return yaml.safe_load(
            file
        )


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

        text_size, baseline = (
            cv2.getTextSize(
                label,
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                1,
            )
        )

        text_width, text_height = (
            text_size
        )

        label_y1 = max(
            0,
            y1
            -
            text_height
            -
            baseline
            -
            8,
        )

        cv2.rectangle(
            frame,
            (
                x1,
                label_y1,
            ),
            (
                x1
                +
                text_width
                +
                8,
                y1,
            ),
            (0, 255, 0),
            -1,
        )

        cv2.putText(
            frame,
            label,
            (
                x1 + 4,
                y1
                -
                baseline
                -
                4,
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )


def main():

    config = load_config()

    video_config = config[
        "video"
    ]

    display_config = config[
        "display"
    ]

    video_path = (
        ROOT
        /
        video_config[
            "path"
        ]
    )

    camera_id = video_config[
        "camera_id"
    ]

    show = bool(
        display_config.get(
            "show",
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

    if not video_path.exists():

        raise FileNotFoundError(
            f"Video not found: "
            f"{video_path}"
        )

    detector = VehicleDetector(
        CONFIG_PATH
    )

    capture = cv2.VideoCapture(
        str(video_path)
    )

    if not capture.isOpened():

        raise RuntimeError(
            f"Failed to open video: "
            f"{video_path}"
        )

    video_fps = capture.get(
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

    print()
    print(
        "=============================="
    )

    print(
        f"Camera: {camera_id}"
    )

    print(
        f"Video: {video_path.name}"
    )

    print(
        f"Resolution: "
        f"{width}x{height}"
    )

    print(
        f"FPS: {video_fps:.3f}"
    )

    print(
        f"Frames: {frame_count}"
    )

    print(
        "=============================="
    )

    print()

    processed_frames = 0

    total_inference_time = 0.0

    try:

        while True:

            success, frame = (
                capture.read()
            )

            if not success:
                break

            frame_index = int(
                capture.get(
                    cv2.CAP_PROP_POS_FRAMES
                )
            ) - 1

            start_time = (
                time.perf_counter()
            )

            detections = (
                detector.detect(
                    frame
                )
            )

            inference_time = (
                time.perf_counter()
                -
                start_time
            )

            processed_frames += 1

            total_inference_time += (
                inference_time
            )

            inference_fps = (
                1.0
                /
                inference_time
                if inference_time > 0
                else 0.0
            )

            timestamp = (
                frame_index
                /
                video_fps
                if video_fps > 0
                else 0
            )

            draw_detections(
                frame=frame,
                detections=detections,
                show_confidence=show_confidence,
                line_width=line_width,
            )

            info_text = (
                f"{camera_id} | "
                f"frame {frame_index} | "
                f"time {timestamp:.2f}s | "
                f"vehicles {len(detections)} | "
                f"YOLO {inference_fps:.1f} FPS"
            )

            cv2.putText(
                frame,
                info_text,
                (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

            if show:

                cv2.imshow(
                    "AX Parking - YOLO Detection",
                    frame,
                )

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

        capture.release()

        cv2.destroyAllWindows()

    print()

    print(
        "Detection finished."
    )

    print(
        f"Processed frames: "
        f"{processed_frames}"
    )

    if processed_frames > 0:

        average_time = (
            total_inference_time
            /
            processed_frames
        )

        average_fps = (
            1.0
            /
            average_time
            if average_time > 0
            else 0
        )

        print(
            f"Average inference: "
            f"{average_time * 1000:.2f} ms"
        )

        print(
            f"Average YOLO FPS: "
            f"{average_fps:.2f}"
        )


if __name__ == "__main__":
    main()