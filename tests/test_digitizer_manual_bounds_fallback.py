"""Unconfirmed Box bounds and selective, atomic manual axis completion."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
from WinUx.plotdigitizer.core.engine import DigitizerEngine
from WinUx.plotdigitizer.core.models import AxisScale
from WinUx.plotdigitizer.core import tick_detection as td
from test_digitizer_tick_auto_calibration import make_chart


class ManualBoundsFallbackTests(unittest.TestCase):
    def setUp(self):
        self.engine = DigitizerEngine()
        self.image, self.rect = make_chart()
        self.engine.apply_image(self.image, str(ROOT / 'tests' / 'manual-bounds.png'))
        self.engine.set_plot_rect_with_corner_anchors(self.rect, detect_ticks=False)

    def test_seeds_are_not_ready_and_incomplete_pair_cannot_confirm_them(self):
        self.assertFalse(self.engine.calibration_ready())
        before = self.engine.calibration.to_dict()
        with self.assertRaises(ValueError):
            self.engine.set_axis_bounds({'x1': 0})
        self.assertEqual(before, self.engine.calibration.to_dict())
        self.assertFalse(self.engine.auto_tick_verified_axes)

    def test_area_without_anchors_gets_unconfirmed_draggable_endpoints(self):
        self.engine.reset_calibration()
        self.engine.prepare_manual_axis_bounds(('x', 'y'))
        for key in ('x1', 'x2', 'y1', 'y2'):
            self.assertIsNotNone(getattr(self.engine.calibration, key))
        self.assertEqual(tuple(self.rect), self.engine.calibration.box_rect)
        self.assertFalse(self.engine.calibration_ready())
        self.assertFalse(self.engine.auto_tick_verified_axes)

    def test_manual_pairs_confirm_independently_and_undo_restores_confirmation(self):
        self.engine.set_axis_bounds({'x1': 3.2, 'x2': 0})  # Reversed axes are legal.
        self.assertFalse(self.engine.calibration_ready())
        self.engine.set_axis_bounds({'y1': 0, 'y2': 2000})
        self.assertTrue(self.engine.calibration_ready())
        self.engine.undo()
        self.assertFalse(self.engine.calibration_ready())
        self.assertEqual({'x'}, self.engine.auto_tick_verified_axes)
        self.engine.redo()
        self.assertTrue(self.engine.calibration_ready())

    def test_invalid_pairs_do_not_commit_or_erase_other_axis(self):
        self.engine.reset_calibration()
        self.engine.set_axis_scale(y=AxisScale.LOG10)
        self.engine.set_plot_rect_with_corner_anchors(self.rect, detect_ticks=False)
        self.engine.set_axis_bounds({'x1': 0, 'x2': 3.2})
        before = self.engine.calibration.to_dict()
        for values in ({'y1': 0, 'y2': 100}, {'y1': 10, 'y2': 10},
                       {'y1': 1, 'y2': float('nan')}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.engine.set_axis_bounds(values)
            self.assertEqual(before, self.engine.calibration.to_dict())
            self.assertEqual({'x'}, self.engine.auto_tick_verified_axes)

    def test_filling_missing_y_preserves_measured_x_ticks(self):
        full = td.detect_calibration_ticks(self.image, self.rect)
        partial = td.TickCalibrationDetection(full.x, td.AxisTickDetection('y', (), 0, AxisScale.LINEAR))
        self.engine.apply_tick_calibration_detection(partial, expected_rect=self.rect)
        self.assertFalse(self.engine.calibration_ready())
        points = list(self.engine.calibration.points_x)
        self.engine.set_axis_bounds({'y1': 0, 'y2': 2000})
        self.assertEqual(points, self.engine.calibration.points_x)
        self.assertEqual('ticks', self.engine.calibration.mapping_x)
        self.assertTrue(self.engine.calibration_ready())

    def test_project_and_history_keep_unconfirmed_values_unconfirmed(self):
        self.engine.set_axis_bounds({'x1': 0, 'x2': 3.2})
        temp = Path.home() / 'AppData' / 'Local' / 'Temp' / 'opencode'
        with tempfile.TemporaryDirectory(dir=temp) as folder:
            path = str(Path(folder) / 'partial.pdg')
            self.engine.save_project(path)
            loaded = DigitizerEngine()
            loaded.load_project(path)
            self.assertFalse(loaded.calibration_ready())
            self.assertEqual({'x'}, loaded.auto_tick_verified_axes)
            loaded.undo()
            self.assertFalse(loaded.auto_tick_verified_axes)
            loaded.redo()
            self.assertEqual({'x'}, loaded.auto_tick_verified_axes)


if __name__ == '__main__':
    unittest.main()
