from __future__ import annotations

import bisect
import json
from pathlib import Path

import cv2
import numpy as np
import yaml

from src.mosaic import LAYOUT_PATH


"""
카메라 화면 모드 (전체 / 축소).

차량이 없을 때 일부 카메라는 용량을 줄이려고 화면 전체를 가로로 압축하고
좌우를 검게 채운다 (축소 모드). 같은 땅 위치가 모드마다 다른 픽셀에
찍히므로, tracking / calibration은 항상 "전체 화면" 좌표를 사용한다.

    축소 모드 x = scale_x * 전체 화면 x + offset_x   (y는 같다)

모드 기록: data/<title>/view_modes.json (있을 때만 사용.
scripts/00_prepare_video.py 로 여백을 없앤 영상에서 검출했다면 필요 없다)
    {"letterbox": {...}, "frame_count": N,
     "cameras": {"cam06": [[start, end), ...], ...}}   (축소 모드 구간)
"""

VIEW_MODES_FILENAME = "view_modes.json"

# 축소 모드 판별에 쓰는 세로 범위 (왼쪽 위 "CAMx" 글자 제외).
_LABEL_MARGIN_Y = 60

# 검은 띠로 볼 최대 밝기 / 화면 내용으로 볼 최소 밝기.
_BLACK_MAX = 10.0
_CONTENT_MIN = 15.0


def load_letterbox(path: Path = LAYOUT_PATH) -> tuple[float, float]:
    with path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}
    letterbox = config.get("letterbox") or {}
    return (float(letterbox.get("scale_x", 0.825)),
            float(letterbox.get("offset_x", 113.0)))


def is_letterboxed(crop: np.ndarray, scale_x: float, offset_x: float) -> bool:
    """잘라낸 카메라 칸이 축소 모드(좌우 검은 띠)인지."""
    height, width = crop.shape[:2]
    rows = crop[_LABEL_MARGIN_Y:height - 10]
    bar = int(offset_x) - 8
    content_end = int(offset_x + scale_x * width)
    left = rows[:, bar // 3:bar].mean()
    right = rows[:, content_end + 8:width - 8].mean()
    inner = rows[:, bar + 20:content_end - 20].mean()
    return left <= _BLACK_MAX and right <= _BLACK_MAX and inner >= _CONTENT_MIN


def unletterbox_image(crop: np.ndarray, scale_x: float, offset_x: float) -> np.ndarray:
    """축소 모드 화면을 전체 화면 좌표로 펼친 이미지."""
    height, width = crop.shape[:2]
    map_x = np.tile(
        (offset_x + scale_x * np.arange(width, dtype=np.float32)), (height, 1))
    map_y = np.repeat(np.arange(height, dtype=np.float32)[:, None], width, axis=1)
    return cv2.remap(crop, map_x, map_y, cv2.INTER_LINEAR)


class ViewModes:
    """프레임별 카메라 화면 모드 기록."""

    def __init__(self, scale_x: float, offset_x: float,
                 segments: dict[str, list[tuple[int, int]]] | None = None):
        self.scale_x = scale_x
        self.offset_x = offset_x
        self.segments = {
            camera_id: sorted((int(start), int(end)) for start, end in items)
            for camera_id, items in (segments or {}).items()
        }
        self._starts = {
            camera_id: [start for start, _ in items]
            for camera_id, items in self.segments.items()
        }

    @classmethod
    def load(cls, path: Path) -> ViewModes | None:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        letterbox = data.get("letterbox", {})
        return cls(float(letterbox["scale_x"]), float(letterbox["offset_x"]),
                   data.get("cameras", {}))

    def save(self, path: Path, frame_count: int) -> None:
        data = {
            "letterbox": {"scale_x": self.scale_x, "offset_x": self.offset_x},
            "frame_count": frame_count,
            "cameras": {
                camera_id: [list(item) for item in items]
                for camera_id, items in self.segments.items()
            },
        }
        with path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=1)

    def letterboxed(self, camera_id: str, frame_index: int) -> bool:
        starts = self._starts.get(camera_id)
        if not starts:
            return False
        index = bisect.bisect_right(starts, frame_index) - 1
        return index >= 0 and frame_index < self.segments[camera_id][index][1]

    def to_full_x(self, x: float) -> float:
        return (x - self.offset_x) / self.scale_x

    def to_view_x(self, x: float) -> float:
        return self.scale_x * x + self.offset_x


class ViewModeRecorder:
    """프레임을 순서대로 받아 축소 모드 구간을 기록한다."""

    def __init__(self, camera_ids: list[str], scale_x: float, offset_x: float):
        self.scale_x = scale_x
        self.offset_x = offset_x
        self.segments: dict[str, list[tuple[int, int]]] = {c: [] for c in camera_ids}
        self._open: dict[str, int | None] = {c: None for c in camera_ids}
        self.frame_count = 0

    def add(self, frame_index: int, crops: dict[str, np.ndarray]) -> None:
        for camera_id, crop in crops.items():
            boxed = is_letterboxed(crop, self.scale_x, self.offset_x)
            start = self._open[camera_id]
            if boxed and start is None:
                self._open[camera_id] = frame_index
            elif not boxed and start is not None:
                self.segments[camera_id].append((start, frame_index))
                self._open[camera_id] = None
        self.frame_count = frame_index + 1

    def finish(self) -> ViewModes:
        for camera_id, start in self._open.items():
            if start is not None:
                self.segments[camera_id].append((start, self.frame_count))
                self._open[camera_id] = None
        return ViewModes(self.scale_x, self.offset_x, self.segments)
