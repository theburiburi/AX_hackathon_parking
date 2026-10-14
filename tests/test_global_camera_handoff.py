"""Entrance-only Global IDs and overlapping CCTV observations."""

import unittest
from pathlib import Path

import yaml

from src.tracking.global_tracker import GlobalObservation, GlobalTracker
from src.tracking.local_tracker import TrackState


CONFIG = Path(__file__).resolve().parents[1] / "config" / "global_tracking.yaml"


class GlobalCameraHandoffTest(unittest.TestCase):
    def setUp(self):
        settings = yaml.safe_load(CONFIG.read_text())["global_tracking"]
        self.tracker = GlobalTracker(
            max_reid_gap_sec=settings["max_reid_gap_sec"],
            last_position_match_distance_px=settings["last_position_match_distance_px"],
            overlap_match_distance_px=settings["overlap_match_distance_px"],
            overlap_window_sec=settings["overlap_window_sec"],
            overlap_score_bonus=settings["overlap_score_bonus"],
            handoff_confirmation_frames=settings["handoff_confirmation_frames"],
            probe_handoff_grace_sec=settings["probe_handoff_grace_sec"],
            print_events=False,
        )

    @staticmethod
    def observation(camera, local_id, x, timestamp, entry=False, y=100):
        return GlobalObservation(
            camera, local_id, TrackState.ACTIVE, "car", .9, x, y,
            timestamp, entry_eligible=entry,
        )

    def test_no_global_id_before_an_entrance_arrival(self):
        self.assertEqual(self.tracker.update([
            self.observation("cam07", 8, 100, 0),
            self.observation("cam01", 1, 100, 0),
        ], 0), {})
        self.assertEqual(self.tracker.global_tracks, {})

    def test_only_entrance_allocates_and_ids_increase_for_each_arrival(self):
        assignments = self.tracker.update([
            self.observation("cam07", 8, 800, 0),
            self.observation("cam01", 1, 100, 0, entry=True),
        ], 0)
        self.assertEqual(assignments[("cam01", 1)], 1)
        self.assertNotIn(("cam07", 8), assignments)
        self.assertEqual(len(self.tracker.global_tracks), 1)

        self.assertNotIn(("cam07", 9), self.tracker.update([
            self.observation("cam07", 9, 805, .1)
        ], .1))
        self.assertEqual(len(self.tracker.global_tracks), 1)

        next_entry = self.tracker.update([
            self.observation("cam01", 2, 120, .2, entry=True)
        ], .2)
        self.assertEqual(next_entry[("cam01", 2)], 2)
        self.assertEqual(self.tracker.next_global_id, 3)

    def test_two_cameras_can_share_an_id_without_double_motion_sample(self):
        self.tracker.update([self.observation("cam01", 1, 100, 0, entry=True)], 0)
        assignments = self.tracker.update([
            self.observation("cam01", 1, 100, .1),
            self.observation("cam07", 8, 108, .1),
        ], .1)
        self.assertEqual(assignments[("cam01", 1)], 1)
        self.assertNotIn(("cam07", 8), assignments)
        self.assertEqual(len(self.tracker.global_tracks[1].bev_history), 2)
        self.assertEqual(self.tracker.global_tracks[1].last_bev_x, 100)

        self.tracker.update([
            self.observation("cam01", 1, 100, .15),
            self.observation("cam07", 8, 108, .15),
        ], .15)
        assignments = self.tracker.update([
            self.observation("cam01", 1, 100, .2),
            self.observation("cam07", 8, 108, .2),
            self.observation("cam07", 9, 110, .2),
        ], .2)
        self.assertEqual(assignments[("cam07", 8)], 1)
        self.assertNotIn(("cam07", 9), assignments)

    def test_one_existing_id_does_not_claim_unrelated_distant_car(self):
        self.tracker.update([self.observation("cam01", 1, 100, 0, entry=True)], 0)
        assignments = self.tracker.update([
            self.observation("cam07", 2, 900, 200.0)
        ], 200.0)
        self.assertNotIn(("cam07", 2), assignments)
        self.assertEqual(len(self.tracker.global_tracks), 1)

    def test_multiple_entrants_leave_ambiguous_other_camera_unassigned(self):
        self.tracker.update([
            self.observation("cam01", 1, 100, 0, entry=True),
            self.observation("cam01", 2, 110, 0, entry=True),
        ], 0)
        self.assertEqual(len(self.tracker.global_tracks), 2)
        self.assertEqual(self.tracker.update([
            self.observation("cam07", 5, 105, .1)
        ], .1), {})
        self.assertEqual(len(self.tracker.global_tracks), 2)

    def test_entrance_crossing_gets_new_id_even_near_existing_car(self):
        self.tracker.update([self.observation("cam01", 1, 100, 0, entry=True)], 0)
        assignments = self.tracker.update([
            self.observation("cam01", 2, 103, .1, entry=True)
        ], .1)
        self.assertEqual(assignments[("cam01", 2)], 2)
        self.assertEqual(len(self.tracker.global_tracks), 2)

    def test_cam03_and_cam08_overlap_with_multiple_existing_ids(self):
        self.tracker.update([self.observation("cam01", 1, 100, 0, entry=True)], 0)
        timestamp = 0
        for camera, local_id in (("cam07", 1), ("cam05", 2), ("cam06", 3),
                                 ("cam03", 4), ("cam08", 5)):
            for _ in range(3):
                timestamp = round(timestamp + .1, 2)
                self.tracker.update([
                    self.observation(camera, local_id, 100, timestamp)
                ], timestamp)
            self.assertEqual(self.tracker.get_global_id(camera, local_id), 1)
        self.tracker.update([
            self.observation("cam01", 2, 500, timestamp + .1, entry=True)
        ], timestamp + .1)
        for timestamp in (1.7, 1.8, 1.9):
            assignments = self.tracker.update([
                self.observation("cam08", 5, 100, timestamp),
                self.observation("cam03", 6, 105, timestamp),
            ], timestamp)
        self.assertEqual(assignments[("cam08", 5)], 1)
        self.assertEqual(assignments[("cam03", 6)], 1)
        self.assertEqual(len(self.tracker.global_tracks), 2)

    def test_cam05_and_cam07_can_share_one_id_without_a_camera_route(self):
        self.tracker.update([self.observation("cam01", 1, 100, 0, entry=True)], 0)
        for timestamp in (.1, .2, .3):
            self.tracker.update([
                self.observation("cam05", 2, 100, timestamp)
            ], timestamp)
        self.assertEqual(self.tracker.get_global_id("cam05", 2), 1)

        for timestamp in (.4, .5, .6):
            assignments = self.tracker.update([
                self.observation("cam05", 2, 100, timestamp),
                self.observation("cam07", 3, 105, timestamp),
            ], timestamp)
        self.assertEqual(assignments[("cam05", 2)], 1)
        self.assertEqual(assignments[("cam07", 3)], 1)
        self.assertEqual(len(self.tracker.global_tracks), 1)

    def test_early_motion_probe_keeps_predicted_id_until_active(self):
        self.tracker.update([self.observation("cam01", 1, 0, 0, entry=True)], 0)
        self.tracker.update([self.observation("cam01", 1, 10, .1)], .1)

        for index in range(28, 43):
            timestamp = index / 10
            self.tracker.probe_existing(
                self.observation("cam07", 2, timestamp * 100, timestamp))
        assignments = self.tracker.update([
            self.observation("cam07", 2, 430, 4.3)
        ], 4.3)
        self.assertEqual(assignments[("cam07", 2)], 1)
        self.assertEqual(len(self.tracker.global_tracks), 1)

    def test_late_or_distant_reappearance_does_not_take_an_id(self):
        self.tracker.update([self.observation("cam01", 1, 100, 0, entry=True)], 0)
        self.assertEqual(self.tracker.update([
            self.observation("cam07", 2, 100, 4.3)
        ], 4.3), {})
        for timestamp in (2.8, 2.9, 3.0):
            self.assertIsNone(self.tracker.probe_existing(
                self.observation("cam05", 3, 800, timestamp)))
        self.assertEqual(self.tracker.update([
            self.observation("cam05", 3, 800, 4.3)
        ], 4.3), {})

    def test_turn_after_camera_gap_uses_last_observed_bev_point(self):
        self.tracker.update([
            self.observation("cam01", 1, 759, 0, entry=True, y=511)
        ], 0)
        self.tracker.update([
            self.observation("cam01", 1, 750, .1, y=517)
        ], .1)
        for timestamp in (1.3, 1.4, 1.5):
            distractor = self.tracker.update([
                self.observation("cam05", 3, 870, timestamp, y=783)
            ], timestamp)
            self.assertNotIn(("cam05", 3), distractor)
        for timestamp, x, y in ((3.3, 790, 670), (3.4, 787, 676),
                                (3.5, 784, 682)):
            assignments = self.tracker.update([
                self.observation("cam05", 2, x, timestamp, y=y)
            ], timestamp)
        self.assertEqual(assignments[("cam05", 2)], 1)


if __name__ == "__main__":
    unittest.main()
