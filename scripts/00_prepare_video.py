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

from src.content_fill import fill_width  # noqa: E402
from src.video import VIDEO_FPS, display_path, load_video  # noqa: E402
from src.video_writer import FFmpegWriter, pick_encoder  # noqa: E402


"""
1단계: 원본 모자이크 정리.

data/raw_video/<title>.mp4 를 한 번 읽으면서 카메라 칸마다
좌우 검은 여백을 잘라내고 가로로 늘려 칸을 꽉 채운 뒤 (src/content_fill.py)

  - data/<title>/cams/<camera_id>.mp4  카메라 영상 7개 (YOLO 입력, 01_detect_vehicles.py)
  - data/<title>/mosaic.mp4            늘린 칸으로 다시 합친 모자이크 (웹 재생)
  - data/<title>/content.jsonl         프레임별 원래 화면 가로 범위 {camera_id: [left, right]}

를 만든다. CCTV 녹화 장비가 차가 없을 때 화면을 가로로 줄여 여백이 생기므로,
여백을 없애 같은 차량의 bbox 위치 / 폭이 프레임마다 바뀌지 않게 한다.
카메라가 없는 칸(mosaic.yaml 에 없는 칸)은 원본 그대로 둔다.

영상은 H.264(ffmpeg)로 저장한다. 웹(브라우저)에서 재생할 수 있고,
키프레임이 1초마다 있어 재생바 이동이 빠르다.
GPU 인코더(h264_nvenc)를 쓸 수 있으면 쓰고, 아니면 libx264.

예:
    python scripts/00_prepare_video.py test01
    python scripts/00_prepare_video.py test01 --overwrite
    python scripts/00_prepare_video.py test01 --max-frames 300     # 빠른 확인
"""


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Remove side bars of each camera cell, then save camera videos "
            "and a rebuilt mosaic for the web."
        )
    )

    parser.add_argument(
        "title",
        type=str,
        help="Video title (data/raw_video/<title>.mp4)",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing outputs",
    )

    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Process only the first N frames (quick test)",
    )

    parser.add_argument(
        "--encoder",
        type=str,
        default="auto",
        help="ffmpeg video encoder: auto (default), h264_nvenc, libx264",
    )

    parser.add_argument(
        "--quality",
        type=int,
        default=18,
        help=(
            "Camera videos (YOLO input) CRF, "
            "lower = better quality (default: 18)"
        ),
    )

    parser.add_argument(
        "--mosaic-quality",
        type=int,
        default=26,
        help=(
            "Mosaic (web playback) CRF / CQ (default: 26, "
            "about the same size as the source)"
        ),
    )

    parser.add_argument(
        "--print-interval",
        type=int,
        default=300,
    )

    return parser.parse_args()


def temp_path(
    path: Path,
) -> Path:
    """
    작업 중 파일 (완료되면 원래 이름으로 바꾼다). 확장자는 유지한다 (ffmpeg 형식 판단).
    """

    return path.with_name(f"{path.stem}.tmp{path.suffix}")


