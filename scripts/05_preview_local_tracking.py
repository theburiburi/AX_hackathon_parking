from __future__ import annotations

import argparse
import colorsys
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )

from src.calibration import CameraProjector  # noqa: E402
from src.content_fill import fill_width  # noqa: E402
from src.video import MAP_DIR, display_path, load_video  # noqa: E402
from src.tracking.runner import run_tracking  # noqa: E402


"""
Local Tracker 결과를 영상을 재생하지 않고 이미지로 확인한다.

1. data/<title>/detections.jsonl 을 처음부터 끝까지
   카메라마다 server.py와 같은 Local Tracker(config/tracking.yaml)로 추적한다.
2. 카메라 7개: 카메라 칸 이미지 위에 track별 이동 경로(bbox 바닥 중앙점)를 그린다.
   - 움직인 track (has_moved): 색 선 + 시작점(원) + 끝점(화살표) + Local ID
   - 움직이지 않은 track: 회색 점 (주차 / 정지 차량)
3. BEV 지도 1장: 움직인 track의 경로를 calibration으로 투영해 카메라별 색으로 겹쳐 그린다.
4. outputs/<title>/local_tracking/ 에 camXX.jpg 7장 + bev.jpg 를 저장한다.

배경은 카메라마다 차량이 가장 많이 검출된 프레임을 쓴다.
(CCTV 저장 영상은 차가 없을 때 화면이 작아지므로 확장된 상태의 프레임을 고른다)

예:
    python scripts/05_preview_local_tracking.py test01
    python scripts/05_preview_local_tracking.py test02 --min-frames 30
"""


# 웹(web/app.js CAMERA_COLORS)과 같은 카메라 색 (BGR)
CAMERA_COLORS = {
    "cam01": (59, 59, 255),
    "cam02": (0, 152, 255),
    "cam03": (59, 235, 255),
    "cam05": (101, 223, 52),
    "cam06": (255, 217, 0),
    "cam07": (255, 118, 76),
    "cam08": (255, 76, 227),
}

# 카메라 이미지 폭 (칸 크기와 관계없이 이 폭으로 그린다)
CAMERA_IMAGE_WIDTH = 1280


@dataclass
class TrackPath:
    camera_id: str
    local_id: int
    class_name: str
    first_frame: int
    last_frame: int = 0
    has_moved: bool = False
    points: list[tuple[float, float]] = field(default_factory=list)
    states: set[str] = field(default_factory=set)


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Draw local tracking paths of every camera "
            "and on the BEV map."
        )
    )

    parser.add_argument(
        "title",
        type=str,
        help="Video title (data/<title>/detections.jsonl must exist)",
    )

    parser.add_argument(
        "--min-frames",
        type=int,
        default=15,
        help="Skip moved tracks shorter than this (default: 15 frames)",
    )

    return parser.parse_args()


def track_color(
    local_id: int,
) -> tuple[int, int, int]:
    """
    Local ID마다 구분되는 밝은 색 (BGR).
    """

    hue = (local_id * 0.618033988749895) % 1.0

    r, g, b = colorsys.hsv_to_rgb(hue, 0.85, 1.0)

    return int(b * 255), int(g * 255), int(r * 255)


def collect_paths(
    video,
) -> tuple[dict[str, dict[int, TrackPath]], dict[str, int], int]:
    """
    전체 프레임을 추적해(src/tracking/runner.py) 카메라별 track 경로와
    카메라별 '검출이 가장 많은 프레임'을 돌려준다.
    """

    paths: dict[str, dict[int, TrackPath]] = {
        camera_id: {}
        for camera_id in video.camera_ids
    }

    best_frame = {camera_id: 0 for camera_id in video.camera_ids}
    best_count = {camera_id: -1 for camera_id in video.camera_ids}

    frame_count = 0

    for result in run_tracking(video):

        frame = result.frame_index

        for camera_id in video.camera_ids:

            count = len(result.detections[camera_id])

            if count > best_count[camera_id]:
                best_count[camera_id] = count
                best_frame[camera_id] = frame

            for item in result.tracked[camera_id]:

                track = item.track

                path = paths[camera_id].setdefault(
                    int(track.local_id),
                    TrackPath(
                        camera_id=camera_id,
                        local_id=int(track.local_id),
                        class_name=str(track.class_name),
                        first_frame=frame,
                    ),
                )

                path.last_frame = frame
                path.has_moved = path.has_moved or bool(track.has_moved)
                path.points.append(
                    (float(track.ground_x), float(track.ground_y))
                )
                path.states.add(track.state.value)

        frame_count += 1

    return paths, best_frame, frame_count


