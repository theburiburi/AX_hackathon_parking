"""Letterboxed camera frames must be tracked in full-view coordinates."""

import unittest

import numpy as np

from src.view_mode import ViewModeRecorder, ViewModes, is_letterboxed, unletterbox_image


SCALE, OFFSET = 0.825, 113.0


def frame(letterboxed):
    image = np.full((720, 1280, 3), 120, np.uint8)
    if letterboxed:
        image[:, :112] = 0
        image[:, 1170:] = 0
    return image


class ViewModeTest(unittest.TestCase):
    def test_detects_black_side_bars_only(self):
        self.assertTrue(is_letterboxed(frame(True), SCALE, OFFSET))
        self.assertFalse(is_letterboxed(frame(False), SCALE, OFFSET))
        self.assertFalse(is_letterboxed(np.zeros((720, 1280, 3), np.uint8), SCALE, OFFSET))

    def test_coordinates_round_trip(self):
        modes = ViewModes(SCALE, OFFSET)
        self.assertAlmostEqual(modes.to_view_x(modes.to_full_x(704.0)), 704.0)
        self.assertAlmostEqual(modes.to_full_x(OFFSET), 0.0)
        self.assertAlmostEqual(modes.to_full_x(OFFSET + SCALE * 1280), 1280.0)

    def test_recorder_keeps_letterboxed_frame_ranges(self):
        recorder = ViewModeRecorder(["cam06"], SCALE, OFFSET)
        for index, boxed in enumerate([False, True, True, False, True]):
            recorder.add(index, {"cam06": frame(boxed)})
        modes = recorder.finish()
        self.assertEqual(modes.segments["cam06"], [(1, 3), (4, 5)])
        self.assertEqual([modes.letterboxed("cam06", i) for i in range(6)],
                         [False, True, True, False, True, False])
        self.assertFalse(modes.letterboxed("cam07", 1))

    def test_unletterbox_restores_full_view_pixels(self):
        full = np.tile(np.arange(1280, dtype=np.float32) / 5, (10, 1))
        boxed = np.zeros_like(full)
        boxed[:, 113:1169] = np.interp(
            np.arange(113, 1169), OFFSET + SCALE * np.arange(1280), full[0])
        restored = unletterbox_image(boxed, SCALE, OFFSET)
        self.assertLess(np.abs(restored[:, 5:1275] - full[:, 5:1275]).max(), 0.5)


if __name__ == "__main__":
    unittest.main()
