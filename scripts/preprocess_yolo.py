from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import torch
import yaml


ROOT = Path(__file__).resolve().parents[1]

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


def load_yaml(
    path: Path,
) -> dict:
    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        data = yaml.safe_load(
            file
        )

    if data is None:
        return {}

    return data


def detect_scene_name(
    config: dict,
) -> str:
    videos = config.get(
        "videos",
        [],
    )

    if not videos:
        return "scene"

    first_path = videos[0].get(
        "path",
        "",
    )

    if not first_path:
        return "scene"

    path = Path(
        first_path
    )

    parent_name = (
        path.parent.name
    )

    if parent_name:
        return parent_name

    return "scene"


def detection_to_dict(
    detection,
) -> dict:
    return {
        "x1": float(
            detection.x1
        ),
        "y1": float(
            detection.y1
        ),
        "x2": float(
            detection.x2
        ),
        "y2": float(
            detection.y2
        ),
        "class_name": str(
            detection.class_name
        ),
        "confidence": float(
            detection.confidence
        ),
    }


def frame_result_to_dict(
    frame_index: int,
    timestamp: float,
    camera_ids: list[str],
    all_detections,
) -> dict:
    cameras = {}

    for (
        camera_id,
        detections,
    ) in zip(
        camera_ids,
        all_detections,
    ):
        cameras[
            camera_id
        ] = [
            detection_to_dict(
                detection
            )
            for detection
            in detections
        ]

    return {
        "frame_index": int(
            frame_index
        ),
        "timestamp": float(
            timestamp
        ),
        "cameras": cameras,
    }


def build_metadata(
    config: dict,
    camera_ids: list[str],
    scene_name: str,
    processed_frames: int,
    elapsed_seconds: float,
    total_detections: int,
) -> dict:
    model_config = config.get(
        "model",
        {},
    )

    inference_config = config.get(
        "inference",
        {},
    )

    videos = config.get(
        "videos",
        [],
    )

    source_videos = []

    for video in videos:
        source_videos.append(
            {
                "camera_id": video.get(
                    "camera_id"
                ),
                "path": video.get(
                    "path"
                ),
            }
        )

    average_sets_per_second = 0.0

    if elapsed_seconds > 0.0:
        average_sets_per_second = (
            processed_frames
            /
            elapsed_seconds
        )

    return {
        "format_version": 1,
        "created_at": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
        "scene_name": scene_name,
        "camera_ids": camera_ids,
        "camera_count": len(
            camera_ids
        ),
        "processed_frame_sets": int(
            processed_frames
        ),
        "total_detections": int(
            total_detections
        ),
        "elapsed_seconds": float(
            elapsed_seconds
        ),
        "average_sets_per_second": float(
            average_sets_per_second
        ),
        "model": {
            "weights": model_config.get(
                "weights"
            ),
            "device": model_config.get(
                "device"
            ),
        },
        "inference": {
            "imgsz": inference_config.get(
                "imgsz"
            ),
            "conf": inference_config.get(
                "conf"
            ),
            "iou": inference_config.get(
                "iou"
            ),
            "quantize": inference_config.get(
                "quantize"
            ),
            "batch_size": inference_config.get(
                "batch_size"
            ),
        },
        "source_videos": (
            source_videos
        ),
    }


