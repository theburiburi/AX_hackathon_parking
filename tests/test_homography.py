import unittest

import numpy as np

from src.calibration.homography import compute_homography, project_point


class HomographyTests(unittest.TestCase):
    def test_maps_known_rectangle(self):
        source = [[0, 0], [10, 0], [10, 10], [0, 10]]
        destination = [[100, 50], [200, 50], [200, 250], [100, 250]]
        matrix, mask = compute_homography(source, destination)

        self.assertTrue(mask.all())
        np.testing.assert_allclose(project_point((5, 5), matrix), (150, 150), atol=1e-4)

    def test_requires_four_matching_points(self):
        with self.assertRaisesRegex(ValueError, "at least 4"):
            compute_homography([[0, 0], [1, 0], [1, 1]], [[0, 0], [2, 0], [2, 2]])

    def test_requires_equal_point_counts(self):
        with self.assertRaisesRegex(ValueError, "same number"):
            compute_homography(
                [[0, 0], [1, 0], [1, 1], [0, 1]],
                [[0, 0], [2, 0], [2, 2], [0, 2], [1, 1]],
            )


if __name__ == "__main__":
    unittest.main()
