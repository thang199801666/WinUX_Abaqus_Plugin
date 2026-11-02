"""Headless tests for independent calibration-anchor picking."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from WinUx.plotdigitizer.core import AxisScale, DigitizerEngine
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog


class AnchorPickValueTests(unittest.TestCase):
    def setUp(self):
        self.dialog = object.__new__(PlotDigitizerDialog)
        self.dialog.engine = DigitizerEngine()

    def test_linear_unset_anchors_use_zero_one_seed(self):
        self.assertEqual(self.dialog._anchor_pick_value("x1"), 0.0)
        self.assertEqual(self.dialog._anchor_pick_value("x2"), 1.0)
        self.assertEqual(self.dialog._anchor_pick_value("y1"), 0.0)
        self.assertEqual(self.dialog._anchor_pick_value("y2"), 1.0)

    def test_logarithmic_unset_anchors_use_positive_seed(self):
        self.dialog.engine.calibration.scale_x = AxisScale.LOG10
        self.dialog.engine.calibration.scale_y = AxisScale.LN
        self.assertEqual(self.dialog._anchor_pick_value("x1"), 1.0)
        self.assertEqual(self.dialog._anchor_pick_value("x2"), 10.0)
        self.assertEqual(self.dialog._anchor_pick_value("y1"), 1.0)
        self.assertEqual(self.dialog._anchor_pick_value("y2"), 10.0)

    def test_existing_anchor_keeps_edited_value_when_repicked(self):
        self.dialog.engine.calibration.set_anchor("x1", 10, 20, 3.2)
        self.assertEqual(self.dialog._anchor_pick_value("x1"), 3.2)

    def test_new_seed_never_duplicates_paired_anchor(self):
        self.dialog.engine.calibration.set_anchor("x1", 10, 20, 1.0)
        self.assertEqual(self.dialog._anchor_pick_value("x2"), 2.0)
        self.dialog.engine.calibration = type(self.dialog.engine.calibration)(scale_x=AxisScale.LOG10)
        self.dialog.engine.calibration.set_anchor("x1", 10, 20, 10.0)
        self.assertEqual(self.dialog._anchor_pick_value("x2"), 100.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
