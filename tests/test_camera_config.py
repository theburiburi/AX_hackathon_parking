import tempfile
import unittest
from pathlib import Path

from src.camera_config import load_camera_registry


class CameraConfigTests(unittest.TestCase):
    def test_loads_paths_relative_to_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "cameras.yaml"
            config.write_text(
                """bev_map: maps/bev.png
cameras:
  - id: cam01
    video: videos/one.mp4
    fps: 25.0
    offset_frames: 31
    calibration:
      is_sample: true
      image_points: []
      bev_points: []
""",
                encoding="utf-8",
            )
            registry = load_camera_registry(config)

        self.assertEqual(registry.cameras[0].camera_id, "cam01")
        self.assertEqual(registry.cameras[0].offset_frames, 31)
        self.assertEqual(registry.cameras[0].offset_seconds, 1.24)
        self.assertEqual(registry.cameras[0].video, root / "videos/one.mp4")
        self.assertEqual(registry.bev_map, root / "maps/bev.png")

    def test_rejects_duplicate_camera_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cameras.yaml"
            path.write_text(
                """bev_map: map.png
cameras:
  - {id: cam01, video: a.mp4, calibration: {}}
  - {id: cam01, video: b.mp4, calibration: {}}
""",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unique"):
                load_camera_registry(path)


if __name__ == "__main__":
    unittest.main()
