"""Loading and validation for the multi-camera registry."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class CameraConfig:
    camera_id: str
    video: Path
    fps: float
    offset_frames: int
    calibration: dict[str, Any]

    @property
    def offset_seconds(self) -> float:
        return self.offset_frames / self.fps


@dataclass(frozen=True)
class CameraRegistry:
    path: Path
    bev_map: Path
    cameras: tuple[CameraConfig, ...]

    def get(self, camera_id: str) -> CameraConfig:
        for camera in self.cameras:
            if camera.camera_id == camera_id:
                return camera
        choices = ", ".join(camera.camera_id for camera in self.cameras)
        raise ValueError(f"unknown camera '{camera_id}'; available: {choices}")


def load_camera_registry(path: Path) -> CameraRegistry:
    if not path.is_file():
        raise FileNotFoundError(f"camera config not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file)
    if not isinstance(raw, dict):
        raise ValueError("camera config must contain a YAML mapping")
    if not isinstance(raw.get("cameras"), list) or not raw["cameras"]:
        raise ValueError("camera config must contain a non-empty cameras list")
    if not raw.get("bev_map"):
        raise ValueError("camera config must contain bev_map")

    base = path.resolve().parent
    bev_map = Path(raw["bev_map"])
    if not bev_map.is_absolute():
        bev_map = base / bev_map
    cameras: list[CameraConfig] = []
    seen: set[str] = set()
    for index, item in enumerate(raw["cameras"]):
        if not isinstance(item, dict):
            raise ValueError(f"cameras[{index}] must be a mapping")
        camera_id = str(item.get("id", "")).strip()
        if not camera_id or camera_id in seen:
            raise ValueError(f"camera IDs must be non-empty and unique: {camera_id!r}")
        if not item.get("video"):
            raise ValueError(f"camera {camera_id} is missing video")
        calibration = item.get("calibration")
        if not isinstance(calibration, dict):
            raise ValueError(f"camera {camera_id} is missing calibration")
        seen.add(camera_id)
        video = Path(item["video"])
        if not video.is_absolute():
            video = base / video
        fps = float(item.get("fps", 30.0))
        if fps <= 0:
            raise ValueError(f"camera {camera_id} fps must be positive")
        # offset_seconds remains readable for old config files, but frame offset
        # is canonical for fixed-FPS recorded inputs.
        if "offset_frames" in item:
            offset_frames = int(item["offset_frames"])
        else:
            offset_frames = int(round(float(item.get("offset_seconds", 0.0)) * fps))
        cameras.append(
            CameraConfig(
                camera_id=camera_id,
                video=video,
                fps=fps,
                offset_frames=offset_frames,
                calibration=calibration,
            )
        )
    return CameraRegistry(Path(path), bev_map, tuple(cameras))
