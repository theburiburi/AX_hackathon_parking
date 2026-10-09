from __future__ import annotations

import argparse
import inspect
import json
import math
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
import yaml


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )

from src.mosaic import GATE_LOG_ROOT, load_video  # noqa: E402
from src.tracking import LocalTracker  # noqa: E402


"""
차단기 카메라(cam01)에서 입차 / 출차를 자동 감지해 기록을 만든다.

1. data/detections/<title>/detections.jsonl 에서 카메라의 bbox를 읽는다.
2. server.py와 같은 Local Tracker(config/tracking.yaml)로 차량을 추적한다.
3. 차량 bbox가 config/gate.yaml 의 네모 감지 박스(입차용 / 출차용)와
   일정 비율 이상 겹치고, 진행 방향이 박스의 direction과 맞으면 입차(IN) / 출차(OUT)로 기록한다.
   (같은 차량은 박스마다 한 번만 기록)
4. 웹 GATE LOG가 읽는 형식으로 data/gate_logs/<title>.json 에 저장한다.

예:
    python scripts/detect_gate_events.py test01
    python scripts/detect_gate_events.py test01 --preview            # 구역 확인 이미지
    python scripts/detect_gate_events.py test01 --start-time "2026-10-01 07:31:44"
    python scripts/detect_gate_events.py test00 --overwrite          # 기존 기록 덮어쓰기
"""


GATE_CONFIG_PATH = ROOT / "config" / "gate.yaml"
TRACKING_CONFIG_PATH = ROOT / "config" / "tracking.yaml"


@dataclass
class Detection:
    x1: float
    y1: float
    x2: float
    y2: float
    class_name: str
    confidence: float


@dataclass
class Zone:
    """
    네모 감지 박스 (x1, y1, x2, y2). 차량 bbox와 같은 형식.
    """

    type: str
    label: str
    box: tuple[float, float, float, float]
    direction: np.ndarray


def load_yaml(
    path: Path,
) -> dict:

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:

        return yaml.safe_load(file) or {}


def load_zones(
    config: dict,
) -> list[Zone]:

    zones = []

    for item in config.get("zones", []):

        direction = np.asarray(
            item["direction"],
            dtype=np.float64,
        )

        norm = float(np.linalg.norm(direction))

        if norm <= 0:
            raise ValueError(
                f"zone {item['type']}: direction must not be zero"
            )

        bx1, by1, bx2, by2 = (float(v) for v in item["box"])

        if bx2 <= bx1 or by2 <= by1:
            raise ValueError(
                f"zone {item['type']}: box must be [x1, y1, x2, y2] with x1 < x2, y1 < y2"
            )

        zones.append(
            Zone(
                type=str(item["type"]),
                label=str(item.get("label", item["type"])),
                box=(bx1, by1, bx2, by2),
                direction=direction / norm,
            )
        )

    if not zones:
        raise ValueError(
            f"No zones in {GATE_CONFIG_PATH}"
        )

    return zones


def overlap_ratio(
    bbox: tuple[float, float, float, float],
    zone: Zone,
) -> float:
    """
    감지 박스 중 차량 bbox와 겹친 넓이의 비율 (0 ~ 1).
    박스 넓이 기준이라 차량 bbox 크기와 관계없이 같은 기준으로 판정한다.
    """

    x1, y1, x2, y2 = bbox
    bx1, by1, bx2, by2 = zone.box

    box_area = (bx2 - bx1) * (by2 - by1)

    w = max(0.0, min(x2, bx2) - max(x1, bx1))
    h = max(0.0, min(y2, by2) - max(y1, by1))

    return w * h / box_area


def create_tracker(
    camera_id: str,
) -> LocalTracker:
    """
    server.py와 같은 설정(config/tracking.yaml)으로 Local Tracker를 만든다.
    """

    config = load_yaml(
        TRACKING_CONFIG_PATH
    ).get(
        "local_tracking",
        {},
    )

    accepted = set(
        inspect.signature(LocalTracker.__init__).parameters
    )

    params = {
        key: value
        for key, value in config.items()
        if key in accepted
    }

    params["print_transitions"] = False

    return LocalTracker(
        camera_id=camera_id,
        **params,
    )


def display_path(
    path: Path,
) -> str:

    try:
        return str(path.relative_to(ROOT))

    except ValueError:
        return str(path)


def format_time(
    start_time: datetime | None,
    frame: int,
    fps: float,
) -> str:

    seconds = round(frame / fps, 3)

    if start_time is not None:

        value = start_time + timedelta(milliseconds=round(seconds * 1000))

        return value.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    minutes, remaining = divmod(seconds, 60)
    hours, minutes = divmod(int(minutes), 60)

    return f"{hours:02d}:{minutes:02d}:{remaining:06.3f}"


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Detect gate IN / OUT events from cached detections "
            "and write a gate log for the web viewer."
        )
    )

    parser.add_argument(
        "title",
        type=str,
        help="Video title (data/detections/<title>/ must exist)",
    )

    parser.add_argument(
        "--start-time",
        type=str,
        default=None,
        help=(
            "Wall-clock time of frame 0, e.g. '2026-10-01 07:31:44'. "
            "Without it, times are written as video elapsed time."
        ),
    )

    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output path (default: data/gate_logs/<title>.json)",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing gate log",
    )

    parser.add_argument(
        "--preview",
        action="store_true",
        help=(
            "Save an image with zones and detected event positions "
            "to outputs/gate_zones_<title>.jpg"
        ),
    )

    return parser.parse_args()


