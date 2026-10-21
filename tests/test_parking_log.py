"""Zone counts follow GID cars that park or vanish inside the lot."""

import unittest

import re

from src.tracking.parking_log import ParkingLog, vehicle_plate


ZONES = [
    {"id": "H", "capacity": 8, "bndbox": {"xmin": 170, "ymin": 175, "xmax": 233, "ymax": 840}},
    {"id": "I", "capacity": 7, "bndbox": {"xmin": 170, "ymin": 130, "xmax": 655, "ymax": 170}},
]


def item(state, x, y, gid=2, camera="cam08"):
    return {"global_id": gid, "state": state, "x": x, "y": y, "camera_id": camera}


class ParkingLogTest(unittest.TestCase):
    def setUp(self):
        self.log = ParkingLog(ZONES, lost_after_sec=10.0)

    def test_parked_inside_zone_counts_once(self):
        self.log.update(0, 0.0, [item("ACTIVE", 300, 150)])
        events = self.log.update(1, 0.1, [item("PARKED", 370, 150)])
        self.log.update(2, 0.2, [item("PARKED", 371, 150)])
        self.assertEqual([e["type"] for e in events], ["PARKED"])
        self.assertEqual(self.log.counts["I"], 1)
        self.assertEqual(events[0]["count"], 1)

    def test_vanished_car_counts_in_nearest_zone_after_ten_seconds(self):
        self.log.update(0, 0.0, [item("ACTIVE", 250, 190, camera="cam03")])
        self.assertEqual(self.log.update(1, 9.9, []), [])
        events = self.log.update(2, 10.0, [])
        self.assertEqual([(e["type"], e["zone"]) for e in events], [("LOST", "H")])
        self.assertEqual(self.log.update(3, 30.0, []), [])
        self.assertEqual(self.log.counts["H"], 1)

    def test_car_last_seen_at_gate_camera_is_not_counted(self):
        self.log.update(0, 0.0, [item("ACTIVE", 1015, 150, camera="cam01")])
        self.assertEqual(self.log.update(1, 20.0, []), [])
        self.assertEqual(sum(self.log.counts.values()), 0)

    def test_leaving_car_is_subtracted(self):
        self.log.update(0, 0.0, [item("PARKED", 370, 150)])
        self.log.update(1, 1.0, [item("ACTIVE", 372, 152)])
        self.assertEqual(self.log.counts["I"], 1)
        events = self.log.update(2, 2.0, [item("ACTIVE", 372, 260)])
        self.assertEqual([e["type"] for e in events], ["LEFT"])
        self.assertEqual(self.log.counts["I"], 0)

    def test_estimated_car_moves_to_zone_where_it_parks(self):
        self.log.update(0, 0.0, [item("ACTIVE", 250, 190, camera="cam03")])
        self.log.update(1, 10.0, [])
        events = self.log.update(2, 11.0, [item("PARKED", 400, 150)])
        self.assertEqual([(e["type"], e["zone"]) for e in events],
                         [("LEFT", "H"), ("PARKED", "I")])
        self.assertEqual((self.log.counts["H"], self.log.counts["I"]), (0, 1))

    def test_events_carry_a_stable_plate_per_vehicle(self):
        events = self.log.update(0, 0.0, [item("PARKED", 370, 150)])
        self.assertRegex(events[0]["plate"], r"^\d{2,3}[가-힣] \d{4}$")
        self.assertEqual(events[0]["plate"], vehicle_plate(2))
        self.assertEqual(vehicle_plate(2), vehicle_plate(2))
        self.assertNotEqual(vehicle_plate(1), vehicle_plate(2))

    def test_cars_without_global_id_are_ignored(self):
        self.log.update(0, 0.0, [item("PARKED", 370, 150, gid=None)])
        self.assertEqual(sum(self.log.counts.values()), 0)


if __name__ == "__main__":
    unittest.main()