def main() -> None:

    args = parse_args()

    try:
        video = load_video(args.title)

    except FileNotFoundError as error:
        sys.exit(str(error))

    capture = cv2.VideoCapture(str(video.video_path))

    if not capture.isOpened():
        sys.exit(f"Failed to open video: {video.video_path}")

    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = VIDEO_FPS  # 모든 영상 30 fps
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))

    if args.max_frames is not None:
        frame_count = min(frame_count, args.max_frames)

    rects = video.crop_rects(width, height)
    camera_ids = list(rects)

    cam_paths = {
        camera_id: video.split_dir / f"{camera_id}.mp4"
        for camera_id in camera_ids
    }

    outputs = [
        video.mosaic_path,
        video.content_path,
        *cam_paths.values(),
    ]

    existing = [path for path in outputs if path.exists()]

    if existing and not args.overwrite:
        sys.exit(
            "Output already exists (use --overwrite):\n"
            + "\n".join(f"  {display_path(path)}" for path in existing)
        )

    encoder = pick_encoder(args.encoder)

    print()
    print("======================================")
    print("PREPARE VIDEO")
    print("======================================")
    print(f"Video   : {display_path(video.video_path)}")
    print(f"Source  : {width}x{height}, {fps:.2f} fps, {frame_count} frames")
    print(
        f"Encoder : mosaic {encoder} (quality {args.mosaic_quality}), "
        f"cameras libx264 (quality {args.quality})"
    )
    print(f"Mosaic  : {display_path(video.mosaic_path)}")
    print(f"Cameras : {display_path(video.split_dir)}/ ({len(camera_ids)})")
    print("======================================")
    print()

    mosaic_writer = FFmpegWriter(
        temp_path(video.mosaic_path),
        width,
        height,
        fps,
        encoder,
        args.mosaic_quality,
    )

    # 칸 영상은 작아서 CPU 인코더로 충분하다 (GPU 인코더 동시 세션 수 제한 회피)
    cam_writers = {
        camera_id: FFmpegWriter(
            temp_path(cam_paths[camera_id]),
            x2 - x1,
            y2 - y1,
            fps,
            "libx264",
            args.quality,
        )
        for camera_id, (x1, y1, x2, y2) in rects.items()
    }

    content_temp = temp_path(video.content_path)
    content_file = content_temp.open("w", encoding="utf-8")

    filled_counts = {camera_id: 0 for camera_id in camera_ids}

    processed = 0
    started_at = time.perf_counter()
    success = False

    try:

        while processed < frame_count:

            ok, frame = capture.read()

            if not ok:
                break

            content = {}

            for camera_id, (x1, y1, x2, y2) in rects.items():

                filled, columns = fill_width(
                    frame[y1:y2, x1:x2]
                )

                if columns != (0, x2 - x1):
                    filled_counts[camera_id] += 1

                    # 모자이크의 같은 칸에 늘린 이미지를 다시 넣는다
                    frame[y1:y2, x1:x2] = filled

                cam_writers[camera_id].write(filled)

                content[camera_id] = list(columns)

            mosaic_writer.write(frame)

            content_file.write(
                json.dumps(
                    {
                        "frame_index": processed,
                        "content": content,
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
                    f"{processed / elapsed:.1f} frames/s"
                )

        success = processed > 0

    except KeyboardInterrupt:

        print()
        print("Interrupted.")

    finally:

        capture.release()
        content_file.close()

        errors = []

        for writer in [mosaic_writer, *cam_writers.values()]:

            try:
                writer.close()

            except RuntimeError as error:
                errors.append(str(error))

        if errors:
            success = False
            print("\n".join(errors))

    temps = [temp_path(path) for path in outputs]

    if not success:

        for path in temps:
            path.unlink(missing_ok=True)

        sys.exit("Preparing failed or was interrupted. Outputs were not saved.")

    for path in outputs:
        temp_path(path).replace(path)

    elapsed = time.perf_counter() - started_at

    # metadata.json 의 "prepare" 부분만 갱신 (검출 정보는 01_detect_vehicles.py)
    metadata = {}

    if video.metadata_path.exists():

        with video.metadata_path.open("r", encoding="utf-8") as file:
            metadata = json.load(file)

    metadata.update(
        {
            "format_version": 4,
            "title": video.name,
            "source_video": video.video_path.relative_to(ROOT).as_posix(),
            "source_size": [width, height],
            "fps": fps,
            "frame_count": processed,
            "camera_ids": camera_ids,
            "layout": {
                **video.layout.to_dict(),
                "crop_rects": {
                    camera_id: list(rect)
                    for camera_id, rect in rects.items()
                },
            },
            "prepare": {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": elapsed,
                "mosaic_encoder": encoder,
                "mosaic_quality": args.mosaic_quality,
                "cams_encoder": "libx264",
                "cams_quality": args.quality,
                "mosaic": video.mosaic_path.relative_to(ROOT).as_posix(),
                "cams": {
                    camera_id: path.relative_to(ROOT).as_posix()
                    for camera_id, path in cam_paths.items()
                },
                "content": video.content_path.relative_to(ROOT).as_posix(),
                # 카메라별 여백을 없애고 늘린 프레임 수
                "filled_frames": filled_counts,
            },
        }
    )

    with video.metadata_path.open("w", encoding="utf-8") as file:
        json.dump(metadata, file, ensure_ascii=False, indent=2)

    print()
    print("======================================")
    print("PREPARE COMPLETE")
    print("======================================")
    print(f"Frames  : {processed}")
    print(f"Elapsed : {elapsed:.1f} sec ({processed / elapsed:.1f} frames/s)")

    for camera_id in camera_ids:
        print(
            f"  {camera_id}: side bars removed in "
            f"{filled_counts[camera_id]} / {processed} frames"
        )

    print(f"Mosaic  : {display_path(video.mosaic_path)}")
    print("Next    : python scripts/01_detect_vehicles.py " + video.name)
    print("======================================")


if __name__ == "__main__":
    main()