def print_progress(
    frame_count: int,
    total_detections: int,
    started_at: float,
    camera_count: int,
) -> None:
    elapsed = (
        time.perf_counter()
        -
        started_at
    )

    if elapsed <= 0.0:
        sets_per_second = 0.0
    else:
        sets_per_second = (
            frame_count
            /
            elapsed
        )

    camera_frames_per_second = (
        sets_per_second
        *
        camera_count
    )

    print(
        f"[YOLO CACHE] "
        f"frame_sets={frame_count} | "
        f"detections={total_detections} | "
        f"sets/s={sets_per_second:.2f} | "
        f"camera_frames/s="
        f"{camera_frames_per_second:.2f}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run YOLO over all synchronized CCTV videos "
            "and cache detections to JSONL."
        )
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help=(
            "Output directory. "
            "Default: data/detections/<scene_name>"
        ),
    )

    parser.add_argument(
        "--scene-name",
        type=str,
        default=None,
        help=(
            "Override automatically detected scene name."
        ),
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help=(
            "Overwrite an existing detection cache."
        ),
    )

    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help=(
            "Process only this many synchronized frame sets. "
            "Useful for a quick test."
        ),
    )

    parser.add_argument(
        "--print-interval",
        type=int,
        default=100,
        help=(
            "Print progress every N synchronized frame sets."
        ),
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    config = load_yaml(
        CONFIG_PATH
    )

    videos = config.get(
        "videos",
        [],
    )

    if not videos:
        raise RuntimeError(
            "No videos configured in "
            f"{CONFIG_PATH}"
        )

    pipeline_config = config.get(
        "pipeline",
        {},
    )

    queue_size = int(
        pipeline_config.get(
            "queue_size",
            2,
        )
    )

    scene_name = (
        args.scene_name
        if args.scene_name
        else detect_scene_name(
            config
        )
    )

    if args.output_dir:
        output_dir = Path(
            args.output_dir
        )

        if not output_dir.is_absolute():
            output_dir = (
                ROOT
                /
                output_dir
            )

    else:
        output_dir = (
            ROOT
            / "data"
            / "detections"
            / scene_name
        )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        output_dir
        /
        "detections.jsonl"
    )

    temp_output_path = (
        output_dir
        /
        "detections.jsonl.tmp"
    )

    metadata_path = (
        output_dir
        /
        "metadata.json"
    )

    if (
        output_path.exists()
        and
        not args.overwrite
    ):
        raise FileExistsError(
            f"Detection cache already exists:\n"
            f"{output_path}\n\n"
            f"Use --overwrite to recreate it."
        )

    if temp_output_path.exists():
        temp_output_path.unlink()

    print()
    print(
        "======================================"
    )
    print(
        "YOLO PREPROCESSING"
    )
    print(
        "======================================"
    )

    print(
        f"Config       : "
        f"{CONFIG_PATH}"
    )

    print(
        f"Scene        : "
        f"{scene_name}"
    )

    print(
        f"Output       : "
        f"{output_path}"
    )

    print(
        f"Metadata     : "
        f"{metadata_path}"
    )

    print(
        f"Queue size   : "
        f"{queue_size}"
    )

    if args.max_frames is not None:
        print(
            f"Max frames   : "
            f"{args.max_frames}"
        )

    print(
        "======================================"
    )
    print()

    detector = VehicleDetector(
        CONFIG_PATH
    )

    reader = (
        SynchronizedVideoReader(
            video_configs=videos,
            root=ROOT,
            queue_size=queue_size,
        )
    )

    reader.print_info()

    print()
    print(
        "Starting YOLO preprocessing..."
    )
    print()

    processed_frames = 0
    total_detections = 0

    started_at = (
        time.perf_counter()
    )

    reader.start()

    success = False

    try:
        with temp_output_path.open(
            "w",
            encoding="utf-8",
            buffering=1024 * 1024,
        ) as output_file:

            while True:
                frame_set = (
                    reader.get()
                )

                if frame_set is None:
                    break

                all_detections = (
                    detector.detect_batch(
                        frame_set.frames
                    )
                )

                # 정확한 GPU 처리 시간 측정 및
                # 다음 반복 전에 CUDA 작업 완료 보장.
                torch.cuda.synchronize()

                frame_data = (
                    frame_result_to_dict(
                        frame_index=(
                            frame_set.frame_index
                        ),
                        timestamp=(
                            frame_set.timestamp
                        ),
                        camera_ids=(
                            reader.camera_ids
                        ),
                        all_detections=(
                            all_detections
                        ),
                    )
                )

                json.dump(
                    frame_data,
                    output_file,
                    ensure_ascii=False,
                    separators=(
                        ",",
                        ":",
                    ),
                )

                output_file.write(
                    "\n"
                )

                processed_frames += 1

                total_detections += sum(
                    len(
                        detections
                    )
                    for detections
                    in all_detections
                )

                if (
                    args.print_interval > 0
                    and
                    processed_frames
                    %
                    args.print_interval
                    ==
                    0
                ):
                    output_file.flush()

                    print_progress(
                        frame_count=(
                            processed_frames
                        ),
                        total_detections=(
                            total_detections
                        ),
                        started_at=(
                            started_at
                        ),
                        camera_count=(
                            len(
                                reader.camera_ids
                            )
                        ),
                    )

                if (
                    args.max_frames
                    is not None
                    and
                    processed_frames
                    >=
                    args.max_frames
                ):
                    break

        success = True

    except KeyboardInterrupt:
        print()
        print(
            "Interrupted by user."
        )

    finally:
        reader.stop()

    elapsed_seconds = (
        time.perf_counter()
        -
        started_at
    )

    print()

    if success:
        # 완전히 생성된 경우에만 최종 파일명으로 변경.
        if output_path.exists():
            output_path.unlink()

        temp_output_path.replace(
            output_path
        )

        metadata = (
            build_metadata(
                config=config,
                camera_ids=(
                    reader.camera_ids
                ),
                scene_name=(
                    scene_name
                ),
                processed_frames=(
                    processed_frames
                ),
                elapsed_seconds=(
                    elapsed_seconds
                ),
                total_detections=(
                    total_detections
                ),
            )
        )

        with metadata_path.open(
            "w",
            encoding="utf-8",
        ) as metadata_file:
            json.dump(
                metadata,
                metadata_file,
                ensure_ascii=False,
                indent=2,
            )

        print(
            "======================================"
        )
        print(
            "YOLO PREPROCESSING COMPLETE"
        )
        print(
            "======================================"
        )

        print(
            f"Frame sets       : "
            f"{processed_frames}"
        )

        print(
            f"Camera frames    : "
            f"{processed_frames * len(reader.camera_ids)}"
        )

        print(
            f"Detections       : "
            f"{total_detections}"
        )

        print(
            f"Elapsed          : "
            f"{elapsed_seconds:.2f} sec"
        )

        if elapsed_seconds > 0.0:
            sets_per_second = (
                processed_frames
                /
                elapsed_seconds
            )

            camera_frames_per_second = (
                sets_per_second
                *
                len(
                    reader.camera_ids
                )
            )

            print(
                f"Sets/s           : "
                f"{sets_per_second:.2f}"
            )

            print(
                f"Camera frames/s  : "
                f"{camera_frames_per_second:.2f}"
            )

        print(
            f"Detection cache  : "
            f"{output_path}"
        )

        print(
            f"Metadata         : "
            f"{metadata_path}"
        )

        print(
            "======================================"
        )

    else:
        print(
            "YOLO preprocessing was not completed."
        )

        if temp_output_path.exists():
            print(
                "Partial temporary cache remains at:"
            )

            print(
                temp_output_path
            )


if __name__ == "__main__":
    main()