"""
detections.jsonl 한 프레임을 카메라별 tracker에 넣기 (src/tracking/runner.py).
"""

from src.tracking.factory import create_tracker
from src.tracking.runner import track_frame


def box(x1, y1, x2, y2):

    return {
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
        "class_name": "car",
        "confidence": 0.9,
    }


def test_track_frame_keeps_ids_across_frames():

    trackers = {
        "cam01": create_tracker("cam01"),
        "cam02": create_tracker("cam02"),
    }

    first = track_frame(
        trackers,
        {
            "frame_index": 0,
            "timestamp": 0.0,
            "cameras": {
                "cam01": [box(100, 100, 160, 140)],
                # cam02: 검출 없음
            },
        },
    )

    assert first.frame_index == 0
    assert len(first.detections["cam01"]) == 1
    assert first.detections["cam02"] == []
    assert len(first.tracked["cam01"]) == 1

    second = track_frame(
        trackers,
        {
            "frame_index": 1,
            "cameras": {"cam01": [box(102, 100, 162, 140)]},
        },
    )

    # timestamp 가 없으면 30 fps 기준
    assert second.timestamp == 1 / 30

    # 조금 움직인 같은 차량은 같은 Local ID
    assert (
        second.tracked["cam01"][0].track.local_id
        == first.tracked["cam01"][0].track.local_id
    )
