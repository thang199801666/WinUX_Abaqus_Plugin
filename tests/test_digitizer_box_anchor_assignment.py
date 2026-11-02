"""Headless tests for assigning calibration anchors from a chart-area box."""
from pathlib import Path
import sys
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from WinUx.plotdigitizer.core import AxisScale, DigitizerEngine


class BoxAnchorAssignmentTests(unittest.TestCase):
    def setUp(self):
        self.engine = DigitizerEngine()
        self.engine.apply_image(Image.new("RGB", (400, 300), "white"), str(ROOT / "tests" / "box-anchor.png"))

    def _anchors(self):
        cal = self.engine.calibration
        return {
            key: (getattr(cal, key).px, getattr(cal, key).py, getattr(cal, key).value)
            for key in ("x1", "x2", "y1", "y2")
        }

    def test_box_assigns_axis_corners_and_linear_seed_values(self):
        self.engine.set_plot_rect_with_corner_anchors((40, 30, 340, 250))
        self.assertEqual(self.engine.plot_rect, (40, 30, 340, 250))
        self.assertEqual(self._anchors(), {
            "x1": (40.0, 250.0, 0.0),
            "x2": (340.0, 250.0, 1.0),
            "y1": (40.0, 250.0, 0.0),
            "y2": (40.0, 30.0, 1.0),
        })
        self.assertFalse(self.engine.calibration_ready())  # Box seeds need user/OCR confirmation.

    def test_reverse_drag_is_normalized_before_anchor_assignment(self):
        self.engine.set_plot_rect_with_corner_anchors((340, 250, 40, 30))
        self.assertEqual(self.engine.plot_rect, (40, 30, 340, 250))
        anchors = self._anchors()
        self.assertEqual(anchors["x1"][:2], (40.0, 250.0))
        self.assertEqual(anchors["x2"][:2], (340.0, 250.0))
        self.assertEqual(anchors["y1"][:2], (40.0, 250.0))
        self.assertEqual(anchors["y2"][:2], (40.0, 30.0))

    def test_redrawing_box_preserves_existing_axis_values(self):
        self.engine.set_anchor("x1", 10, 250, -2.5)
        self.engine.set_anchor("x2", 350, 250, 8.25)
        self.engine.set_anchor("y1", 10, 250, 100.0)
        self.engine.set_anchor("y2", 10, 20, 2500.0)
        self.engine.set_plot_rect_with_corner_anchors((60, 40, 320, 230))
        anchors = self._anchors()
        self.assertEqual(anchors["x1"], (60.0, 230.0, -2.5))
        self.assertEqual(anchors["x2"], (320.0, 230.0, 8.25))
        self.assertEqual(anchors["y1"], (60.0, 230.0, 100.0))
        self.assertEqual(anchors["y2"], (60.0, 40.0, 2500.0))

    def test_logarithmic_axes_receive_positive_seed_values(self):
        self.engine.calibration.scale_x = AxisScale.LOG10
        self.engine.calibration.scale_y = AxisScale.LN
        self.engine.set_plot_rect_with_corner_anchors((20, 25, 380, 275))
        anchors = self._anchors()
        self.assertEqual((anchors["x1"][2], anchors["x2"][2]), (1.0, 10.0))
        self.assertEqual((anchors["y1"][2], anchors["y2"][2]), (1.0, 10.0))
        self.assertFalse(self.engine.calibration_ready())

    def test_box_and_four_anchors_are_one_undo_step(self):
        self.assertFalse(self.engine.can_undo)
        self.engine.set_plot_rect_with_corner_anchors((40, 30, 340, 250))
        self.assertTrue(self.engine.can_undo)
        self.assertEqual(len(self.engine._undo_stack), 1)
        self.assertEqual(self.engine._undo_stack[-1][0], "Set plot area and calibration anchors")
        self.assertTrue(self.engine.undo())
        self.assertIsNone(self.engine.plot_rect)
        self.assertTrue(all(getattr(self.engine.calibration, key) is None
                            for key in ("x1", "x2", "y1", "y2")))
        self.assertFalse(self.engine.can_undo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
