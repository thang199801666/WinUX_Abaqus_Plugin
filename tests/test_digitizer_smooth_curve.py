"""Arc-length redistribution for Plot Digitizer Smooth Curve."""
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from WinUx.plotdigitizer.core import DigitizerEngine
from WinUx.plotdigitizer.core.models import DataPoint
from WinUx.plotdigitizer.core.reduction import resample_polyline


def distance_to_polyline(point, polyline):
    px, py = point
    best = float("inf")
    for first, last in zip(polyline, polyline[1:]):
        ax, ay = first
        bx, by = last
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        if length_sq == 0:
            qx, qy = ax, ay
        else:
            t = ((px - ax) * dx + (py - ay) * dy) / length_sq
            t = max(0.0, min(1.0, t))
            qx, qy = ax + t * dx, ay + t * dy
        best = min(best, math.hypot(px - qx, py - qy))
    return best


class SmoothCurveTests(unittest.TestCase):
    def test_resample_uses_arc_length_not_x_or_y(self):
        original = [(0, 0), (2, 0), (10, 0), (10, 3), (10, 10)]
        result = resample_polyline(original, 5)
        self.assertEqual(result, [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0),
                                  (10.0, 5.0), (10.0, 10.0)])
        for point in result:
            self.assertLessEqual(distance_to_polyline(point, original), 1e-9)

    def test_mixed_manual_and_automatic_points_become_even_on_one_curve(self):
        engine = DigitizerEngine()
        ds = engine.active_dataset
        ds.extracted_pixels = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
        ds.extracted_breaks = []
        ds.manual_points = [DataPoint(1.0, 0.0), DataPoint(10.0, 1.0)]
        original_curve = [(0.0, 0.0), (1.0, 0.0), (10.0, 0.0),
                          (10.0, 1.0), (10.0, 10.0)]

        moved = engine.smooth_curve()
        self.assertEqual(moved, 2)
        self.assertEqual(ds.extracted_pixels,
                         [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)])
        self.assertEqual([(p.px, p.py) for p in ds.manual_points],
                         [(5.0, 0.0), (10.0, 5.0)])
        all_points = [ds.extracted_pixels[0], (ds.manual_points[0].px, ds.manual_points[0].py),
                      ds.extracted_pixels[1], (ds.manual_points[1].px, ds.manual_points[1].py),
                      ds.extracted_pixels[2]]
        for point in all_points:
            self.assertLessEqual(distance_to_polyline(point, original_curve), 1e-9)
        self.assertEqual(len(ds.extracted_pixels) + len(ds.manual_points), 5)

    def test_manual_only_preserves_acquisition_path_instead_of_axis_sorting(self):
        engine = DigitizerEngine()
        ds = engine.active_dataset
        original = [(0.0, 0.0), (2.0, 0.0), (10.0, 0.0),
                    (10.0, 2.0), (10.0, 10.0)]
        ds.manual_points = [DataPoint(x, y) for x, y in original]

        engine.smooth_curve()
        result = [(p.px, p.py) for p in ds.manual_points]
        self.assertEqual(result, [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0),
                                  (10.0, 5.0), (10.0, 10.0)])
        for point in result:
            self.assertLessEqual(distance_to_polyline(point, original), 1e-9)

    def test_disconnected_extraction_segments_are_never_bridged(self):
        engine = DigitizerEngine()
        ds = engine.active_dataset
        ds.extracted_pixels = [(0.0, 0.0), (1.0, 0.0), (10.0, 0.0),
                               (100.0, 0.0), (101.0, 0.0), (110.0, 0.0)]
        ds.extracted_breaks = [3]
        engine.smooth_curve()
        self.assertEqual(ds.extracted_pixels,
                         [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0),
                          (100.0, 0.0), (105.0, 0.0), (110.0, 0.0)])
        self.assertEqual(ds.extracted_breaks, [3])

    def test_undo_restores_pre_smooth_positions(self):
        engine = DigitizerEngine()
        ds = engine.active_dataset
        ds.manual_points = [DataPoint(0, 0), DataPoint(1, 0), DataPoint(10, 0)]
        before = [(p.px, p.py) for p in ds.manual_points]
        self.assertGreater(engine.smooth_curve(), 0)
        self.assertTrue(engine.can_undo)
        self.assertTrue(engine.undo())
        self.assertEqual([(p.px, p.py) for p in engine.active_dataset.manual_points], before)

    def test_locked_and_too_short_datasets_are_rejected(self):
        engine = DigitizerEngine()
        engine.active_dataset.manual_points = [DataPoint(0, 0), DataPoint(1, 1)]
        with self.assertRaisesRegex(ValueError, "At least 3"):
            engine.smooth_curve()
        engine.active_dataset.manual_points.append(DataPoint(2, 2))
        engine.active_dataset.locked = True
        with self.assertRaisesRegex(ValueError, "Unlock"):
            engine.smooth_curve()


if __name__ == "__main__":
    unittest.main(verbosity=2)
