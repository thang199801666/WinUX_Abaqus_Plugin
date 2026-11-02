"""Pure regression tests for Reference Chart XY sample reduction."""
import math
import unittest

from WinUx.services.reference_charts import reduce_reference_samples


class ReferenceSampleReductionTests(unittest.TestCase):
    def test_exact_removes_redundant_straight_line_samples(self):
        points = [[i / 1000.0, 3.0 + 2.0 * i / 1000.0] for i in range(1001)]
        reduced = reduce_reference_samples(points, 0.0)
        self.assertEqual(reduced, [points[0], points[-1]])

    def test_corner_and_endpoints_are_preserved(self):
        points = [[0, 0], [0.5, 0], [1, 0], [1, 0.5], [1, 1]]
        reduced = reduce_reference_samples(points, 0.0001)
        self.assertEqual(reduced[0], [0.0, 0.0])
        self.assertEqual(reduced[-1], [1.0, 1.0])
        self.assertIn([1.0, 0.0], reduced)

    def test_high_fidelity_reduces_dense_smooth_curve(self):
        count = 13873
        points = []
        for index in range(count):
            x = 2.2 * index / (count - 1)
            y = 0.42 * x + 0.025 * math.sin(4 * x) + 0.007 * math.sin(16 * x)
            points.append([x, y])
        reduced = reduce_reference_samples(points, 0.0001)
        self.assertLess(len(reduced), count // 10)
        self.assertEqual(reduced[0], points[0])
        self.assertEqual(reduced[-1], points[-1])

    def test_normalization_makes_units_irrelevant(self):
        base = [[0, 0], [0.25, 0.1], [0.5, 0.4], [0.75, 0.9], [1, 1]]
        scaled = [[x * 1000.0, y * 1.0e6] for x, y in base]
        reduced_base = reduce_reference_samples(base, 0.01)
        reduced_scaled = reduce_reference_samples(scaled, 0.01)
        self.assertEqual(len(reduced_base), len(reduced_scaled))

    def test_invalid_tolerance_is_rejected(self):
        with self.assertRaises(ValueError):
            reduce_reference_samples([[0, 0], [1, 1]], -1)
        with self.assertRaises(ValueError):
            reduce_reference_samples([[0, 0], [1, 1]], float('nan'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
