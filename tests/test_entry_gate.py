"""Only a directed cam01 entrance crossing can authorize a new GID."""

import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

from src.tracking.global_tracker import EntryGate


CONFIG = Path(__file__).resolve().parents[1] / "config" / "gate.yaml"


class EntryGateTest(unittest.TestCase):
    def setUp(self):
        self.gate = EntryGate(yaml.safe_load(CONFIG.read_text()))

    @staticmethod
    def track(local_id, x, y, camera="cam01", occluded=False):
        return SimpleNamespace(
            camera_id=camera, local_id=local_id,
            bbox=(x - 40, y - 50, x + 40, y),
            ground_x=x, ground_y=y, occluded=occluded,
        )

    def test_entry_is_remembered_after_three_frames_in_zone(self):
        positions = [(420, 134), (410, 136), (400, 138),
                     (390, 140), (380, 142), (370, 144)]
        results = [self.gate.observe(self.track(1, x, y), index * .1)
                   for index, (x, y) in enumerate(positions)]
        self.assertFalse(results[0])
        self.assertTrue(results[-1])
        self.assertTrue(self.gate.observe(self.track(1, 100, 220), .6))

    def test_reverse_or_other_camera_does_not_qualify(self):
        for index, x in enumerate((340, 350, 360, 370, 380)):
            self.assertFalse(self.gate.observe(self.track(2, x, 135), index * .1))
            self.assertFalse(self.gate.observe(
                self.track(1, 380 - index * 10, 135, camera="cam07"), index * .1))

    def test_entry_zone_scales_with_camera_resolution(self):
        scaled_gate = EntryGate(yaml.safe_load(CONFIG.read_text()), (1280, 720))
        self.assertEqual(scaled_gate.box, (600.0, 210.0, 760.0, 280.0))
        self.assertEqual(scaled_gate.min_speed, self.gate.min_speed * 2)
        positions = [(420, 134), (410, 136), (400, 138),
                     (390, 140), (380, 142), (370, 144)]
        results = []
        for index, (x, y) in enumerate(positions):
            track = self.track(1, x, y)
            track.bbox = tuple(value * 2 for value in track.bbox)
            track.ground_x *= 2
            track.ground_y *= 2
            results.append(scaled_gate.observe(track, index * .1))
        self.assertTrue(results[-1])


if __name__ == "__main__":
    unittest.main()
