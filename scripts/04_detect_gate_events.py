from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )

from src.content_fill import fill_width  # noqa: E402
from src.gate import GateDetector, Zone, load_gate_config  # noqa: E402
from src.tracking.runner import run_tracking  # noqa: E402
from src.video import VIDEO_FPS, display_path, load_video  # noqa: E402


"""
차단기 카메라(cam01)에서 입차 / 출차를 자동 감지해 기록을 만든다.

1. data/<title>/detections.jsonl 에서 카메라의 bbox를 읽는다.
2. server.py와 같은 Local Tracker(config/tracking.yaml)로 차량을 추적한다.
3. 차량 bbox가 config/gate.yaml 의 네모 감지 박스(입차용 / 출차용)와
   일정 비율 이상 겹치고, 겹침 비율이 커지면서(박스 안으로 들어오는 중)
   박스의 direction 쪽으로 움직이면 입차(IN) / 출차(OUT)로 기록한다.
   (외길이라 속도는 보지 않는다)
   (같은 차량은 박스마다 한 번만 기록)
4. 웹 GATE LOG가 읽는 형식으로 data/<title>/gate_log.json 에 저장한다.

예:
    python scripts/04_detect_gate_events.py test01
    python scripts/04_detect_gate_events.py test01 --preview            # 구역 확인 이미지
    python scripts/04_detect_gate_events.py test01 --start-time "2026-10-01 07:31:44"
    python scripts/04_detect_gate_events.py test00 --overwrite          # 기존 기록 덮어쓰기
"""


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
        help="Video title (data/<title>/detections.jsonl must exist)",
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
        help="Output path (default: data/<title>/gate_log.json)",
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
            "to outputs/<title>/gate_zones.jpg"
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

    x1, y1, x2, y2 = video.cell_rects[camera_id]

    # 칸 크기와 관계없이 폭 1280 px 이미지로 만든다.
    scale = 1280 / (x2 - x1)

    # detections.jsonl 과 같이 칸 좌우 여백을 없애고 늘린 이미지 기준
    cell, _ = fill_width(
        mosaic[y1:y2, x1:x2]
    )

    image = cv2.resize(
        cell,
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

    gate_config = load_gate_config()

    camera_id = str(
        gate_config.get("camera_id", "cam01")
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
            f"Run: python scripts/01_detect_vehicles.py {video.name}"
        )

    if camera_id not in video.camera_ids:
        sys.exit(
            f"{camera_id} is not in config/mosaic.yaml"
        )

    # 박스는 reference_size 칸 기준이므로 실제 칸 크기 비율만큼 늘린다.
    cx1, cy1, cx2, cy2 = video.cell_rects[camera_id]

    detector = GateDetector.from_config(
        gate_config,
        (cx1, cy1, cx2, cy2),
    )

    zones = detector.zones
    scale_x, scale_y = detector.scale
    reference_width, reference_height = detector.reference_size

    output_path = (
        Path(args.output)
        if args.output
        else video.gate_log_path
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

    # -----------------------------------------------------
    # Tracking (src/tracking/runner.py) + 입출차 판정 (src/gate.py)
    # -----------------------------------------------------

    fps = VIDEO_FPS  # 모든 영상 30 fps

    # 미리보기용 전체 경로
    paths: dict[int, list[tuple[float, float]]] = {}

    events = []
    frame_count = 0

    for result in run_tracking(video, [camera_id]):

        tracked = result.tracked[camera_id]

        frame_count += 1

        for item in tracked:
            paths.setdefault(int(item.track.local_id), []).append(
                (float(item.track.ground_x), float(item.track.ground_y))
            )

        for event in detector.update(result.frame_index, tracked):

            x, y = event.position

            events.append(
                {
                    "frame": event.frame,
                    "time": format_time(start_time, event.frame, fps),
                    "type": event.zone.type,
                    "label": event.zone.label,
                    "plate": None,
                    "detail": (
                        f"{camera_id} L{event.track_id:03d} · "
                        f"{event.class_name} · "
                        f"겹침 {event.start_ratio:.2f}→{event.ratio:.2f}"
                    ),
                    "track_id": event.track_id,
                    "position": [round(x, 1), round(y, 1)],
                    "bbox": [round(v, 1) for v in event.bbox],
                }
            )

    events.sort(key=lambda event: event["frame"])

    # -----------------------------------------------------
    # Save
    # -----------------------------------------------------

    log = {
        "video": video.name,
        "description": (
            "scripts/04_detect_gate_events.py 가 자동 감지한 입출차 기록. "
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
        f"Cell    : {cx2 - cx1}x{cy2 - cy1} "
        f"(boxes x{scale_x:g} / x{scale_y:g} from "
        f"{reference_width:g}x{reference_height:g})"
    )
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
            ROOT / "outputs" / video.name / "gate_zones.jpg",
        )

    print("======================================")


if __name__ == "__main__":
    main()
