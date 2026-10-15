from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )

from src.detection.detector import VehicleDetector  # noqa: E402
from src.mosaic import (  # noqa: E402
    DETECTION_CONFIG_PATH,
    load_video,
)
from src.view_mode import (  # noqa: E402
    VIEW_MODES_FILENAME,
    ViewModeRecorder,
    load_letterbox,
)


"""
모자이크 원본 영상 전처리.

data/videos/raw/<title>.mp4 를 한 번 읽으면서
  1. 칸별로 잘라 카메라 영상 7개로 저장한다.
       -> data/videos/<title>/<camera_id>.mp4
  2. 같은 잘라낸 이미지에 YOLO를 돌려 bbox를 저장한다.
       -> data/detections/<title>/detections.jsonl, metadata.json

칸 배치는 config/mosaic.yaml, YOLO 설정은 config/detection.yaml을 사용한다.
모든 카메라가 같은 모자이크 프레임에서 잘리므로
분리 영상, bbox의 프레임 번호가 원본과 정확히 일치한다.

bbox 좌표는 잘라낸 칸 기준 픽셀이다.

예:
    python scripts/preprocess.py test00
    python scripts/preprocess.py test00 --overwrite
    python scripts/preprocess.py test00 --max-frames 100     # 빠른 확인
    python scripts/preprocess.py test00 --no-split           # bbox만
    python scripts/preprocess.py test00 --no-detect          # 분리만
"""


def detection_to_dict(
    detection,
) -> dict:

    return {
        "x1": float(detection.x1),
        "y1": float(detection.y1),
        "x2": float(detection.x2),
        "y2": float(detection.y2),
        "class_name": str(detection.class_name),
        "confidence": float(detection.confidence),
    }


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Split a raw mosaic video into camera videos "
            "and cache YOLO detections."
        )
    )

    parser.add_argument(
        "title",
        type=str,
        help=(
            "Raw video title "
            "(data/videos/raw/<title>.mp4, e.g. test00)"
        ),
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing split videos / detections",
    )

    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Process only the first N frames (quick test)",
    )

    parser.add_argument(
        "--no-split",
        action="store_true",
        help="Do not save split camera videos",
    )

    parser.add_argument(
        "--no-detect",
        action="store_true",
        help="Do not run YOLO",
    )

    parser.add_argument(
        "--fourcc",
        type=str,
        default="mp4v",
        help=(
            "Codec for split videos (default: mp4v). "
            "mp4v is readable by OpenCV, "
            "but not playable in most browsers."
        ),
    )

    parser.add_argument(
        "--print-interval",
        type=int,
        default=100,
    )

    return parser.parse_args()


