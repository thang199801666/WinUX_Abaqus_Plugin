"""Smart Region drag/two-click gestures must commit only a complete rectangle."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from DearUIQt.core import QPoint
from WinUx.plotdigitizer.core import DigitizerEngine
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog


class SmartRegionTests(unittest.TestCase):
    def setUp(self):
        self.dialog = dialog = object.__new__(PlotDigitizerDialog)
        dialog.engine = DigitizerEngine()
        dialog.engine.image = Image.new('RGB', (400, 300), 'white')
        dialog._pick_mode = None
        dialog._active_tool = 'axes'
        dialog._edit_enabled = False
        dialog._drag_start = dialog._drag_preview = dialog._drag_target = None
        dialog._anchor_drag_target = dialog._point_press = None
        dialog._region_first_corner = dialog._region_press = None
        dialog._fit_scale = dialog._zoom = 1
        dialog.calibration_hint = 'hint'
        for name in ('_set_status', '_show_tool', 'set_control_visible', 'set_control_value',
                     '_paint_pointer', '_redraw', '_focus_canvas_keyboard', '_reset_point_gesture',
                     '_start_tick_calibration', '_set_calibration_method'):
            setattr(dialog, name, Mock())
        dialog._begin_pick('area')

    def mouse(self, point, phase, *, inside=True):
        with patch.object(self.dialog, '_mouse_in_canvas', return_value=inside), \
                patch.object(self.dialog, '_canvas_to_image', return_value=point), \
                patch('WinUx.plotdigitizer.ui.dialog.QCursor.pos', return_value=QPoint(0, 0)):
            getattr(self.dialog, '_mouse_left' if phase == 'down' else '_mouse_left_up')()

    def click(self, point):
        self.mouse(point, 'down')
        self.mouse(point, 'up')

    def assert_region(self, rect):
        self.assertEqual(rect, self.dialog.engine.plot_rect)
        self.assertEqual(None, self.dialog._pick_mode)
        self.assertIsNone(self.dialog._region_first_corner)
        self.assertIsNone(self.dialog._drag_start)
        self.dialog._start_tick_calibration.assert_called_once_with(rect)
        c = self.dialog.engine.calibration
        self.assertEqual((rect[0], rect[3]), (c.x1.px, c.x1.py))
        self.assertEqual((c.x1.px, c.x1.py), (c.y1.px, c.y1.py))

    def test_drag_still_commits_in_one_gesture(self):
        self.mouse((20, 30), 'down')
        self.mouse((300, 240), 'up')
        self.assert_region((20, 30, 300, 240))

    def test_two_clicks_commit_only_after_second_release(self):
        revision = self.dialog.engine.revision
        self.click((20, 30))
        self.assertEqual(revision, self.dialog.engine.revision)
        self.assertIsNone(self.dialog.engine.plot_rect)
        self.assertEqual((20, 30), self.dialog._region_first_corner)
        self.dialog._start_tick_calibration.assert_not_called()
        self.mouse((300, 240), 'down')
        self.assertIsNone(self.dialog.engine.plot_rect)
        self.mouse((300, 240), 'up')
        self.assert_region((20, 30, 300, 240))

    def test_reverse_corner_order_is_normalized(self):
        self.click((300, 240))
        self.click((20, 30))
        self.assert_region((20, 30, 300, 240))

    def test_duplicate_release_does_not_commit_a_hover_rectangle(self):
        self.click((20, 30))
        self.mouse((300, 240), 'up')
        self.assertIsNone(self.dialog.engine.plot_rect)
        self.dialog._start_tick_calibration.assert_not_called()
        self.click((300, 240))
        self.mouse((300, 240), 'up')
        self.assert_region((20, 30, 300, 240))

    def test_small_click_jitter_uses_screen_not_image_pixels(self):
        self.dialog._fit_scale = 2
        self.dialog._zoom = 2
        self.mouse((20, 30), 'down')
        self.mouse((20.5, 30.5), 'up')
        self.assertEqual((20, 30), self.dialog._region_first_corner)
        self.dialog._start_tick_calibration.assert_not_called()
        self.click((300, 240))
        self.assert_region((20, 30, 300, 240))

    def test_degenerate_second_corner_can_be_retried(self):
        self.click((20, 30))
        self.click((20, 240))
        self.assertIsNone(self.dialog.engine.plot_rect)
        self.assertEqual((20, 30), self.dialog._region_first_corner)
        self.dialog._start_tick_calibration.assert_not_called()
        self.click((300, 240))
        self.assert_region((20, 30, 300, 240))

    def test_escape_discards_first_corner_without_mutating_engine(self):
        self.click((20, 30))
        revision = self.dialog.engine.revision
        self.dialog._close_from_escape()
        self.assertIsNone(self.dialog._region_first_corner)
        self.assertIsNone(self.dialog._drag_start)
        self.assertIsNone(self.dialog._pick_mode)
        self.assertEqual(revision, self.dialog.engine.revision)
        self.dialog._start_tick_calibration.assert_not_called()

    def test_reactivating_tool_starts_a_fresh_rectangle(self):
        self.click((20, 30))
        self.dialog._begin_pick('area')
        self.click((100, 100))
        self.assertEqual((100, 100), self.dialog._region_first_corner)
        self.assertIsNone(self.dialog.engine.plot_rect)
        self.click((300, 240))
        self.assert_region((100, 100, 300, 240))

    def test_second_click_outside_image_is_ignored(self):
        self.click((20, 30))
        self.click((500, 350))
        self.assertIsNone(self.dialog.engine.plot_rect)
        self.assertEqual((20, 30), self.dialog._region_first_corner)
        self.click((300, 240))
        self.assert_region((20, 30, 300, 240))


if __name__ == '__main__':
    unittest.main()
