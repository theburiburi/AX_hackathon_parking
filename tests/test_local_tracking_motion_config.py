"""Check that configured motion gates reject modest image scaling but retain departures."""

import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

from src.tracking.local_tracker import LocalTracker, TrackState


CONFIG = Path(__file__).resolve().parents[1] / "config" / "tracking.yaml"


class LocalTrackingMotionConfigTest(unittest.TestCase):
    def setUp(self):
        settings = yaml.safe_load(CONFIG.read_text())["local_tracking"]
        self.tracker = LocalTracker("cam01", print_transitions=False, **settings)

    def _observe(self, timestamp, shift_x=0.0, scale=1.0):
        center_x, center_y = 320.0, 180.0
        box = (475.0 + shift_x, 210.0, 525.0 + shift_x, 250.0)
        scaled = [center + scale * (value - center)
                  for value, center in zip(box, (center_x, center_y, center_x, center_y))]
        detection = SimpleNamespace(
            x1=scaled[0], y1=scaled[1], x2=scaled[2], y2=scaled[3],
            class_name="car", confidence=0.9,
        )
        return self.tracker.update([detection], timestamp)[0].track

    def test_gradual_image_shrink_does_not_activate_stationary_car(self):
        track = None
        for frame in range(91):
            track = self._observe(frame / 30, scale=1 - 0.12 * frame / 90)
        self.assertEqual(track.local_id, 1)
        self.assertEqual(track.state, TrackState.UNKNOWN)

    def test_actual_departure_still_activates_car(self):
        track = None
        for frame in range(91):
            track = self._observe(frame / 30, shift_x=45 * frame / 90)
        self.assertEqual(track.local_id, 1)
        self.assertEqual(track.state, TrackState.ACTIVE)

    def test_short_detection_gap_keeps_real_motion_evidence(self):
        track = None
        for frame in range(85):
            timestamp = frame / 30
            if 50 <= frame <= 54:
                self.tracker.update([], timestamp)
                continue
            track = self._observe(timestamp, shift_x=45 * frame / 84)
        self.assertEqual(track.local_id, 1)
        self.assertEqual(track.state, TrackState.ACTIVE)

    def test_passing_car_does_not_activate_occluded_rear_car(self):
        def detection(x):
            return SimpleNamespace(
                x1=x, y1=100, x2=x + 40, y2=140,
                class_name="car", confidence=.9,
            )

        rear_was_occluded = False
        for frame in range(151):
            timestamp = frame / 30
            passing = -20 + 50 * timestamp
            # The rear detection is pulled 12 px while the front car covers it.
            rear = 100 + (12 if 2.2 < timestamp < 4.2 else 0)
            observations = self.tracker.update([detection(passing), detection(rear)], timestamp)
            self.assertEqual(observations[0].track.local_id, 1)
            self.assertEqual(observations[1].track.local_id, 2)
            rear_track = self.tracker.tracks[2]
            rear_was_occluded |= rear_track.occluded
            self.assertEqual(rear_track.state, TrackState.UNKNOWN)
            if rear_track.occluded:
                self.assertIsNone(rear_track.moving_candidate_since)

        self.assertTrue(rear_was_occluded)
        self.assertEqual(self.tracker.tracks[2].local_id, 2)
        self.assertEqual(self.tracker.tracks[1].state, TrackState.ACTIVE)

        # Once the view clears, a genuine departure may still become ACTIVE.
        for frame in range(151, 241):
            timestamp = frame / 30
            self.tracker.update([detection(100 + 18 * (timestamp - 5))], timestamp)
        self.assertEqual(self.tracker.tracks[2].state, TrackState.ACTIVE)

    def test_moving_car_hidden_behind_parked_car_does_not_take_its_id(self):
        def detection(x):
            return SimpleNamespace(x1=x, y1=100, x2=x + 40, y2=140,
                                   class_name="car", confidence=.9)

        # The moving car drives onto the parked car's box and goes out of
        # sight behind it; only the parked car's detection remains.
        for frame in range(106):
            timestamp = frame / 30
            if timestamp <= 2.0:
                detections = [detection(100), detection(300 - 100 * timestamp)]
            else:
                detections = [detection(100)]
            observations = self.tracker.update(detections, timestamp)
            if frame == 70:
                # The moving track first claims the parked car's box.
                self.assertEqual(observations[0].track.local_id, 2)
                self.assertEqual(self.tracker.tracks[2].state, TrackState.ACTIVE)

        self.assertEqual(observations[0].track.local_id, 1)
        self.assertNotIn(2, self.tracker.tracks)

    def test_rear_car_stays_occluded_during_one_foreground_detection_gap(self):
        def detection(x):
            return SimpleNamespace(x1=x, y1=100, x2=x + 40, y2=140,
                                   class_name="car", confidence=.9)

        for frame in range(76):
            timestamp = frame / 30
            rear = detection(100 + (12 if timestamp > 2.2 else 0))
            detections = ([rear] if frame == 75 else
                          [detection(-20 + 50 * timestamp), rear])
            self.tracker.update(detections, timestamp)
        self.assertTrue(self.tracker.tracks[2].occluded)
        self.assertEqual(self.tracker.tracks[2].state, TrackState.UNKNOWN)
        self.assertIsNone(self.tracker.tracks[2].moving_candidate_since)

    def test_camera_reframing_keeps_parked_id_on_same_car(self):
        def detection(box):
            return SimpleNamespace(x1=box[0], y1=box[1], x2=box[2], y2=box[3],
                                   class_name="car", confidence=.9)

        before = [(15, 282, 240, 401), (138, 262, 238, 320),
                  (265, 250, 432, 331)]
        after = [(112, 285, 312, 402), (230, 263, 310, 322),
                 (332, 250, 471, 332)]
        observations = self.tracker.update([detection(box) for box in before], 0.0)
        original_ids = [item.track.local_id for item in observations]
        for track in self.tracker.tracks.values():
            track.state = TrackState.PARKED
        observations = self.tracker.update([detection(box) for box in after], 1 / 30)
        self.assertEqual([item.track.local_id for item in observations], original_ids)

    def test_parked_id_does_not_jump_to_larger_neighbor(self):
        def detection(box):
            return SimpleNamespace(x1=box[0], y1=box[1], x2=box[2], y2=box[3],
                                   class_name="car", confidence=.9)

        old = self.tracker.update([detection((138, 262, 238, 320))], 0.0)[0].track
        old.state = TrackState.PARKED
        new = self.tracker.update([detection((112, 285, 312, 402))], 1 / 30)[0].track
        self.assertNotEqual(new.local_id, old.local_id)


    def test_duplicate_box_on_stopped_car_does_not_steal_its_id(self):
        def detection(x1, x2):
            return SimpleNamespace(x1=x1, y1=100, x2=x2, y2=200,
                                   class_name="car", confidence=.9)

        stopped = self.tracker.update([detection(475, 525)], 0)[0].track
        stopped.has_moved = True
        stopped.state = TrackState.STOPPED
        both = self.tracker.update([detection(475, 525), detection(482, 540)], .1)
        duplicate_id = both[1].track.local_id
        self.assertNotEqual(duplicate_id, stopped.local_id)

        # Only the second box remains, closer to the new track's box.
        track = None
        for frame in range(2, 60):
            track = self.tracker.update([detection(483, 541)], frame / 30)[0].track
        self.assertEqual(track.local_id, stopped.local_id)
        self.assertEqual(track.state, TrackState.STOPPED)
        self.assertNotIn(duplicate_id, self.tracker.tracks)

    def test_car_arriving_over_stopped_car_keeps_its_own_id(self):
        def detection(x1, x2):
            return SimpleNamespace(x1=x1, y1=100, x2=x2, y2=200,
                                   class_name="car", confidence=.9)

        stopped = self.tracker.update([detection(475, 525)], 0)[0].track
        stopped.has_moved = True
        stopped.state = TrackState.STOPPED
        arriving = self.tracker.update([detection(475, 525), detection(300, 350)], .1)[1].track
        duplicate = self.tracker.update([detection(475, 525), detection(482, 540)], .2)[1].track
        # Only a box born on top of the stopped car is treated as its duplicate.
        self.assertIsNone(arriving.duplicate_of)
        self.assertEqual(duplicate.duplicate_of, stopped.local_id)

if __name__ == "__main__":
    unittest.main()
