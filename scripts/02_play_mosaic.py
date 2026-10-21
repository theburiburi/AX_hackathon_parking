from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )

from src.video import VIDEO_FPS, default_title, load_video  # noqa: E402


"""
모자이크 영상(mosaic.mp4, 칸 좌우 여백을 없앤 것) + YOLO detection 캐시를 프레임 번호로 맞춰 재생한다.

- 영상 프레임 i 에는 detections.jsonl 의 frame_index i 결과를 그린다.
  (영상과 bbox가 같은 프레임 번호이므로 항상 동기화된다)
- bbox 좌표는 카메라(잘라낸 칸) 기준이므로,
  config/mosaic.yaml 의 칸 위치만큼 옮겨 그린다.

예:
    python scripts/02_play_mosaic.py                 # config/detection.yaml 의 video
    python scripts/02_play_mosaic.py test00

    # 화면 없이 bbox가 그려진 영상만 저장
    python scripts/02_play_mosaic.py test00 \\
        --save outputs/test00_bbox.mp4 --no-show

키:
    Space : 재생 / 일시정지
    A / D : 1프레임 뒤 / 앞 (일시정지 중)
    J / L : 30프레임 뒤 / 앞
    Q/ESC : 종료
"""


WINDOW = "Mosaic Playback"

DISPLAY_MAX_WIDTH = 1600

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


def draw_detections(
    frame: np.ndarray,
    cameras: dict,
    origins: dict[str, tuple[int, int]],
    show_label: bool,
) -> int:

    count = 0

    for camera_id, detections in cameras.items():

        origin = origins.get(
            camera_id
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
        "title",
        type=str,
        nargs="?",
        default=None,
        help=(
            "Video title (data/<title>/mosaic.mp4). "
            "Default: 'video' in config/detection.yaml"
        ),
    )

    parser.add_argument(
        "--detections",
        type=str,
        default=None,
        help=(
            "Override detections.jsonl path "
            "(default: data/<title>/detections.jsonl)"
        ),
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

    title = (
        args.title
        or
        default_title()
    )

    if not title:
        sys.exit(
            "No video given. Pass a title or set "
            "'video' in config/detection.yaml"
        )

    try:

        scene = load_video(
            title
        )

    except FileNotFoundError as error:

        sys.exit(str(error))

    # bbox는 칸 좌우 여백을 없앤 좌표이므로 같은 처리를 한 mosaic.mp4 위에 그린다
    video_path = scene.mosaic_path

    detections_path = (
        resolve(args.detections)
        if args.detections
        else scene.detections_dir / "detections.jsonl"
    )

    if not video_path.exists():
        sys.exit(
            f"Video not found: {video_path}\n"
            f"Run: python scripts/00_prepare_video.py {scene.name}"
        )

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
    fps = VIDEO_FPS  # 모든 영상 30 fps
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))

    cache = DetectionCache(
        detections_path
    )

    origins = {
        camera_id: (x1, y1)
        for camera_id, (x1, y1, x2, y2)
        in scene.crop_rects(width, height).items()
    }

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
            origins,
            show_label=not args.no_label,
        )

        for camera_id, (x, y) in origins.items():

            cv2.putText(
                frame,
                camera_id,
                (x + 8, y + 22),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
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
