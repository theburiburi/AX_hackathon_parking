from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass

from src.video import VIDEO_FPS, MosaicVideo

from .factory import Detection, create_tracker, load_tracking_config
from .local_tracker import LocalTracker, TrackedDetection


"""
detections.jsonl 의 한 프레임을 카메라별 Local Tracker에 넣는 공통 코드.

웹 tracking 엔진(engine.py)과 스크립트(입출차 감지, 경로 프리뷰)가
같은 방법으로 tracker를 돌리도록 여기서만 구현한다.
"""


@dataclass
class TrackedFrame:
    """
    한 프레임의 카메라별 검출(tracker 입력)과 추적 결과.
    """

    frame_index: int
    timestamp: float
    detections: dict[str, list[Detection]]
    tracked: dict[str, list[TrackedDetection]]


def track_frame(
    trackers: dict[str, LocalTracker],
    frame_data: dict,
) -> TrackedFrame:
    """
    detections.jsonl 한 줄(frame_data)을 trackers의 카메라마다 넣는다.
    """

    frame_index = int(frame_data["frame_index"])

    timestamp = float(
        frame_data.get(
            "timestamp",
            frame_index / VIDEO_FPS,
        )
    )

    cameras = frame_data.get("cameras", {})

    detections = {
        camera_id: [
            Detection.from_dict(item)
            for item in cameras.get(camera_id, [])
        ]
        for camera_id in trackers
    }

    tracked = {
        camera_id: tracker.update(
            detections=detections[camera_id],
            timestamp=timestamp,
        )
        for camera_id, tracker in trackers.items()
    }

    return TrackedFrame(
        frame_index=frame_index,
        timestamp=timestamp,
        detections=detections,
        tracked=tracked,
    )


def create_trackers(
    video: MosaicVideo,
    camera_ids: list[str] | None = None,
    config: dict | None = None,
) -> dict[str, LocalTracker]:
    """
    영상의 카메라별 Local Tracker (칸 크기에 맞춘 *_px 설정).
    config를 주면 config/tracking.yaml 을 다시 읽지 않는다.
    """

    if config is None:
        config = load_tracking_config()

    return {
        camera_id: create_tracker(
            camera_id,
            video.cell_rects[camera_id],
            config=config,
        )
        for camera_id in (camera_ids or video.camera_ids)
    }


def run_tracking(
    video: MosaicVideo,
    camera_ids: list[str] | None = None,
) -> Iterator[TrackedFrame]:
    """
    영상의 detections.jsonl 을 처음부터 끝까지 추적하며 프레임마다 결과를 내보낸다.
    camera_ids를 주면 그 카메라만 추적한다.
    """

    trackers = create_trackers(
        video,
        camera_ids,
    )

    with (video.detections_dir / "detections.jsonl").open(
        "r",
        encoding="utf-8",
    ) as file:

        for line in file:

            yield track_frame(
                trackers,
                json.loads(line),
            )
