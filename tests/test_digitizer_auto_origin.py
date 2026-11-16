"""Automatic extraction must include one exact chart-origin sample after calibration."""
from pathlib import Path
import sys
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from WinUx.plotdigitizer.core import AxisScale, DigitizerEngine
from WinUx.plotdigitizer.core.models import SmartDetectionResult


class AutomaticOriginTests(unittest.TestCase):
    def setUp(self):
        self.engine = DigitizerEngine()
        self.engine.apply_image(Image.new("RGB", (400, 300), "white"), str(ROOT / "tests" / "auto-origin.png"))
        # Origin is the chart's lower-left corner at pixel (40, 250).
        self.engine.set_plot_rect((40, 30, 360, 250))
        self.engine.calibrate_plot_rect(0.0, 3.2, 0.0, 2.0)

    def _apply(self, points):
        return self.engine.apply_smart_detect_result(SmartDetectionResult(
            plot_rect=self.engine.plot_rect,
            curve_rgb=(255, 0, 0),
            extracted_pixels=list(points),
        ))

    def test_auto_generation_inserts_exact_zero_zero_sample(self):
        self.assertTrue(self._apply([(55.0, 240.0), (100.0, 210.0), (180.0, 150.0)]))
        ds = self.engine.active_dataset
        self.assertIn((40.0, 250.0), ds.extracted_pixels)
        self.assertIn((0.0, 0.0), ds.extracted_data)
        self.assertEqual(ds.extracted_data.count((0.0, 0.0)), 1)

    def test_near_origin_extracted_sample_is_snapped_not_duplicated(self):
        self.assertTrue(self._apply([(40.4, 249.7), (80.0, 220.0), (150.0, 180.0)]))
        ds = self.engine.active_dataset
        self.assertEqual(len(ds.extracted_pixels), 3)
        self.assertEqual(ds.extracted_pixels[0], (40.0, 250.0))
        self.assertEqual(ds.extracted_data[0], (0.0, 0.0))
        self.assertEqual(ds.extracted_data.count((0.0, 0.0)), 1)

    def test_repeated_auto_generation_still_has_one_origin(self):
        points = [(55.0, 240.0), (100.0, 210.0), (180.0, 150.0)]
        self.assertTrue(self._apply(points))
        self.assertTrue(self._apply(points))
        ds = self.engine.active_dataset
        self.assertEqual(ds.extracted_pixels.count((40.0, 250.0)), 1)
        self.assertEqual(ds.extracted_data.count((0.0, 0.0)), 1)

    def test_origin_is_inserted_by_curve_order_not_x_or_y_sort(self):
        # Backtracking path: nearest arc location to origin is before the first sample.
        points = [(60.0, 238.0), (120.0, 180.0), (80.0, 150.0), (160.0, 100.0)]
        self.assertTrue(self._apply(points))
        ds = self.engine.active_dataset
        self.assertEqual(ds.extracted_pixels[0], (40.0, 250.0))
        self.assertEqual(ds.extracted_pixels[1:], points)

    def test_log_axis_does_not_create_invalid_zero_sample(self):
        engine = DigitizerEngine()
        engine.apply_image(Image.new("RGB", (400, 300), "white"), str(ROOT / "tests" / "auto-origin-log.png"))
        engine.plot_rect = (40, 30, 360, 250)
        engine.calibration.scale_x = AxisScale.LOG10
        engine.set_anchor("x1", 40, 250, 1.0)
        engine.set_anchor("x2", 360, 250, 100.0)
        engine.set_anchor("y1", 40, 250, 0.0)
        engine.set_anchor("y2", 40, 30, 2.0)
        result = SmartDetectionResult(
            plot_rect=engine.plot_rect,
            curve_rgb=(255, 0, 0),
            extracted_pixels=[(60.0, 230.0), (120.0, 200.0)],
        )
        self.assertTrue(engine.apply_smart_detect_result(result))
        self.assertEqual(len(engine.active_dataset.extracted_pixels), 2)
        self.assertNotIn((0.0, 0.0), engine.active_dataset.extracted_data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
