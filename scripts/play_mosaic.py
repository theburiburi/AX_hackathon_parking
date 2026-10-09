from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]


"""
모자이크 영상 + YOLO detection 캐시를 프레임 번호로 맞춰 재생한다.

- 영상 프레임 i 에는 detections.jsonl 의 frame_index i 결과를 그린다.
  (영상과 bbox가 같은 프레임 번호이므로 항상 동기화된다)
- camera_id가 cell_r{행}c{열} 형식이면 그 칸 위치로 bbox를 옮겨 그린다.
  (split_mosaic.py로 분리한 영상은 칸과 같은 해상도이므로 크기 변환이 필요 없다)

예:
    python scripts/play_mosaic.py data/videos/1009.mp4 \\
        --detections data/detections/1009/detections.jsonl

    # 화면 없이 bbox가 그려진 영상만 저장
    python scripts/play_mosaic.py data/videos/1009.mp4 \\
        --detections data/detections/1009/detections.jsonl \\
        --save outputs/1009_bbox.mp4 --no-show

키:
    Space : 재생 / 일시정지
    A / D : 1프레임 뒤 / 앞 (일시정지 중)
    J / L : 30프레임 뒤 / 앞
    Q/ESC : 종료
"""


WINDOW = "Mosaic Playback"

DISPLAY_MAX_WIDTH = 1600

CELL_PATTERN = re.compile(
    r"^cell_r(\d+)c(\d+)$"
)

CLASS_COLORS = {
    "car": (0, 200, 255),
    "truck": (255, 120, 0),
    "bus": (255, 0, 200),
    "motorcycle": (0, 255, 120),
}

DEFAULT_COLOR = (255, 255, 255)


def resolve(
    path: str,
) -> Path:

    result = Path(path)

    if not result.is_absolute():
        result = ROOT / result

    return result


class DetectionCache:
    """
    detections.jsonl 을 줄 단위 offset으로 색인해서
    임의의 frame_index를 바로 읽는다.
    """

    def __init__(
        self,
        path: Path,
    ):
        self.path = path

        self.offsets: list[int] = []

        with path.open("rb") as file:

            while True:

                offset = file.tell()

                if not file.readline():
                    break

                self.offsets.append(offset)

        self.file = path.open("rb")

    def __len__(
        self,
    ) -> int:

        return len(self.offsets)

    def read(
        self,
        frame_index: int,
    ) -> dict:

        if not 0 <= frame_index < len(self.offsets):
            return {}

        self.file.seek(
            self.offsets[frame_index]
        )

        data = json.loads(
            self.file.readline()
        )

        if int(data.get("frame_index", -1)) != frame_index:
            raise RuntimeError(
                f"Detection cache is not sequential "
                f"at frame {frame_index}"
            )

        return data.get(
            "cameras",
            {},
        )


def cell_origin(
    camera_id: str,
    cell_width: int,
    cell_height: int,
) -> tuple[int, int] | None:

    match = CELL_PATTERN.match(camera_id)

    if match is None:
        return None

    row = int(match.group(1)) - 1
    col = int(match.group(2)) - 1

    return (
        int(round(col * cell_width)),
        int(round(row * cell_height)),
    )


def draw_detections(
    frame: np.ndarray,
    cameras: dict,
    cell_width: float,
    cell_height: float,
    show_label: bool,
) -> int:

    count = 0

    for camera_id, detections in cameras.items():

        origin = cell_origin(
            camera_id,
            cell_width,
            cell_height,
        )

        if origin is None:
            continue

        offset_x, offset_y = origin

        for item in detections:

            x1 = int(round(item["x1"])) + offset_x
            y1 = int(round(item["y1"])) + offset_y
            x2 = int(round(item["x2"])) + offset_x
            y2 = int(round(item["y2"])) + offset_y

            class_name = item.get(
                "class_name",
                "",
            )

            color = CLASS_COLORS.get(
                class_name,
                DEFAULT_COLOR,
            )

            cv2.rectangle(
                frame,
                (x1, y1),
                (x2, y2),
                color,
                2,
            )

            if show_label:

                cv2.putText(
                    frame,
                    f"{class_name} {item.get('confidence', 0.0):.2f}",
                    (x1, max(12, y1 - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.4,
                    color,
                    1,
                    cv2.LINE_AA,
                )

            count += 1

    return count


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Play a mosaic video with cached "
            "YOLO detections drawn on each cell."
        )
    )

    parser.add_argument(
        "video",
        type=str,
        help="Mosaic video path",
    )

    parser.add_argument(
        "--detections",
        type=str,
        required=True,
        help="detections.jsonl path",
    )

    parser.add_argument(
        "--rows",
        type=int,
        default=3,
    )

    parser.add_argument(
        "--cols",
        type=int,
        default=3,
    )

    parser.add_argument(
        "--save",
        type=str,
        default=None,
        help="Save rendered video (mp4v) to this path",
    )

    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Do not open a window (use with --save)",
    )

    parser.add_argument(
        "--no-label",
        action="store_true",
        help="Draw boxes only, without class/confidence text",
    )

    return parser.parse_args()


