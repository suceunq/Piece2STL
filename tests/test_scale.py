import unittest

import numpy as np

from piece2stl.pipeline.scale import scale_factor_from_two_points


class ScaleTests(unittest.TestCase):
    def test_scale_factor(self):
        factor = scale_factor_from_two_points(np.array([0, 0, 0]), np.array([2, 0, 0]), 10)
        self.assertEqual(factor, 5)

    def test_coincident_points_are_rejected(self):
        with self.assertRaises(ValueError):
            scale_factor_from_two_points(np.zeros(3), np.zeros(3), 10)

    def test_non_positive_real_distance_is_rejected(self):
        with self.assertRaises(ValueError):
            scale_factor_from_two_points(np.zeros(3), np.ones(3), 0)


if __name__ == "__main__":
    unittest.main()
