from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )

from src.detection.detector import VehicleDetector  # noqa: E402
from src.video import DETECTION_CONFIG_PATH, VIDEO_FPS, display_path, load_video  # noqa: E402


"""
2단계: 차량 검출.

00_prepare_video.py 가 만든 카메라 영상 7개(data/<title>/cams/<camera_id>.mp4)를
같은 프레임끼리 읽어 YOLO(config/detection.yaml)로 검출하고
data/<title>/detections.jsonl 에 저장한다.

bbox 좌표는 카메라 영상(여백을 없애고 늘린 칸) 기준 픽셀이다.
모든 카메라 영상이 같은 모자이크 프레임에서 만들어졌으므로
프레임 번호가 원본 / mosaic.mp4 와 정확히 일치한다.

서버가 켜져 있어도 실행할 수 있다 (끝나면 detections.jsonl 을 교체하고,
서버는 다음 요청 때 새 파일을 읽는다).

예:
    python scripts/01_detect_vehicles.py test01
    python scripts/01_detect_vehicles.py test01 --overwrite
    python scripts/01_detect_vehicles.py test01 --max-frames 300     # 빠른 확인
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
        description="Run YOLO on each camera video and cache detections."
    )

    parser.add_argument(
        "title",
        type=str,
        help="Video title (data/<title>/cams/ from 00_prepare_video.py)",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing detections",
    )

    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Process only the first N frames (quick test)",
    )

    parser.add_argument(
        "--print-interval",
        type=int,
        default=100,
    )

    return parser.parse_args()


def main() -> None:

    args = parse_args()

    try:
        video = load_video(args.title)

    except FileNotFoundError as error:
        sys.exit(str(error))

    cam_paths = {
        camera_id: video.split_dir / f"{camera_id}.mp4"
        for camera_id in video.camera_ids
    }

    missing = [path for path in cam_paths.values() if not path.exists()]

    if missing:
        sys.exit(
            "Camera videos not found:\n"
            + "\n".join(f"  {display_path(path)}" for path in missing)
            + f"\nRun: python scripts/00_prepare_video.py {video.name}"
        )

    detections_path = video.detections_dir / "detections.jsonl"
    temp_path = video.detections_dir / "detections.jsonl.tmp"

    if detections_path.exists() and not args.overwrite:
        sys.exit(
            f"Detections already exist (use --overwrite): "
            f"{display_path(detections_path)}"
        )

    captures = {
        camera_id: cv2.VideoCapture(str(path))
        for camera_id, path in cam_paths.items()
    }

    frame_counts = {
        camera_id: int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        for camera_id, capture in captures.items()
    }

    fps = VIDEO_FPS  # 모든 영상 30 fps

    frame_count = min(frame_counts.values())

    if args.max_frames is not None:
        frame_count = min(frame_count, args.max_frames)

    print()
    print("======================================")
    print("DETECT VEHICLES")
    print("======================================")
    print(f"Cameras : {display_path(video.split_dir)}/ ({len(cam_paths)})")
    print(f"Frames  : {frame_count} ({fps:.2f} fps)")

    if len(set(frame_counts.values())) > 1:
        print(f"[WARN] camera video frame counts differ: {frame_counts}")

    print(f"Output  : {display_path(detections_path)}")
    print("======================================")
    print()

    detector = VehicleDetector(DETECTION_CONFIG_PATH)

    processed = 0
    total_detections = 0
    started_at = time.perf_counter()
    success = False

    output_file = temp_path.open(
        "w",
        encoding="utf-8",
        buffering=1024 * 1024,
    )

    try:

        while processed < frame_count:

            frames = []

            for camera_id in video.camera_ids:

                ok, frame = captures[camera_id].read()

                if not ok:
                    break

                frames.append(frame)

            if len(frames) != len(video.camera_ids):
                break

            all_detections = detector.detect_batch(frames)

            cameras = {
                camera_id: [
                    detection_to_dict(detection)
                    for detection in detections
                ]
                for camera_id, detections in zip(
                    video.camera_ids,
                    all_detections,
                )
            }

            total_detections += sum(len(items) for items in cameras.values())

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

            if args.print_interval > 0 and processed % args.print_interval == 0:

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

        output_file.close()

        for capture in captures.values():
            capture.release()

    if not success:

        temp_path.unlink(missing_ok=True)

        sys.exit("Detection failed or was interrupted. Detections were not saved.")

    temp_path.replace(detections_path)

    elapsed = time.perf_counter() - started_at

    # metadata.json 의 "detection" 부분만 갱신 (영상 정보는 00_prepare_video.py)
    metadata = {}

    if video.metadata_path.exists():

        with video.metadata_path.open("r", encoding="utf-8") as file:
            metadata = json.load(file)

    metadata["detection"] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": elapsed,
        "frame_count": processed,
        "total_detections": total_detections,
        "model": detector.config.get("model", {}),
        "inference": detector.config.get("inference", {}),
        "detections": detections_path.relative_to(ROOT).as_posix(),
    }

    with video.metadata_path.open("w", encoding="utf-8") as file:
        json.dump(metadata, file, ensure_ascii=False, indent=2)

    print()
    print("======================================")
    print("DETECTION COMPLETE")
    print("======================================")
    print(f"Frames     : {processed}")
    print(f"Elapsed    : {elapsed:.1f} sec ({processed / elapsed:.2f} frames/s)")
    print(f"Detections : {total_detections} -> {display_path(detections_path)}")
    print("======================================")


if __name__ == "__main__":
    main()