def save_preview(
    video,
    camera_id: str,
    zones: list[Zone],
    events: list[dict],
    paths: dict[int, list[tuple[float, float]]],
    output_path: Path,
) -> None:
    """
    카메라 칸에 구역, 이벤트가 난 차량의 이동 경로, 이벤트 위치를 그린다.
    """

    capture = cv2.VideoCapture(
        str(video.video_path)
    )

    frame_index = (
        events[0]["frame"]
        if events
        else 0
    )

    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)

    ok, mosaic = capture.read()

    capture.release()

    if not ok:
        print("[WARN] preview: failed to read video frame")
        return

    x1, y1, x2, y2 = video.crop_rects(
        mosaic.shape[1],
        mosaic.shape[0],
    )[camera_id]

    scale = 2

    image = cv2.resize(
        mosaic[y1:y2, x1:x2],
        None,
        fx=scale,
        fy=scale,
    )

    colors = {
        "IN": (0, 220, 0),
        "OUT": (0, 140, 255),
    }

    for zone in zones:

        color = colors.get(zone.type, (255, 255, 0))

        bx1, by1, bx2, by2 = (int(v * scale) for v in zone.box)

        overlay = image.copy()
        cv2.rectangle(overlay, (bx1, by1), (bx2, by2), color, -1)
        image = cv2.addWeighted(overlay, 0.2, image, 0.8, 0)
        cv2.rectangle(image, (bx1, by1), (bx2, by2), color, 2)

        center = np.array([(bx1 + bx2) / 2, (by1 + by2) / 2])
        arrow_end = center + zone.direction * 60

        cv2.arrowedLine(
            image,
            tuple(int(v) for v in center),
            tuple(int(v) for v in arrow_end),
            color,
            2,
            tipLength=0.3,
        )

        cv2.putText(
            image,
            # OpenCV putText는 한글을 그리지 못하므로 type만 표시
            f"{zone.type} box",
            (bx1, by1 - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
        )

    for event in events:

        path = paths.get(event["track_id"], [])

        for (px, py), (qx, qy) in zip(path, path[1:]):
            cv2.line(
                image,
                (int(px * scale), int(py * scale)),
                (int(qx * scale), int(qy * scale)),
                (0, 0, 255),
                2,
            )

        ex, ey = event["position"]

        bx1, by1, bx2, by2 = (int(v * scale) for v in event["bbox"])

        cv2.rectangle(
            image,
            (bx1, by1),
            (bx2, by2),
            colors.get(event["type"], (255, 255, 255)),
            1,
        )

        cv2.circle(
            image,
            (int(ex * scale), int(ey * scale)),
            7,
            colors.get(event["type"], (255, 255, 255)),
            -1,
        )

        cv2.putText(
            image,
            f"{event['type']} f{event['frame']}",
            (int(ex * scale) + 10, int(ey * scale) - 6),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            2,
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    cv2.imwrite(str(output_path), image)

    print(f"Preview : {display_path(output_path)}")


def main() -> None:

    args = parse_args()

    gate_config = load_yaml(
        GATE_CONFIG_PATH
    )

    camera_id = str(
        gate_config.get("camera_id", "cam01")
    )

    zones = load_zones(
        gate_config
    )

    min_frames = int(
        gate_config.get("min_frames_in_zone", 3)
    )

    direction_window_sec = float(
        gate_config.get("direction_window_sec", 0.5)
    )

    min_speed = float(
        gate_config.get("min_speed_px_per_sec", 10.0)
    )

    min_overlap = float(
        gate_config.get("min_overlap_ratio", 0.1)
    )

    try:
        video = load_video(args.title)

    except FileNotFoundError as error:
        sys.exit(str(error))

    detections_path = (
        video.detections_dir / "detections.jsonl"
    )

    if not detections_path.exists():
        sys.exit(
            f"Detections not found: {detections_path}\n"
            f"Run: python scripts/preprocess.py {video.name}"
        )

    if camera_id not in video.camera_ids:
        sys.exit(
            f"{camera_id} is not in config/mosaic.yaml"
        )

    output_path = (
        Path(args.output)
        if args.output
        else GATE_LOG_ROOT / f"{video.name}.json"
    )

    if not output_path.is_absolute():
        output_path = ROOT / output_path

    if output_path.exists() and not args.overwrite:
        sys.exit(
            f"Gate log already exists (use --overwrite or --output): "
            f"{output_path}"
        )

    start_time = None

    if args.start_time:

        try:
            start_time = datetime.fromisoformat(
                args.start_time
            )

        except ValueError:
            sys.exit(
                f"Invalid --start-time: {args.start_time} "
                "(e.g. '2026-10-01 07:31:44')"
            )

    tracker = create_tracker(
        camera_id
    )

    # -----------------------------------------------------
    # Tracking + zone check
    # -----------------------------------------------------

    fps = 30.0
    window = max(1, int(round(direction_window_sec * fps)))

    # track_id -> 최근 위치 (frame, x, y)
    history: dict[int, deque] = {}

    # (track_id, zone index) -> 박스와 연속으로 겹친 프레임 수 / 첫 겹침 프레임
    inside_count: dict[tuple[int, int], int] = {}
    inside_since: dict[tuple[int, int], int] = {}

    # 이미 기록한 (track_id, zone index)
    fired: set[tuple[int, int]] = set()

    # 미리보기용 전체 경로
    paths: dict[int, list[tuple[float, float]]] = {}

    events = []
    frame_count = 0

    with detections_path.open(
        "r",
        encoding="utf-8",
    ) as file:

        for line in file:

            data = json.loads(line)

            frame = int(data["frame_index"])
            timestamp = float(data.get("timestamp", frame / fps))

            if frame > 0 and timestamp > 0:
                fps = frame / timestamp

            detections = [
                Detection(
                    x1=float(item["x1"]),
                    y1=float(item["y1"]),
                    x2=float(item["x2"]),
                    y2=float(item["y2"]),
                    class_name=str(item["class_name"]),
                    confidence=float(item["confidence"]),
                )
                for item in data["cameras"].get(camera_id, [])
            ]

            tracked = tracker.update(
                detections=detections,
                timestamp=timestamp,
            )

            frame_count += 1

            for item in tracked:

                track = item.track
                track_id = int(track.local_id)

                x = float(track.ground_x)
                y = float(track.ground_y)

                bbox = (
                    float(track.x1),
                    float(track.y1),
                    float(track.x2),
                    float(track.y2),
                )

                samples = history.setdefault(
                    track_id,
                    deque(maxlen=window + 1),
                )

                samples.append((frame, x, y))

                paths.setdefault(track_id, []).append((x, y))

                # 진행 방향 = 최근 window 동안의 이동 벡터 (px/s)
                velocity = None

                if len(samples) >= 2:

                    f0, x0, y0 = samples[0]
                    dt = (frame - f0) / fps

                    if dt > 0:
                        velocity = np.array(
                            [(x - x0) / dt, (y - y0) / dt]
                        )

                for zone_index, zone in enumerate(zones):

                    key = (track_id, zone_index)

                    if key in fired:
                        continue

                    inside = overlap_ratio(bbox, zone) > min_overlap

                    if not inside:
                        inside_count.pop(key, None)
                        inside_since.pop(key, None)
                        continue

                    inside_count[key] = inside_count.get(key, 0) + 1
                    inside_since.setdefault(key, frame)

                    if inside_count[key] < min_frames:
                        continue

                    if velocity is None:
                        continue

                    speed_along = float(
                        np.dot(velocity, zone.direction)
                    )

                    if speed_along < min_speed:
                        continue

                    fired.add(key)

                    event_frame = inside_since[key]

                    events.append(
                        {
                            "frame": event_frame,
                            "time": format_time(start_time, event_frame, fps),
                            "type": zone.type,
                            "label": zone.label,
                            "plate": None,
                            "detail": (
                                f"{camera_id} L{track_id:03d} · "
                                f"{track.class_name} · "
                                f"{math.hypot(*velocity):.0f}px/s"
                            ),
                            "track_id": track_id,
                            "position": [round(x, 1), round(y, 1)],
                            "bbox": [round(v, 1) for v in bbox],
                        }
                    )

    events.sort(key=lambda event: event["frame"])

    # -----------------------------------------------------
    # Save
    # -----------------------------------------------------

    log = {
        "video": video.name,
        "description": (
            "scripts/detect_gate_events.py 가 자동 감지한 입출차 기록. "
            "구역 설정: config/gate.yaml"
        ),
        "start_time": (
            start_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            if start_time
            else None
        ),
        "fps": round(fps, 3),
        "gate": {
            "id": gate_config.get("gate", {}).get("id", "GATE"),
            "name": gate_config.get("gate", {}).get("name", "차단기"),
            "camera_id": camera_id,
        },
        "events": events,
    }

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_path.open(
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            log,
            file,
            ensure_ascii=False,
            indent=2,
        )

    counts = {
        zone.type: sum(1 for event in events if event["type"] == zone.type)
        for zone in zones
    }

    print()
    print("======================================")
    print("GATE EVENTS")
    print("======================================")
    print(f"Video   : {video.name} ({frame_count} frames, {camera_id})")
    print(
        "Events  : "
        + ", ".join(f"{key} {value}" for key, value in counts.items())
    )

    for event in events:
        print(
            f"  frame {event['frame']:>6} | {event['time']} | "
            f"{event['type']:<3} {event['label']} | {event['detail']}"
        )

    print(f"Saved   : {display_path(output_path)}")

    if args.preview:
        save_preview(
            video,
            camera_id,
            zones,
            events,
            paths,
            ROOT / "outputs" / f"gate_zones_{video.name}.jpg",
        )

    print("======================================")


if __name__ == "__main__":
    main()
