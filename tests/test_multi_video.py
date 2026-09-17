import unittest
from pathlib import Path

import numpy as np

from src.playback.cli import compose_video_grid
from src.playback.reader import VideoInfo, common_time_range


class MultiVideoTests(unittest.TestCase):
    def test_common_range_respects_offsets(self):
        infos = [
            VideoInfo(Path("a.mp4"), 30.0, 300, 1920, 1080),
            VideoInfo(Path("b.mp4"), 25.0, 250, 1920, 1080),
        ]
        start, end = common_time_range(infos, [0.0, 2000.0])
        self.assertEqual(start, 0.0)
        self.assertEqual(end, 8000.0)

    def test_grid_contains_seven_frames_at_requested_size(self):
        frames = [np.full((90, 160, 3), index, dtype=np.uint8) for index in range(7)]
        grid = compose_video_grid(
            frames, [f"cam-{index}" for index in range(7)], 900, 700, 3, 1234.0, True
        )
        self.assertEqual(grid.shape, (700, 900, 3))


if __name__ == "__main__":
    unittest.main()
