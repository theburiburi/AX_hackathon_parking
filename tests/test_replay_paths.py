"""Whole-video BEV paths for the replay path mode."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web" / "backend"))

from replay.paths import build_paths, frame_positions  # noqa: E402


def item(camera, global_id, x, y, state="ACTIVE"):
    return {"camera_id": camera, "local_id": 1, "global_id": global_id,
            "state": state, "x": x, "y": y}


class ReplayPathsTest(unittest.TestCase):
    def test_cam07_wins_over_cam02_and_others_are_averaged(self):
        positions = frame_positions([
            item("cam02", 1, 300, 300), item("cam07", 1, 100, 100),
            item("cam03", 2, 10, 10), item("cam08", 2, 20, 30),
            item("cam06", None, 5, 5), item("cam05", 3, 50, 50, state="UNKNOWN"),
        ], 1000, 1000)
        self.assertEqual(positions, {1: (100, 100), 2: (15, 20)})

    def test_path_keeps_samples_in_order_across_a_camera_gap(self):
        frames = [(n, [item("cam01", 4, 10 * n, 0)]) for n in range(0, 31, 3)]
        frames += [(n, []) for n in range(33, 120, 3)]
        frames += [(n, [item("cam05", 4, 500, 200)]) for n in range(120, 130, 3)]
        path = build_paths(frames, 1000, 1000)["4"]
        self.assertEqual(path[0][0], 0)
        self.assertEqual(path[-1][1:], [500.0, 200.0])
        self.assertEqual([p[0] for p in path], sorted(p[0] for p in path))
        # The gap from frame 30 to 120 stays as one jump for the UI to dash.
        self.assertTrue(any(b[0] - a[0] > 30 for a, b in zip(path, path[1:])))


if __name__ == "__main__":
    unittest.main()