def main() -> None:

    args = parse_args()

    if args.no_split and args.no_detect:
        sys.exit(
            "Nothing to do: both --no-split and --no-detect are set."
        )

    try:

        video = load_video(
            args.title
        )

    except FileNotFoundError as error:

        sys.exit(str(error))

    capture = cv2.VideoCapture(
        str(video.video_path)
    )

    if not capture.isOpened():
        sys.exit(
            f"Failed to open video: {video.video_path}"
        )

    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(capture.get(cv2.CAP_PROP_FPS)) or 30.0
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))

    if args.max_frames is not None:
        frame_count = min(
            frame_count,
            args.max_frames,
        )

    rects = video.crop_rects(
        width,
        height,
    )

    camera_ids = list(rects.keys())

    # -----------------------------------------------------
    # Outputs
    # -----------------------------------------------------

    split_paths = {
        camera_id: video.split_dir / f"{camera_id}.mp4"
        for camera_id in camera_ids
    }

    detections_path = (
        video.detections_dir / "detections.jsonl"
    )

    temp_detections_path = (
        video.detections_dir / "detections.jsonl.tmp"
    )

    metadata_path = (
        video.detections_dir / "metadata.json"
    )

    existing = []

    if not args.no_split:
        existing += [
            path
            for path in split_paths.values()
            if path.exists()
        ]

    if not args.no_detect and detections_path.exists():
        existing.append(detections_path)

    if existing and not args.overwrite:
        sys.exit(
            "Output already exists (use --overwrite):\n"
            + "\n".join(f"  {path}" for path in existing)
        )

    print()
    print("======================================")
    print("MOSAIC PREPROCESSING")
    print("======================================")
    print(f"Video   : {video.video_path.relative_to(ROOT)}")
    print(
        f"Source  : {width}x{height}, {fps:.2f} fps, "
        f"{frame_count} frames, grid {video.rows}x{video.cols}"
    )

    for camera_id, (x1, y1, x2, y2) in rects.items():
        print(
            f"  {camera_id}: x[{x1}:{x2}] y[{y1}:{y2}] "
            f"-> {x2 - x1}x{y2 - y1}"
        )

    if not args.no_split:
        print(f"Split   : {video.split_dir.relative_to(ROOT)}/")

    if not args.no_detect:
        print(f"Detect  : {detections_path.relative_to(ROOT)}")

    print("======================================")
    print()

    # -----------------------------------------------------
    # Writers / detector
    # -----------------------------------------------------

    writers: dict[str, cv2.VideoWriter] = {}

    if not args.no_split:

        video.split_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        fourcc = cv2.VideoWriter_fourcc(
            *args.fourcc
        )

        for camera_id, (x1, y1, x2, y2) in rects.items():

            writer = cv2.VideoWriter(
                str(split_paths[camera_id]),
                fourcc,
                fps,
                (x2 - x1, y2 - y1),
            )

            if not writer.isOpened():
                sys.exit(
                    f"Failed to create writer: "
                    f"{split_paths[camera_id]} (fourcc={args.fourcc})"
                )

            writers[camera_id] = writer

    detector = None
    output_file = None

    if not args.no_detect:

        detector = VehicleDetector(
            DETECTION_CONFIG_PATH
        )

        video.detections_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_file = temp_detections_path.open(
            "w",
            encoding="utf-8",
            buffering=1024 * 1024,
        )

    # -----------------------------------------------------
    # Main loop: read once -> crop -> write + detect
    # -----------------------------------------------------

    processed = 0
    total_detections = 0
    view_recorder = ViewModeRecorder(camera_ids, *load_letterbox())
    started_at = time.perf_counter()
    success = False

    try:

        while processed < frame_count:

            ok, frame = capture.read()

            if not ok:
                break

            crops = [
                np.ascontiguousarray(
                    frame[y1:y2, x1:x2]
                )
                for x1, y1, x2, y2 in rects.values()
            ]

            view_recorder.add(
                processed,
                dict(zip(camera_ids, crops)),
            )

            for camera_id, crop in zip(camera_ids, crops):

                writer = writers.get(camera_id)

                if writer is not None:
                    writer.write(crop)

            if detector is not None:

                all_detections = detector.detect_batch(
                    crops
                )

                cameras = {
                    camera_id: [
                        detection_to_dict(detection)
                        for detection in detections
                    ]
                    for camera_id, detections
                    in zip(camera_ids, all_detections)
                }

                total_detections += sum(
                    len(items)
                    for items in cameras.values()
                )

                output_file.write(
                    json.dumps(
                        {
                            "frame_index": processed,
                            "timestamp": processed / fps,
                            "cameras": cameras,
                        },
                        separators=(",", ":"),
                    )
                    + "\n"
                )

            processed += 1

            if (
                args.print_interval > 0
                and
                processed % args.print_interval == 0
            ):
                elapsed = time.perf_counter() - started_at

                print(
                    f"  {processed} / {frame_count} frames | "
                    f"{processed / elapsed:.2f} frames/s | "
                    f"detections {total_detections}"
                )

        success = processed > 0

    except KeyboardInterrupt:

        print()
        print("Interrupted.")

    finally:

        capture.release()

        for writer in writers.values():
            writer.release()

        if output_file is not None:
            output_file.close()

    elapsed = time.perf_counter() - started_at

    if not success:

        if temp_detections_path.exists():
            temp_detections_path.unlink()

        sys.exit(
            "Preprocessing failed or was interrupted. "
            "Detection cache was not saved."
        )

    # -----------------------------------------------------
    # Finalize detections
    # -----------------------------------------------------

    if detector is not None:

        temp_detections_path.replace(
            detections_path
        )

        # 축소 모드(좌우 검은 띠) 프레임 기록. server.py가 전체 화면 좌표로 되돌린다.
        view_recorder.finish().save(
            video.detections_dir / VIEW_MODES_FILENAME,
            processed,
        )

        metadata = {
            "format_version": 2,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "title": video.name,
            "source_video": video.video_path.relative_to(ROOT).as_posix(),
            "source_size": [width, height],
            "fps": fps,
            "frame_count": processed,
            "camera_ids": camera_ids,
            "total_detections": total_detections,
            "elapsed_seconds": elapsed,
            "model": detector.config.get("model", {}),
            "inference": detector.config.get("inference", {}),
            "layout": {
                **video.layout.to_dict(),
                "crop_rects": {
                    camera_id: list(rect)
                    for camera_id, rect in rects.items()
                },
            },
            "split_videos": (
                {
                    camera_id: path.relative_to(ROOT).as_posix()
                    for camera_id, path in split_paths.items()
                }
                if writers
                else {}
            ),
        }

        with metadata_path.open(
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                metadata,
                file,
                ensure_ascii=False,
                indent=2,
            )

    print()
    print("======================================")
    print("PREPROCESSING COMPLETE")
    print("======================================")
    print(f"Frames      : {processed}")
    print(f"Elapsed     : {elapsed:.1f} sec ({processed / elapsed:.2f} frames/s)")

    if writers:
        print(f"Split videos: {video.split_dir.relative_to(ROOT)}/ ({len(writers)} files)")

    if detector is not None:
        print(f"Detections  : {total_detections} -> {detections_path.relative_to(ROOT)}")

    print("======================================")


if __name__ == "__main__":
    main()
