"""Headless tests for calibration-anchor drag hit testing and preview state."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from WinUx.plotdigitizer.core import DigitizerEngine
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog


class CalibrationAnchorDragTests(unittest.TestCase):
    def setUp(self):
        self.dialog = object.__new__(PlotDigitizerDialog)
        self.dialog.engine = DigitizerEngine()
        self.dialog._active_tool = "axes"
        self.dialog._pick_mode = None
        self.dialog._fit_scale = 1.0
        self.dialog._zoom = 1.0
        self.dialog._anchor_drag_target = None
        self.dialog._anchor_drag_preview = None
        self.dialog._hover_anchor = None
        self.dialog.engine.calibration.set_anchor("x1", 100, 120, 0.0)
        self.dialog.engine.calibration.set_anchor("x2", 300, 120, 3.2)

    def test_anchor_hit_test_only_in_calibration_tool(self):
        self.assertEqual(self.dialog._nearest_anchor(104, 123), "x1")
        self.dialog._active_tool = "extract"
        self.assertIsNone(self.dialog._nearest_anchor(104, 123))

    def test_anchor_hit_test_is_disabled_during_pick_mode(self):
        self.dialog._pick_mode = "y1"
        self.assertIsNone(self.dialog._nearest_anchor(100, 120))

    def test_anchor_hit_radius_is_screen_space_stable(self):
        self.dialog._fit_scale = 2.0
        self.assertEqual(self.dialog._nearest_anchor(104, 120), "x1")  # 8 px on screen
        self.assertIsNone(self.dialog._nearest_anchor(106, 120))       # 12 px on screen

    def test_drag_preview_changes_draw_position_without_mutating_calibration(self):
        self.dialog._anchor_drag_target = "x1"
        self.dialog._anchor_drag_preview = (140.0, 155.0)
        self.assertEqual(self.dialog._anchor_display_pixel("x1"), (140.0, 155.0))
        anchor = self.dialog.engine.calibration.x1
        self.assertEqual((anchor.px, anchor.py, anchor.value), (100.0, 120.0, 0.0))

    def test_commit_preserves_axis_value_and_is_undoable(self):
        engine = self.dialog.engine
        engine.set_anchor("y1", 100, 300, -5.0)
        before = (engine.calibration.y1.px, engine.calibration.y1.py, engine.calibration.y1.value)
        engine.set_anchor("y1", 125, 280, engine.calibration.y1.value)
        self.assertEqual((engine.calibration.y1.px, engine.calibration.y1.py, engine.calibration.y1.value),
                         (125.0, 280.0, -5.0))
        self.assertTrue(engine.undo())
        self.assertEqual((engine.calibration.y1.px, engine.calibration.y1.py, engine.calibration.y1.value), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