def read_frame(
    video_path: Path,
    frame_index: int,
):

    capture = cv2.VideoCapture(str(video_path))
    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)

    ok, frame = capture.read()

    capture.release()

    return frame if ok else None


def draw_arrow_end(
    image,
    points: np.ndarray,
    color: tuple[int, int, int],
    thickness: int,
) -> None:
    """
    경로 끝에 진행 방향 화살표를 그린다 (마지막 몇 점의 방향).
    """

    if len(points) < 2:
        return

    end = points[-1]
    start = points[max(0, len(points) - 8)]

    if np.hypot(*(end - start)) < 3:
        return

    cv2.arrowedLine(
        image,
        tuple(int(v) for v in start),
        tuple(int(v) for v in end),
        color,
        thickness,
        tipLength=0.5,
    )


def draw_label(
    image,
    text: str,
    position: tuple[int, int],
    color: tuple[int, int, int],
    scale: float = 0.45,
) -> None:

    x, y = position

    (width, height), _ = cv2.getTextSize(
        text,
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        1,
    )

    cv2.rectangle(
        image,
        (x, y - height - 4),
        (x + width + 4, y + 2),
        (0, 0, 0),
        -1,
    )

    cv2.putText(
        image,
        text,
        (x + 2, y - 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        color,
        1,
        cv2.LINE_AA,
    )


def draw_header(
    image,
    lines: list[str],
) -> None:

    for index, text in enumerate(lines):

        draw_label(
            image,
            text,
            (10, 26 + index * 24),
            (255, 255, 255),
            0.6,
        )


def draw_camera(
    camera_id: str,
    background,
    tracks: list[TrackPath],
    min_frames: int,
    background_frame: int,
):

    height, width = background.shape[:2]

    scale = CAMERA_IMAGE_WIDTH / width

    image = cv2.resize(background, None, fx=scale, fy=scale)

    # 경로가 잘 보이도록 배경을 어둡게
    image = (image * 0.55).astype(np.uint8)

    moved = [
        track
        for track in tracks
        if track.has_moved and len(track.points) >= min_frames
    ]

    stationary = [
        track
        for track in tracks
        if not track.has_moved
    ]

    # 움직이지 않은 track: 위치 중앙값에 회색 점
    for track in stationary:

        x, y = np.median(np.asarray(track.points), axis=0) * scale

        cv2.circle(image, (int(x), int(y)), 3, (150, 150, 150), -1)

    for track in moved:

        color = track_color(track.local_id)

        points = np.asarray(track.points) * scale

        cv2.polylines(
            image,
            [points.astype(np.int32).reshape(-1, 1, 2)],
            False,
            color,
            2,
            cv2.LINE_AA,
        )

        cv2.circle(image, tuple(int(v) for v in points[0]), 5, color, 2)

        draw_arrow_end(image, points, color, 2)

        draw_label(
            image,
            f"L{track.local_id:03d}",
            (int(points[-1][0]) + 6, int(points[-1][1])),
            color,
        )

    draw_header(
        image,
        [
            f"{camera_id}  tracks {len(tracks)}  "
            f"moved {len(moved)}  stationary {len(stationary)}",
            f"background frame {background_frame}  "
            f"(o start, > end, grey dot = not moved)",
        ],
    )

    return image, len(moved)


def draw_bev(
    paths: dict[str, dict[int, TrackPath]],
    projectors: dict[str, CameraProjector],
    min_frames: int,
):

    image = cv2.imread(str(MAP_DIR / "map.png"))

    if image is None:
        raise RuntimeError(f"Failed to read {MAP_DIR / 'map.png'}")

    image = (image * 0.6).astype(np.uint8)

    with (MAP_DIR / "zones.json").open("r", encoding="utf-8") as file:
        zones = json.load(file)["zones"]

    for zone in zones:

        box = zone["bndbox"]

        cv2.rectangle(
            image,
            (box["xmin"], box["ymin"]),
            (box["xmax"], box["ymax"]),
            (200, 200, 200),
            1,
        )

        draw_label(
            image,
            zone["id"],
            (box["xmin"] + 2, box["ymin"] + 16),
            (200, 200, 200),
        )

    map_height, map_width = image.shape[:2]

    counts = {}

    for camera_id, camera_paths in paths.items():

        projector = projectors.get(camera_id)

        if projector is None:
            continue

        color = CAMERA_COLORS.get(camera_id, (255, 255, 255))

        count = 0

        for track in camera_paths.values():

            if not track.has_moved or len(track.points) < min_frames:
                continue

            projected = []

            for x, y in track.points:

                bx, by = projector.project(x, y)

                # 지도 밖으로 크게 튀는 점(지평선 근처)은 버린다
                if (
                    math.isfinite(bx)
                    and math.isfinite(by)
                    and -map_width <= bx <= 2 * map_width
                    and -map_height <= by <= 2 * map_height
                ):
                    projected.append((bx, by))

            if len(projected) < 2:
                continue

            points = np.asarray(projected)

            cv2.polylines(
                image,
                [points.astype(np.int32).reshape(-1, 1, 2)],
                False,
                color,
                2,
                cv2.LINE_AA,
            )

            cv2.circle(image, tuple(int(v) for v in points[0]), 4, color, 1)

            draw_arrow_end(image, points, color, 2)

            count += 1

        counts[camera_id] = count

    legend = [
        f"{camera_id}: {count} moved tracks"
        for camera_id, count in counts.items()
    ]

    for index, text in enumerate(legend):

        draw_label(
            image,
            text,
            (10, map_height - 12 - (len(legend) - 1 - index) * 22),
            CAMERA_COLORS.get(text.split(":")[0], (255, 255, 255)),
            0.55,
        )

    return image


def main() -> None:

    args = parse_args()

    try:
        video = load_video(args.title)

    except FileNotFoundError as error:
        sys.exit(str(error))

    detections_path = video.detections_dir / "detections.jsonl"

    if not detections_path.exists():
        sys.exit(
            f"Detections not found: {detections_path}\n"
            f"Run: python scripts/01_detect_vehicles.py {video.name}"
        )

    cell_rects = video.cell_rects

    projectors: dict[str, CameraProjector] = {}

    for camera_id in video.camera_ids:

        try:
            projectors[camera_id] = CameraProjector(
                camera_id,
                calibration_dir=video.calibration_dir,
            )

        except Exception as error:
            print(
                f"[WARN] {camera_id}: calibration not loaded, "
                f"skipped on BEV ({error})"
            )

    print(f"Tracking {video.name} ...")

    paths, best_frame, frame_count = collect_paths(
        video,
    )

    output_dir = ROOT / "outputs" / video.name / "local_tracking"

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    print()
    print("======================================")
    print("LOCAL TRACKING PREVIEW")
    print("======================================")
    print(f"Video   : {video.name} ({frame_count} frames)")

    for camera_id in video.camera_ids:

        frame = read_frame(
            video.video_path,
            best_frame[camera_id],
        )

        if frame is None:
            print(f"  {camera_id}: [WARN] failed to read frame")
            continue

        x1, y1, x2, y2 = cell_rects[camera_id]

        image, moved = draw_camera(
            camera_id,
            # detections.jsonl 과 같이 칸 좌우 여백을 없애고 늘린 이미지 기준
            fill_width(frame[y1:y2, x1:x2])[0],
            list(paths[camera_id].values()),
            args.min_frames,
            best_frame[camera_id],
        )

        output_path = output_dir / f"{camera_id}.jpg"

        cv2.imwrite(str(output_path), image)

        print(
            f"  {camera_id}: tracks {len(paths[camera_id]):3d}, "
            f"moved {moved:3d} -> {display_path(output_path)}"
        )

    bev = draw_bev(
        paths,
        projectors,
        args.min_frames,
    )

    bev_path = output_dir / "bev.jpg"

    cv2.imwrite(str(bev_path), bev)

    print(f"  bev  : {display_path(bev_path)}")
    print("======================================")


if __name__ == "__main__":
    main()
