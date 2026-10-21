"""
입출차 판정 (src/gate.py GateDetector).
"""

from types import SimpleNamespace

from src.gate import GateDetector, load_zones


ZONES = load_zones(
    {
        "zones": [
            {
                "type": "IN",
                "label": "입차",
                "box": [100, 100, 200, 150],  # 100 x 50
                "direction": [1.0, 0.0],      # 오른쪽으로 들어온다
            },
        ],
    }
)


def tracked(track_id, x1, y1, x2, y2):
    """
    Local Tracker 결과 1개 (GateDetector가 쓰는 값만).
    """

    track = SimpleNamespace(
        local_id=track_id,
        class_name="car",
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
        ground_x=(x1 + x2) / 2,
        ground_y=y2,
    )

    return SimpleNamespace(track=track)


def run(frames):
    """
    frames: 프레임마다 tracked 목록. 확정된 이벤트 전체를 돌려준다.
    """

    detector = GateDetector(
        ZONES,
        min_overlap_ratio=0.3,
        min_overlap_increase=0.2,
        min_frames=3,
    )

    events = []

    for frame, items in enumerate(frames):
        events += detector.update(frame, items)

    return events


def test_car_entering_box_in_direction_is_recorded_once():

    # 왼쪽에서 오른쪽으로 박스 안에 들어오는 차 (bbox 80 x 50)
    frames = [
        [tracked(1, x, 100, x + 80, 150)]
        for x in range(20, 200, 10)
    ]

    events = run(frames)

    assert len(events) == 1
    assert events[0].zone.type == "IN"
    assert events[0].track_id == 1

    # 기록 시각 = 처음 박스와 겹친 프레임 (겹침 > 0.3 이 된 첫 프레임)
    first_inside = next(
        frame
        for frame, x in enumerate(range(20, 200, 10))
        if (min(x + 80, 200) - max(x, 100)) * 50 / 5000 > 0.3
    )

    assert events[0].frame == first_inside


def test_parked_car_next_to_box_is_ignored():

    # 박스를 반쯤 덮은 채 서 있는 차 (bbox 흔들림만 있음)
    frames = [
        [tracked(2, 150 + (frame % 2), 100, 230 + (frame % 2), 150)]
        for frame in range(30)
    ]

    assert run(frames) == []


def test_car_moving_against_direction_is_ignored():

    # 오른쪽에서 왼쪽으로 박스를 지나가는 차
    frames = [
        [tracked(3, x, 100, x + 60, 150)]
        for x in range(240, 0, -10)
    ]

    assert run(frames) == []
