"""Seeking must preserve entrance-issued identities."""

import itertools
import threading
import unittest
from types import MethodType, SimpleNamespace

from server import TrackingEngine


class TrackingSeekTest(unittest.TestCase):
    def test_forward_and_backward_seek_replay_entrance_history(self):
        engine = object.__new__(TrackingEngine)
        engine.lock = threading.Lock()
        engine.cache = SimpleNamespace(frame_count=1000)
        engine.request_counter = itertools.count(1)
        engine.latest_request = 0
        engine.current_frame = -1
        engine.last_result = None
        engine.checkpoints = {}
        engine.local_trackers = {}
        engine.global_tracker = {"next_id": 1, "issued": []}
        engine.entry_gate = {}
        engine.parking_log = {}

        def process(self, frame):
            if frame == 5:
                self.global_tracker["issued"].append(self.global_tracker["next_id"])
                self.global_tracker["next_id"] += 1
            result = {"frame_index": frame, "issued": list(self.global_tracker["issued"])}
            self.current_frame = frame
            self.last_result = result
            return result

        engine._process_frame = MethodType(process, engine)

        self.assertEqual(engine.get_frame(15)["issued"], [1])
        self.assertEqual(engine.get_frame(8)["issued"], [1])
        self.assertEqual(engine.get_frame(20)["issued"], [1])
        self.assertEqual(engine.global_tracker["next_id"], 2)


if __name__ == "__main__":
    unittest.main()
