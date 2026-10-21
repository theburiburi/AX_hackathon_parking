from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )

from src.tracking.factory import load_tracking_config  # noqa: E402
from src.tracking.runner import create_trackers, track_frame  # noqa: E402
from src.video import default_title, load_video  # noqa: E402


"""
Local Tracker 상태(MOVING / STOPPED / PARKED)가 얼마나 왔다갔다 하는지 숫자로 본다.

data/<title>/detections.jsonl 을 처음부터 끝까지 추적하고 (영상 재생 없음)
설정 조합마다 아래를 출력한다.
  - 상태 전환 횟수
  - 짧은 구간(SHORT_SEC 미만) 만에 바뀐 전환 수 (MOVING -> 서 있음 이 많으면 멈춤 판정이 너무 쉬움)
  - 움직임(MOVING / ACTIVE) <-> 서 있음 전환이 FLIP_COUNT 회 이상인 track 수
  - 움직인 적이 있는 track(has_moved) 수

--set 으로 config/tracking.yaml 값을 바꿔 여러 조합을 한 번에 비교한다 (조합마다 --set 1개).
  python scripts/06_evaluate_track_states.py
  python scripts/06_evaluate_track_states.py --set stop_ratio=0.5 --set stop_ratio=0.5,stop_confirm_sec=2.0
"""


SHORT_SEC = 2.0
FLIP_COUNT = 4

# 움직이는 상태 이름 (tracker 버전에 따라 MOVING 또는 ACTIVE)
MOVING_STATES = ("MOVING", "ACTIVE")


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description="Local Tracker 상태 전환 통계",
    )

    parser.add_argument(
        "--title",
        default=None,
        help="data/<title> (기본: config/detection.yaml 의 video)",
    )

    parser.add_argument(
        "--set",
        dest="combos",
        action="append",
        default=[],
        help="key=value[,key=value...] 설정 조합 (여러 번 지정 가능)",
    )

    return parser.parse_args()


def parse_combo(text: str) -> dict:

    override = {}

    for item in text.split(","):

        if not item:
            continue

        key, value = item.split("=")
        override[key.strip()] = float(value)

    return override


def evaluate(video, frames: list[dict], config: dict) -> dict:

    trackers = create_trackers(
        video,
        config=config,
    )

    # track별 (지금 상태, 그 상태가 된 시각)
    last: dict[tuple[str, int], tuple[str, float]] = {}

    transitions = Counter()
    short = Counter()
    flips = Counter()
    moved = set()

    for frame_data in frames:

        frame = track_frame(trackers, frame_data)

        for camera_id, items in frame.tracked.items():

            for tracked in items:

                track = tracked.track
                key = (camera_id, track.local_id)
                state = track.state.value

                if track.has_moved:
                    moved.add(key)

                previous = last.get(key)

                if previous is None or previous[0] == state:
                    last.setdefault(key, (state, frame.timestamp))
                    continue

                name = f"{previous[0]}->{state}"
                transitions[name] += 1

                # STOPPED -> PARKED 는 정의상 짧을 수 없으므로 제외
                if (
                    name != "STOPPED->PARKED"
                    and frame.timestamp - previous[1] < SHORT_SEC
                ):
                    short[name] += 1

                if any(moving in name for moving in MOVING_STATES):
                    flips[key] += 1

                last[key] = (state, frame.timestamp)

    return {
        "transitions": dict(transitions),
        "short": dict(short),
        "flip_tracks": sum(1 for count in flips.values() if count >= FLIP_COUNT),
        "moved_tracks": len(moved),
        "tracks": len(last),
    }


def main() -> None:

    args = parse_args()

    video = load_video(args.title or default_title())

    with (video.detections_dir / "detections.jsonl").open(
        "r",
        encoding="utf-8",
    ) as file:
        frames = [json.loads(line) for line in file]

    base = load_tracking_config()
    base["print_transitions"] = False

    for combo in [""] + args.combos:

        result = evaluate(
            video,
            frames,
            dict(base, **parse_combo(combo)),
        )

        print(f"[{combo or 'tracking.yaml'}]")
        print(f"  전환: {result['transitions']}")
        print(f"  {SHORT_SEC:g}초 안에 바뀐 전환: {result['short']}")
        print(
            f"  MOVING 전환 {FLIP_COUNT}회 이상 track: {result['flip_tracks']}"
            f" / 움직인 track: {result['moved_tracks']} / 전체 track: {result['tracks']}",
            flush=True,
        )


if __name__ == "__main__":
    main()