def main() -> None:

    args = parse_args()

    video_path = resolve(args.video)
    detections_path = resolve(args.detections)

    if not video_path.exists():
        sys.exit(f"Video not found: {video_path}")

    if not detections_path.exists():
        sys.exit(f"Detections not found: {detections_path}")

    if args.no_show and not args.save:
        sys.exit("--no-show requires --save")

    capture = cv2.VideoCapture(
        str(video_path)
    )

    if not capture.isOpened():
        sys.exit(f"Failed to open video: {video_path}")

    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(capture.get(cv2.CAP_PROP_FPS)) or 30.0
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))

    cache = DetectionCache(
        detections_path
    )

    cell_width = width / args.cols
    cell_height = height / args.rows

    print(
        f"Video      : {video_path.name} "
        f"({width}x{height}, {fps:.2f} fps, {frame_count} frames)"
    )

    print(
        f"Detections : {detections_path} "
        f"({len(cache)} frames)"
    )

    if len(cache) != frame_count:
        print(
            "[WARN] Frame count differs between video "
            "and detections. Frames without detections "
            "are shown without boxes."
        )

    writer = None

    if args.save:

        save_path = resolve(args.save)

        save_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        writer = cv2.VideoWriter(
            str(save_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (width, height),
        )

        print(f"Save       : {save_path}")

    scale = min(
        1.0,
        DISPLAY_MAX_WIDTH / width,
    )

    if not args.no_show:

        cv2.namedWindow(
            WINDOW,
            cv2.WINDOW_AUTOSIZE,
        )

        print(
            "Keys: Space play/pause | A/D step | "
            "J/L -/+30 frames | Q quit"
        )

    delay_ms = max(
        1,
        int(round(1000.0 / fps)),
    )

    paused = False
    frame_index = 0
    next_index = 0

    # 저장 영상에는 각 프레임을 순서대로 한 번씩만 기록한다.
    # (일시정지 / 뒤로 이동 중에는 기록하지 않음)
    last_written = -1

    while True:

        # 순서대로 재생 중이면 그냥 다음 프레임을 읽고,
        # 이동했을 때만 seek한다.
        if next_index != frame_index + 1 or next_index == 0:

            capture.set(
                cv2.CAP_PROP_POS_FRAMES,
                next_index,
            )

        success, frame = capture.read()

        if not success:
            break

        frame_index = next_index

        box_count = draw_detections(
            frame,
            cache.read(frame_index),
            cell_width,
            cell_height,
            show_label=not args.no_label,
        )

        if (
            writer is not None
            and
            frame_index == last_written + 1
        ):
            writer.write(frame)
            last_written = frame_index

        if args.no_show:

            next_index = frame_index + 1

            if frame_index % 100 == 0:
                print(f"  {frame_index} / {frame_count}")

            continue

        display = (
            cv2.resize(
                frame,
                None,
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_AREA,
            )
            if scale < 1.0
            else frame
        )

        cv2.putText(
            display,
            f"frame {frame_index}/{frame_count - 1} | "
            f"{box_count} boxes"
            f"{' | PAUSED' if paused else ''}",
            (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

        cv2.imshow(
            WINDOW,
            display,
        )

        key = cv2.waitKey(
            0 if paused else delay_ms
        ) & 0xFF

        if key in (ord("q"), 27):
            break

        if key == ord(" "):
            paused = not paused
            next_index = frame_index if paused else frame_index + 1
            continue

        if key == ord("a"):
            paused = True
            next_index = max(0, frame_index - 1)
            continue

        if key == ord("d"):
            paused = True
            next_index = min(frame_count - 1, frame_index + 1)
            continue

        if key == ord("j"):
            next_index = max(0, frame_index - 30)
            continue

        if key == ord("l"):
            next_index = min(frame_count - 1, frame_index + 30)
            continue

        next_index = (
            frame_index
            if paused
            else frame_index + 1
        )

    capture.release()

    if writer is not None:
        writer.release()
        print("Saved.")

    if not args.no_show:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
