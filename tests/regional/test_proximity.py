import math
import unittest

import numpy as np
from scipy.spatial import cKDTree

from seascape.regional.proximity import finite_inventory_metrics


class NumericContract(unittest.TestCase):
    def run_case(self, target, inventory):
        return finite_inventory_metrics(
            np.array(target), np.array(inventory), cKDTree(inventory)
        )

    def test_scalar_no_hard_cutoff(self):
        inventory = [[0, 0], [6000, 8000], [100000, 0]]
        d, p, k = self.run_case([[3000, 4000]], inventory)
        expected = [math.hypot(3000 - x, 4000 - y) for x, y in inventory]
        self.assertAlmostEqual(d[0], min(expected))
        self.assertAlmostEqual(k[0], math.fsum(math.exp(-x / 5000) for x in expected))
        self.assertGreater(k[0], 2 * math.exp(-1))

    def test_duplicate_ties_count_retained_records(self):
        d, p, k = self.run_case([[0, 0]], [[0, 0], [0, 0], [5000, 0]])
        self.assertEqual(d[0], 0)
        self.assertIn(p[0], [0, 1])
        self.assertAlmostEqual(k[0], 2 + math.exp(-1))

    def test_unmoved_target_across_boundary(self):
        d, _, _ = self.run_case([[123, 456]], [[100, 400]])
        self.assertEqual(d[0], math.hypot(23, 56))

    def test_oversized_batch_rejected(self):
        with self.assertRaises(ValueError):
            self.run_case(np.zeros((513, 2)), [[0, 0]])

    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError):
            self.run_case([[float("nan"), 0]], [[0, 0]])

    def test_empty_inventory_rejected(self):
        with self.assertRaises(ValueError):
            finite_inventory_metrics([[0, 0]], np.empty((0, 2)), None)


if __name__ == "__main__":
    unittest.main()
