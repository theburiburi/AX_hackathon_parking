from __future__ import annotations

import cv2
import numpy as np


"""
CCTV 저장 영상의 카메라 칸 좌우 검은 여백 제거.

녹화 장비가 차가 지나가지 않을 때 화면을 가로로만 줄여(0.825배씩)
칸 좌우에 검은 여백이 생긴다. 세로는 항상 칸을 꽉 채운다.
(test01 / test02 측정: 꽉 참 1.0, 0.825, 0.681 = 0.825^2, 화면 가운데 기준)

여백을 잘라내고 가로로 늘리면 항상 '꽉 찬 상태'와 같은 좌표가 된다.
"""


# 이 밝기(0~255)보다 어두운 열을 여백으로 본다
BAR_THRESHOLD = 30

# 여백은 좌우 대칭이다. 좌우 여백 폭 차이가 칸 폭의 이 비율보다 크면
# (어두운 장면 등) 여백이 아닌 것으로 보고 늘리지 않는다.
SYMMETRY_TOLERANCE = 0.02


def content_columns(
    cell: np.ndarray,
) -> tuple[int, int]:
    """
    카메라 칸 안의 실제 화면 가로 범위 [left, right).
    여백이 없으면 (0, 칸 폭).
    """

    height, width = cell.shape[:2]

    # 칸 테두리선(밝은 1~2px)과 위쪽 카메라 이름 / 아래쪽 시각 글자는 제외
    border = max(3, width // 160)

    rows = cell[height // 10: height - height // 20: 4]

    brightness = (
        rows.max(axis=2)
        if rows.ndim == 3
        else rows
    ).mean(axis=0)

    bright = np.where(
        brightness[border: width - border] > BAR_THRESHOLD
    )[0] + border

    if len(bright) == 0:
        return 0, width

    left = int(bright[0])
    right = int(bright[-1]) + 1

    if left <= border:
        left = 0

    if right >= width - border:
        right = width

    if abs(left - (width - right)) > SYMMETRY_TOLERANCE * width:
        return 0, width

    return left, right


def fill_width(
    cell: np.ndarray,
) -> tuple[np.ndarray, tuple[int, int]]:
    """
    좌우 여백을 잘라내고 칸 폭으로 가로만 늘린 이미지와
    원래 화면 범위 (left, right).
    """

    height, width = cell.shape[:2]

    left, right = content_columns(cell)

    if left == 0 and right == width:
        return cell, (left, right)

    filled = cv2.resize(
        cell[:, left:right],
        (width, height),
        interpolation=cv2.INTER_LINEAR,
    )

    return filled, (left, right)
