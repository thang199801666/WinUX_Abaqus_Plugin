"""Compatibility guards for the split Plot Digitizer tick detector."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from WinUx.plotdigitizer.core import tick_detection as td
from WinUx.plotdigitizer.core.ticks import pipeline, pixels, recognition, source_ocr


class TickDetectionArchitectureTests(unittest.TestCase):
    def test_public_result_types_keep_historical_module_path(self):
        self.assertEqual("WinUx.plotdigitizer.core.tick_detection", td.TickReading.__module__)
        self.assertEqual("WinUx.plotdigitizer.core.tick_detection", td.AxisTickDetection.__module__)
        self.assertEqual("WinUx.plotdigitizer.core.tick_detection", td.TickCalibrationDetection.__module__)

    def test_patch_of_pixel_helper_propagates_to_consumers(self):
        sentinel = object()
        with patch.object(td, "_binary_mask", return_value=sentinel) as patched:
            self.assertIs(pixels._binary_mask, patched)
            self.assertIs(recognition._binary_mask, patched)
            self.assertIs(source_ocr._binary_mask, patched)
        self.assertIs(pixels._binary_mask, td._binary_mask)
        self.assertIs(recognition._binary_mask, td._binary_mask)
        self.assertIs(source_ocr._binary_mask, td._binary_mask)

    def test_patch_of_pipeline_entrypoint_is_seen_by_calibration(self):
        empty_x = td.AxisTickDetection("x", (), 0.0, td.AxisScale.LINEAR)
        empty_y = td.AxisTickDetection("y", (), 0.0, td.AxisScale.LINEAR)
        calls = []

        def fake_axis(_image, _rect, axis, scale, **_kwargs):
            calls.append((axis, scale))
            return empty_x if axis == "x" else empty_y

        from PIL import Image
        with patch.object(td, "_detect_axis", side_effect=fake_axis) as patched:
            result = td.detect_calibration_ticks(Image.new("RGB", (20, 20)), (2, 2, 18, 18),
                                                 align_axes=False)
            self.assertIs(pipeline._detect_axis, patched)
        self.assertEqual(["x", "y"], [axis for axis, _scale in calls])
        self.assertIs(result.x, empty_x)
        self.assertIs(result.y, empty_y)


if __name__ == "__main__":
    unittest.main()
