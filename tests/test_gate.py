"""
차단기 입출차 감지 박스 (src/gate.py).
"""

import numpy as np
import pytest

from src.gate import load_zones, overlap_ratio


CONFIG = {
    "zones": [
        {
            "type": "IN",
            "label": "입차",
            "box": [100, 100, 200, 150],
            "direction": [-1.0, 0.5],
        },
    ],
}


def test_load_zones_keeps_reference_box():

    zone = load_zones(CONFIG)[0]

    assert zone.box == (100, 100, 200, 150)
    assert np.isclose(np.linalg.norm(zone.direction), 1.0)


def test_load_zones_scales_box_to_cell_size():

    # 640x360 기준 박스를 1280x720 칸(test02)에 맞춘다
    zone = load_zones(CONFIG, 2.0, 2.0)[0]

    assert zone.box == (200, 200, 400, 300)


def test_load_zones_anisotropic_scale_changes_direction():

    zone = load_zones(CONFIG, 2.0, 1.0)[0]

    expected = np.array([-2.0, 0.5]) / np.hypot(2.0, 0.5)

    assert np.allclose(zone.direction, expected)


def test_load_zones_rejects_zero_direction():

    config = {"zones": [{**CONFIG["zones"][0], "direction": [0, 0]}]}

    with pytest.raises(ValueError):
        load_zones(config)


def test_overlap_ratio_is_box_area_based():

    zone = load_zones(CONFIG)[0]  # 100x50 = 5000

    # 차량 bbox가 박스 전체를 덮으면 차량 크기와 관계없이 1
    assert overlap_ratio((0, 0, 1000, 1000), zone) == 1.0

    # 박스 왼쪽 절반만 덮음
    assert overlap_ratio((0, 0, 150, 1000), zone) == 0.5

    # 겹치지 않음
    assert overlap_ratio((300, 300, 400, 400), zone) == 0.0
