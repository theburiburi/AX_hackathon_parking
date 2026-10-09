from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]


"""
모자이크(격자) 영상을 칸별 개별 영상으로 분리한다.

영상을 가로 cols 등분, 세로 rows 등분해서
각 칸을 cell_r{행}c{열}.mp4 로 저장한다. (행/열은 1부터)

모든 칸은 같은 프레임에서 잘라내므로
출력 영상끼리 프레임 번호가 정확히 일치한다.

예:
    python scripts/split_mosaic.py data/videos/1009.mp4
    python scripts/split_mosaic.py data/videos/1009.mp4 --skip-black
"""


# 칸 전체가 이 밝기 이하이면 빈 칸(검은 화면)으로 본다.
BLACK_MEAN_THRESHOLD = 5.0

# 빈 칸 판별에 사용할 앞부분 프레임 수
BLACK_CHECK_FRAMES = 30


def cell_bounds(
    size: int,
    count: int,
) -> list[tuple[int, int]]:
    """
    size를 count 등분한 [start, end) 구간 목록.
    나누어떨어지지 않으면 경계를 반올림해서
    전체 픽셀을 빠짐없이 덮는다.
    """

    edges = [
        int(round(index * size / count))
        for index in range(count + 1)
    ]

    return [
        (
            edges[index],
            edges[index + 1],
        )
        for index in range(count)
    ]


def find_black_cells(
    video_path: Path,
    cells: dict[str, tuple[int, int, int, int]],
) -> set[str]:

    capture = cv2.VideoCapture(
        str(video_path)
    )

    max_mean = {
        name: 0.0
        for name in cells
    }

    for _ in range(BLACK_CHECK_FRAMES):

        success, frame = capture.read()

        if not success:
            break

        for name, (x1, y1, x2, y2) in cells.items():

            max_mean[name] = max(
                max_mean[name],
                float(
                    np.mean(
                        frame[y1:y2, x1:x2]
                    )
                ),
            )

    capture.release()

    return {
        name
        for name, value in max_mean.items()
        if value <= BLACK_MEAN_THRESHOLD
    }


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Split a grid mosaic video "
            "into one video per cell."
        )
    )

    parser.add_argument(
        "input",
        type=str,
        help="Mosaic video path",
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
        "--output-dir",
        type=str,
        default=None,
        help=(
            "Default: <input folder>/<input name>_split"
        ),
    )

    parser.add_argument(
        "--skip-black",
        action="store_true",
        help=(
            "Do not write cells that are completely black "
            "(empty mosaic slots)."
        ),
    )

    parser.add_argument(
        "--fourcc",
        type=str,
        default="mp4v",
        help=(
            "Output codec FourCC (default: mp4v). "
            "mp4v is readable by OpenCV/YOLO, "
            "but not playable in most browsers."
        ),
    )

    return parser.parse_args()


def main() -> None:

    args = parse_args()

    input_path = Path(
        args.input
    )

    if not input_path.is_absolute():
        input_path = ROOT / input_path

    if not input_path.exists():
        sys.exit(
            f"Video not found: {input_path}"
        )

    capture = cv2.VideoCapture(
        str(input_path)
    )

    if not capture.isOpened():
        sys.exit(
            f"Failed to open video: {input_path}"
        )

    width = int(
        capture.get(cv2.CAP_PROP_FRAME_WIDTH)
    )

    height = int(
        capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
    )

    fps = float(
        capture.get(cv2.CAP_PROP_FPS)
    ) or 30.0

    frame_count = int(
        capture.get(cv2.CAP_PROP_FRAME_COUNT)
    )

    if args.output_dir:

        output_dir = Path(
            args.output_dir
        )

        if not output_dir.is_absolute():
            output_dir = ROOT / output_dir

    else:

        output_dir = (
            input_path.parent
            /
            f"{input_path.stem}_split"
        )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # name -> (x1, y1, x2, y2)
    cells: dict[str, tuple[int, int, int, int]] = {}

    for row, (y1, y2) in enumerate(
        cell_bounds(height, args.rows),
        start=1,
    ):

        for col, (x1, x2) in enumerate(
            cell_bounds(width, args.cols),
            start=1,
        ):

            cells[f"cell_r{row}c{col}"] = (
                x1,
                y1,
                x2,
                y2,
            )

    skipped: set[str] = set()

    if args.skip_black:

        skipped = find_black_cells(
            input_path,
            cells,
        )

    print(
        f"Input  : {input_path.name} "
        f"({width}x{height}, {fps:.2f} fps, "
        f"{frame_count} frames)"
    )

    print(
        f"Grid   : {args.rows} x {args.cols}"
    )

    print(
        f"Output : {output_dir}"
    )

    fourcc = cv2.VideoWriter_fourcc(
        *args.fourcc
    )

    writers: dict[str, cv2.VideoWriter] = {}

    for name, (x1, y1, x2, y2) in cells.items():

        if name in skipped:

            print(
                f"  {name}: skipped (black)"
            )

            continue

        path = output_dir / f"{name}.mp4"

        writer = cv2.VideoWriter(
            str(path),
            fourcc,
            fps,
            (
                x2 - x1,
                y2 - y1,
            ),
        )

        if not writer.isOpened():
            sys.exit(
                f"Failed to create writer: {path} "
                f"(fourcc={args.fourcc})"
            )

        writers[name] = writer

        print(
            f"  {name}: x[{x1}:{x2}] y[{y1}:{y2}] "
            f"-> {x2 - x1}x{y2 - y1}"
        )

    written = 0

    while True:

        success, frame = capture.read()

        if not success:
            break

        for name, writer in writers.items():

            x1, y1, x2, y2 = cells[name]

            writer.write(
                np.ascontiguousarray(
                    frame[y1:y2, x1:x2]
                )
            )

        written += 1

        if written % 300 == 0:
            print(
                f"  {written} / {frame_count} frames"
            )

    capture.release()

    for writer in writers.values():
        writer.release()

    print(
        f"Done: {written} frames x "
        f"{len(writers)} videos"
    )


if __name__ == "__main__":
    main()
