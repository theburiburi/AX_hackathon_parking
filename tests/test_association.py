import unittest

from src.association import AssociationObservation, GlobalVehicleAssociator


class GlobalVehicleAssociatorTests(unittest.TestCase):
    def test_entry_vehicle_keeps_id_across_overlapping_cameras(self):
        associator = GlobalVehicleAssociator(max_distance=20)
        first = associator.update([
            AssociationObservation("cam01", 1, 2, (100, 100), 0.9),
            AssociationObservation("cam02", 1, 2, (108, 104), 0.8),
        ])
        self.assertEqual(first[("cam01", 1)], 1)
        self.assertEqual(first[("cam02", 1)], 1)

        second = associator.update([
            AssociationObservation("cam03", 4, 2, (112, 108), 0.85),
        ])
        self.assertEqual(second[("cam03", 4)], 1)

    def test_non_entry_camera_does_not_create_new_id(self):
        associator = GlobalVehicleAssociator()
        assignments = associator.update([
            AssociationObservation("cam02", 1, 2, (100, 100), 0.9),
        ])
        self.assertEqual(assignments, {})

    def test_different_class_or_distance_does_not_reuse_id(self):
        associator = GlobalVehicleAssociator(max_distance=10)
        associator.update([AssociationObservation("cam01", 1, 2, (100, 100))])
        assignments = associator.update([
            AssociationObservation("cam02", 1, 7, (102, 102)),
            AssociationObservation("cam02", 2, 2, (200, 200)),
        ])
        self.assertEqual(assignments, {})


if __name__ == "__main__":
    unittest.main()
