import unittest

import numpy as np

from src.tracking import TrackedVehicle
from src.visualization import compose_multi_camera_bev


class TrackedVehicleTests(unittest.TestCase):
    def test_ground_point_is_bbox_bottom_center(self):
        vehicle = TrackedVehicle(3, 2, 0.9, (10, 20, 30, 80))
        self.assertEqual(vehicle.ground_point, (20.0, 80.0))

    def test_multi_camera_bev_view_has_bounded_size(self):
        cameras = [np.zeros((90, 160, 3), dtype=np.uint8) for _ in range(7)]
        bev = np.zeros((400, 600, 3), dtype=np.uint8)
        combined = compose_multi_camera_bev(cameras, bev, 1000, 800)
        self.assertEqual(combined.shape, (800, 1000, 3))

    def test_camera_grid_is_left_and_bev_is_right_with_two_empty_slots(self):
        cameras = [np.full((100, 100, 3), i + 1, dtype=np.uint8) for i in range(7)]
        bev = np.full((300, 300, 3), 200, dtype=np.uint8)
        combined = compose_multi_camera_bev(cameras, bev, 600, 600)
        for index in range(9):
            row, column = divmod(index, 3)
            expected = index + 1 if index < 7 else 0
            np.testing.assert_array_equal(combined[row * 100 + 50, column * 100 + 50],
                                          [expected] * 3)
        np.testing.assert_array_equal(combined[300, 450], [200] * 3)
        self.assertFalse(combined[300:, :300].any())

    def test_widescreen_cameras_touch_without_stretching(self):
        cameras = [np.full((90, 160, 3), i + 1, dtype=np.uint8) for i in range(7)]
        bev = np.zeros((100, 100, 3), dtype=np.uint8)
        combined = compose_multi_camera_bev(cameras, bev, 960, 800)
        for index in range(7):
            row, col = divmod(index, 3)
            tile = combined[row * 90:(row + 1) * 90, col * 160:(col + 1) * 160]
            self.assertTrue((tile == index + 1).all())
        self.assertFalse(combined[270:, :480].any())

    def test_small_window_is_rejected(self):
        view = np.zeros((10, 10, 3), dtype=np.uint8)
        with self.assertRaises(ValueError):
            compose_multi_camera_bev([view], view, 10, 10)

    def test_without_bev_cameras_use_full_width(self):
        cameras = [np.full((90, 160, 3), i + 1, dtype=np.uint8) for i in range(7)]
        combined = compose_multi_camera_bev(cameras, None, 960, 800)
        for index in range(7):
            row, col = divmod(index, 3)
            self.assertTrue((combined[row * 180:(row + 1) * 180,
                                     col * 320:(col + 1) * 320] == index + 1).all())
        self.assertFalse(combined[360:540, 320:].any())

    def test_bev_uses_spare_space_without_resizing_or_covering_cameras(self):
        cameras = [np.full((90, 160, 3), i + 1, dtype=np.uint8) for i in range(7)]
        plain = compose_multi_camera_bev(cameras, None, 700, 500)
        bev = np.full((100, 200, 3), 200, dtype=np.uint8)
        combined = compose_multi_camera_bev(cameras, bev, 700, 500, bev_in_spare_space=True)
        occupied = plain[:, :, 0] != 0
        np.testing.assert_array_equal(combined[occupied], plain[occupied])
        self.assertTrue((combined[262:464, 233:] == 200).any())
        self.assertFalse(combined[464:].any())


if __name__ == "__main__":
    unittest.main()
