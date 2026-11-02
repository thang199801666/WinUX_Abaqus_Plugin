"""Workflow edits restore complete state with one Undo/Redo command."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
from PIL import Image
from WinUx.plotdigitizer.core.engine import DigitizerEngine
from WinUx.plotdigitizer.core.models import SmartDetectionResult
from WinUx.plotdigitizer.core import tick_detection as td
from test_digitizer_tick_auto_calibration import make_chart


class WorkflowHistoryTests(unittest.TestCase):
    def make_engine(self):
        engine = DigitizerEngine()
        engine.apply_image(Image.new('RGB', (200, 160), 'white'), 'history.png')
        engine.set_plot_rect_with_corner_anchors((20, 20, 180, 140), detect_ticks=False)
        engine.set_axis_bounds(dict(x1=0, x2=10, y1=0, y2=100))
        for px, py in ((25, 120), (40, 115), (55, 90), (70, 92), (90, 60), (110, 35)):
            engine.add_manual_point(px, py)
        engine.add_dataset('Comparison')
        engine.set_active_dataset(0)
        engine._undo_stack.clear()
        return engine

    def test_workflow_commands_roundtrip_in_one_history_step(self):
        commands = {
            'pick_color': lambda e: e.set_curve_color((220, 20, 30)),
            'extract': lambda e: e.apply_smart_detect_result(SmartDetectionResult(
                plot_rect=e.plot_rect, curve_rgb=(220, 20, 30),
                extracted_pixels=[(30, 120), (50, 100), (70, 80)])),
            'add_point': lambda e: e.add_manual_point(125, 25),
            'move_point': lambda e: e.move_point('manual', 1, 42, 112),
            'edit_values': lambda e: e.set_point_values('manual', 1, 2, 30),
            'delete_points': lambda e: e.remove_points([('manual', 1), ('manual', 3)]),
            'smooth': lambda e: e.smooth_curve(),
            'increase_samples': lambda e: e.increase_samples(12),
            'reduce_count': lambda e: e.reduce_sample_count(3),
            'simplify': lambda e: e.reduce_samples(10),
            'manual_bounds': lambda e: e.set_axis_bounds(dict(y1=-100, y2=100)),
            'reset_axes': lambda e: e.reset_calibration(),
            'settings': lambda e: e.set_settings(replace(e.active_dataset.settings, tolerance=25)),
            'new_dataset': lambda e: e.add_dataset(),
            'duplicate_dataset': lambda e: e.duplicate_dataset(),
            'delete_dataset': lambda e: e.remove_dataset(1),
            'rename_dataset': lambda e: e.update_dataset(name='Renamed'),
            'lock_dataset': lambda e: e.update_dataset(locked=True),
            'clean_markers': lambda e: e.clean_markers(),
        }
        for name, command in commands.items():
            with self.subTest(command=name):
                engine = self.make_engine()
                before = engine._snapshot()
                command(engine)
                after = engine._snapshot()
                self.assertNotEqual(before, after)
                self.assertEqual(1, len(engine._undo_stack))
                self.assertTrue(engine.undo())
                self.assertEqual(before, engine._snapshot())
                self.assertTrue(engine.redo())
                self.assertEqual(after, engine._snapshot())

    def test_region_and_background_ocr_are_one_undo_step(self):
        image, rect = make_chart()
        engine = DigitizerEngine()
        engine.apply_image(image, 'chart.png')
        before = engine._snapshot()
        engine.set_plot_rect_with_corner_anchors(rect, detect_ticks=False)
        revision = engine.revision
        detection = td.detect_calibration_ticks(image, rect)
        engine.apply_tick_calibration_detection(detection, expected_rect=rect)
        self.assertTrue(engine.merge_region_tick_history(revision))
        self.assertEqual(1, len(engine._undo_stack))
        after = engine._snapshot()
        engine.undo()
        self.assertEqual(before, engine._snapshot())
        engine.redo()
        self.assertEqual(after, engine._snapshot())

    def test_history_merge_never_swallows_an_intervening_command(self):
        image, rect = make_chart()
        engine = DigitizerEngine()
        engine.apply_image(image, 'chart.png')
        engine.set_plot_rect_with_corner_anchors(rect, detect_ticks=False)
        revision = engine.revision
        engine.set_curve_color((220, 20, 30))
        detection = td.detect_calibration_ticks(image, rect)
        engine.apply_tick_calibration_detection(detection, expected_rect=rect)
        self.assertFalse(engine.merge_region_tick_history(revision))
        self.assertEqual(3, len(engine._undo_stack))


if __name__ == '__main__':
    unittest.main()
