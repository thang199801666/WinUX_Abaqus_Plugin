"""Count-based Increase/Reduce Samples for Plot Digitizer."""
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from WinUx.plotdigitizer.core import DigitizerEngine
from WinUx.plotdigitizer.core.models import DataPoint


def distance_to_polyline(point, polyline):
    px, py = point
    best = float("inf")
    for first, last in zip(polyline, polyline[1:]):
        ax, ay = first
        bx, by = last
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        if length_sq <= 0:
            qx, qy = ax, ay
        else:
            t = ((px - ax) * dx + (py - ay) * dy) / length_sq
            t = max(0.0, min(1.0, t))
            qx, qy = ax + t * dx, ay + t * dy
        best = min(best, math.hypot(px - qx, py - qy))
    return best


class SampleResamplingTests(unittest.TestCase):
    def test_increase_doubles_manual_curve_and_keeps_exact_geometry(self):
        engine = DigitizerEngine()
        original = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
        engine.active_dataset.manual_points = [DataPoint(x, y) for x, y in original]

        added = engine.increase_samples()
        result = [(point.px, point.py) for point in engine.active_dataset.manual_points]
        self.assertEqual(added, 3)
        self.assertEqual(len(result), 6)
        for point in original:
            self.assertIn(point, result)
        for point in result:
            self.assertLessEqual(distance_to_polyline(point, original), 1e-9)

    def test_increase_mixed_manual_auto_preserves_existing_vertices(self):
        engine = DigitizerEngine()
        ds = engine.active_dataset
        ds.extracted_pixels = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
        ds.extracted_breaks = []
        ds.manual_points = [DataPoint(5.0, 1.0), DataPoint(10.0, 5.0)]
        original_auto = list(ds.extracted_pixels)
        original_manual = [(point.px, point.py) for point in ds.manual_points]

        added = engine.increase_samples()
        self.assertEqual(added, 5)
        self.assertEqual(ds.extracted_pixels, original_auto)
        self.assertEqual([(p.px, p.py) for p in ds.manual_points[:2]], original_manual)
        self.assertEqual(len(ds.extracted_pixels) + len(ds.manual_points), 10)

    def test_increase_honors_explicit_target_count(self):
        engine = DigitizerEngine()
        engine.active_dataset.manual_points = [DataPoint(float(x), 0.0) for x in range(6)]
        added = engine.increase_samples(target_count=9)
        self.assertEqual(added, 3)
        self.assertEqual(len(engine.active_dataset.manual_points), 9)

    def test_increase_never_bridges_known_extraction_gap(self):
        engine = DigitizerEngine()
        ds = engine.active_dataset
        ds.extracted_pixels = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0),
                               (100.0, 0.0), (110.0, 0.0), (110.0, 10.0)]
        ds.extracted_breaks = [3]
        engine.increase_samples()
        inserted = [(p.px, p.py) for p in ds.manual_points]
        self.assertTrue(inserted)
        self.assertTrue(all(x <= 10.0 or x >= 100.0 for x, _y in inserted))
        self.assertEqual(ds.extracted_breaks, [3])

    def test_reduce_halves_smooth_curve_and_retains_endpoints(self):
        engine = DigitizerEngine()
        ds = engine.active_dataset
        ds.manual_points = [DataPoint(float(x), (x * x) / 100.0) for x in range(11)]
        first = (ds.manual_points[0].px, ds.manual_points[0].py)
        last = (ds.manual_points[-1].px, ds.manual_points[-1].py)

        removed = engine.reduce_sample_count()
        result = [(p.px, p.py) for p in ds.manual_points]
        self.assertEqual(removed, 5)
        self.assertEqual(len(result), 6)
        self.assertEqual(result[0], first)
        self.assertEqual(result[-1], last)

    def test_reduce_honors_explicit_target_count_on_smooth_curve(self):
        engine = DigitizerEngine()
        ds = engine.active_dataset
        ds.manual_points = [DataPoint(float(x), (x * x) / 100.0) for x in range(11)]
        removed = engine.reduce_sample_count(target_count=7)
        self.assertEqual(removed, 4)
        self.assertEqual(len(ds.manual_points), 7)

    def test_reduce_preserves_hard_corner_instead_of_cutting_across_it(self):
        engine = DigitizerEngine()
        ds = engine.active_dataset
        ds.manual_points = [DataPoint(0.0, 0.0), DataPoint(10.0, 0.0), DataPoint(10.0, 10.0)]
        self.assertEqual(engine.reduce_sample_count(), 0)
        self.assertEqual([(p.px, p.py) for p in ds.manual_points],
                         [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)])

    def test_increase_and_reduce_are_undoable(self):
        engine = DigitizerEngine()
        ds = engine.active_dataset
        ds.manual_points = [DataPoint(float(x), 0.0) for x in range(6)]
        before = [(p.px, p.py) for p in ds.manual_points]
        self.assertGreater(engine.increase_samples(), 0)
        self.assertTrue(engine.undo())
        self.assertEqual([(p.px, p.py) for p in engine.active_dataset.manual_points], before)
        self.assertGreater(engine.reduce_sample_count(), 0)
        self.assertTrue(engine.undo())
        self.assertEqual([(p.px, p.py) for p in engine.active_dataset.manual_points], before)

    def test_locked_dataset_rejects_both_operations(self):
        engine = DigitizerEngine()
        engine.active_dataset.manual_points = [DataPoint(0, 0), DataPoint(1, 0), DataPoint(2, 0)]
        engine.active_dataset.locked = True
        with self.assertRaisesRegex(ValueError, "Unlock"):
            engine.increase_samples()
        with self.assertRaisesRegex(ValueError, "Unlock"):
            engine.reduce_sample_count()


if __name__ == "__main__":
    unittest.main(verbosity=2)
