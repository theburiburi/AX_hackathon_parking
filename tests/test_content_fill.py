"""
카메라 칸 좌우 검은 여백 제거 (src/content_fill.py).
"""

import numpy as np

from src.content_fill import content_columns, fill_width


def make_cell(width=640, height=360, left=0, right=640):
    """
    칸 테두리선(밝은 1px), 좌우 검은 여백, 가운데 화면(밝기 120 + 세로 줄무늬).
    """

    cell = np.zeros((height, width, 3), dtype=np.uint8)

    cell[:, left:right] = 120
    cell[:, left:right:40] = 220  # 줄무늬 (늘어난 위치 확인용)

    cell[:, 0] = 168   # 칸 테두리선
    cell[0, :] = 168

    return cell


def test_full_cell_has_no_bars():

    assert content_columns(make_cell()) == (0, 640)


def test_detects_squeezed_states():

    # test01 에서 관찰한 상태: 0.825, 0.681
    assert content_columns(make_cell(left=56, right=584)) == (56, 584)
    assert content_columns(make_cell(left=102, right=538)) == (102, 538)

    # test02 (4K 칸 1280x720)
    cell = make_cell(1280, 720, 112, 1168)
    assert content_columns(cell) == (112, 1168)


def test_asymmetric_dark_area_is_not_a_bar():

    # 왼쪽만 어두운 장면은 여백이 아니다
    cell = make_cell()
    cell[:, :150] = 0

    assert content_columns(cell) == (0, 640)


def test_fill_width_stretches_content_to_cell():

    cell = make_cell(left=56, right=584)

    filled, (left, right) = fill_width(cell)

    assert (left, right) == (56, 584)
    assert filled.shape == cell.shape

    # 여백이 사라져 양 끝까지 화면이다
    assert filled[180, 2:8].mean() > 100
    assert filled[180, -8:-2].mean() > 100


def test_fill_width_keeps_full_cell():

    cell = make_cell()

    filled, rect = fill_width(cell)

    assert rect == (0, 640)
    assert filled is cell
