"""Synchronized tiled player for multiple CCTV videos."""

import argparse
import math
from pathlib import Path
import sys
import time
from typing import Sequence

import cv2
import numpy as np

from .reader import SynchronizedVideoReader


TRACKBAR_STEP_MS = 100


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Play multiple CCTV files on one synchronized timeline."
    )
    parser.add_argument("--videos", nargs="+", required=True, type=Path, help="video paths")
    parser.add_argument(
        "--offsets",
        nargs="*",
        type=float,
        help="per-video seek offsets in seconds; positive values advance that video",
    )
    parser.add_argument("--columns", type=int, default=3, help="tile columns")
    parser.add_argument("--width", type=int, default=1280, help="combined window width")
    parser.add_argument("--height", type=int, default=900, help="combined window height")
    return parser.parse_args()


def _fit_tile(image: np.ndarray, width: int, height: int) -> np.ndarray:
    source_height, source_width = image.shape[:2]
    scale = min(width / source_width, height / source_height)
    target_width = max(1, int(round(source_width * scale)))
    target_height = max(1, int(round(source_height * scale)))
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    resized = cv2.resize(image, (target_width, target_height), interpolation=interpolation)
    tile = np.zeros((height, width, 3), dtype=np.uint8)
    x = (width - target_width) // 2
    y = (height - target_height) // 2
    tile[y : y + target_height, x : x + target_width] = resized
    return tile


def compose_video_grid(
    frames: Sequence[np.ndarray],
    labels: Sequence[str],
    width: int,
    height: int,
    columns: int,
    time_ms: float,
    playing: bool,
) -> np.ndarray:
    if not frames or len(frames) != len(labels):
        raise ValueError("frames and labels must be non-empty and have equal lengths")
    if columns < 1 or width < 320 or height < 240:
        raise ValueError("invalid grid dimensions or column count")
    status_height = 38
    rows = math.ceil(len(frames) / columns)
    tile_width = width // columns
    tile_height = (height - status_height) // rows
    canvas = np.zeros((height, width, 3), dtype=np.uint8)

    for index, (frame, label) in enumerate(zip(frames, labels)):
        row, column = divmod(index, columns)
        x = column * tile_width
        y = row * tile_height
        cell_width = width - x if column == columns - 1 else tile_width
        cell_height = height - status_height - y if row == rows - 1 else tile_height
        title_height = 26
        tile = _fit_tile(frame, cell_width, max(1, cell_height - title_height))
        canvas[y + title_height : y + cell_height, x : x + cell_width] = tile
        cv2.putText(
            canvas, label, (x + 8, y + 19), cv2.FONT_HERSHEY_SIMPLEX,
            0.52, (255, 255, 255), 1, cv2.LINE_AA,
        )

    seconds = time_ms / 1000.0
    state = "PLAY" if playing else "PAUSE"
    cv2.putText(
        canvas,
        f"{state}  {seconds:8.2f}s  | Space: play/pause  A/D: -/+5s  Q/ESC: quit",
        (12, height - 12),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return canvas


def run(args: argparse.Namespace) -> None:
    if args.offsets is not None and len(args.offsets) not in (0, len(args.videos)):
        raise ValueError("--offsets must contain exactly one value per video")
    offsets = args.offsets or [0.0] * len(args.videos)
    window = "Synchronized CCTV Player"

    with SynchronizedVideoReader(args.videos, offsets) as reader:
        duration_ms = reader.end_ms - reader.start_ms
        trackbar_max = max(1, int(duration_ms // TRACKBAR_STEP_MS))
        position_ms = reader.start_ms
        playing = True
        anchor_position_ms = position_ms
        anchor_wall_time = time.monotonic()
        requested_position: list[int | None] = [None]
        updating_trackbar = [False]

        cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE)

        def on_trackbar(value: int) -> None:
            if not updating_trackbar[0]:
                requested_position[0] = value

        cv2.createTrackbar("Time (0.1s)", window, 0, trackbar_max, on_trackbar)
        labels = [info.path.stem for info in reader.infos]

        while True:
            if requested_position[0] is not None:
                position_ms = min(
                    reader.end_ms,
                    reader.start_ms + requested_position[0] * TRACKBAR_STEP_MS,
                )
                requested_position[0] = None
                anchor_position_ms = position_ms
                anchor_wall_time = time.monotonic()
            elif playing:
                position_ms = anchor_position_ms + (time.monotonic() - anchor_wall_time) * 1000.0

            if position_ms >= reader.end_ms:
                position_ms = reader.end_ms - 0.001
                playing = False

            frames = reader.read_at(position_ms)
            grid = compose_video_grid(
                frames, labels, args.width, args.height, args.columns, position_ms, playing
            )
            cv2.imshow(window, grid)

            trackbar_value = min(
                trackbar_max, int((position_ms - reader.start_ms) // TRACKBAR_STEP_MS)
            )
            updating_trackbar[0] = True
            cv2.setTrackbarPos("Time (0.1s)", window, trackbar_value)
            updating_trackbar[0] = False

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break
            if key == ord(" "):
                playing = not playing
                anchor_position_ms = position_ms
                anchor_wall_time = time.monotonic()
            elif key == ord("a"):
                position_ms = max(reader.start_ms, position_ms - 5000.0)
                anchor_position_ms = position_ms
                anchor_wall_time = time.monotonic()
            elif key == ord("d"):
                position_ms = min(reader.end_ms - 0.001, position_ms + 5000.0)
                anchor_position_ms = position_ms
                anchor_wall_time = time.monotonic()

    cv2.destroyAllWindows()


def main() -> int:
    try:
        run(parse_args())
    except (FileNotFoundError, TypeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
