from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path

import yaml

from src.mosaic import pixel_scale
from src.video import VIDEO_FPS

from .local_tracker import LocalTracker


ROOT = Path(__file__).resolve().parents[2]

TRACKING_CONFIG_PATH = ROOT / "config" / "tracking.yaml"


"""
Local Tracker 생성 (서버 / 스크립트 공통).

server.py 와 스크립트가 같은 설정(config/tracking.yaml), 같은 방법으로
tracker를 만들어야 결과가 같다. tracker는 여기서만 만든다.
"""


@dataclass
class Detection:
    """
    detections.jsonl 의 bbox 1개 (Local Tracker 입력).
    """

    x1: float
    y1: float
    x2: float
    y2: float
    class_name: str
    confidence: float

    @classmethod
    def from_dict(
        cls,
        data: dict,
    ) -> Detection:

        return cls(
            x1=float(data["x1"]),
            y1=float(data["y1"]),
            x2=float(data["x2"]),
            y2=float(data["y2"]),
            class_name=str(data["class_name"]),
            confidence=float(data["confidence"]),
        )


def load_tracking_config() -> dict:
    """
    config/tracking.yaml 의 local_tracking 설정.
    """

    if not TRACKING_CONFIG_PATH.exists():
        return {}

    with TRACKING_CONFIG_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:

        return (yaml.safe_load(file) or {}).get(
            "local_tracking",
            {},
        )


def create_tracker(
    camera_id: str,
    cell_rect: tuple[int, int, int, int] | None = None,
    config: dict | None = None,
) -> LocalTracker:
    """
    config/tracking.yaml 설정으로 Local Tracker를 만든다.

    cell_rect(카메라 칸)를 주면 *_px 설정을 칸 크기에 맞춰 늘린다.
    config를 주면 파일을 다시 읽지 않는다 (여러 카메라를 한 번에 만들 때).
    fps는 30 고정 (VIDEO_FPS).
    """

    if config is None:
        config = load_tracking_config()

    accepted = set(
        inspect.signature(LocalTracker.__init__).parameters
    )

    params = {
        key: value
        for key, value in config.items()
        if key in accepted
    }

    params["print_transitions"] = False

    params["nominal_fps"] = VIDEO_FPS

    if cell_rect is not None:

        x1, y1, x2, y2 = cell_rect

        params["pixel_scale"] = pixel_scale(
            cell_rect,
            config.get("reference_size", [640, 360]),
        )

        params["cell_size"] = (x2 - x1, y2 - y1)

    # tracker가 받지 않는 인자는 넘기지 않는다 (server.py 의 LocalTracker와 같은 설정)
    params = {
        key: value
        for key, value in params.items()
        if key in accepted
    }

    return LocalTracker(
        camera_id=camera_id,
        **params,
    )
