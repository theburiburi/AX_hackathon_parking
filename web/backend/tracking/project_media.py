"""Read existing project camera settings without modifying them."""
from pathlib import Path
import os
import sys

sys.dont_write_bytecode = True
PROJECT = Path(__file__).resolve().parents[3]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from src.camera_config import load_camera_registry


def registry():
    return load_camera_registry(Path(os.environ.get("WEB_CAMERAS_CONFIG", PROJECT / "cameras.yaml")))


def selected_map(media_dir, first_media, suffixes):
    image = registry().bev_map
    return image if image.is_file() else first_media(media_dir / "maps", suffixes)


def camera_media(media_dir, first_media, suffixes):
    cameras = []
    for camera in registry().cameras:
        short_id = camera.camera_id.removeprefix("cam")
        video = camera.video if camera.video.is_file() else first_media(media_dir / "cctv" / f"camera_{short_id}", suffixes)
        cameras.append((camera, video))
    return cameras
