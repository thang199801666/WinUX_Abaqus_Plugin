from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_winux
run_winux._configure_bundled_dependencies(str(Path(__file__).resolve().parents[1]))

from WinUx.ui.behaviors.input.pointer import PointerRoutingMixin
from WinUx.ui.components.explorer.drag_preview import DragPreviewHelper
from DearUIQt.gui import QCursor


class Host(PointerRoutingMixin):
    pass


class DynamicPanel:
    def __init__(self, rect):
        self.rect = rect
    def screen_rect(self):
        return self.rect


class M36ResizeGeometryTests(unittest.TestCase):
    def make_host(self, width, height, divider_ratio=.5, gutter=8.0):
        top = 58.0
        bottom = max(top + 3.0, height * .62)
        divider = max(80.0, min(width - 80.0, width * divider_ratio))
        host = Host()
        host.left = DynamicPanel((0.0, top, divider, bottom))
        host.right = DynamicPanel((divider + gutter, top, float(width), bottom))
        host.left_parent = None
        host.right_parent = None
        return host, divider, top, bottom, gutter

    def test_target_tracks_live_geometry_across_window_sizes(self):
        for width, height in ((420, 320), (640, 480), (900, 700),
                              (1280, 720), (1600, 1000), (2560, 1440)):
            for ratio in (.25, .5, .75):
                with self.subTest(size=(width, height), ratio=ratio):
                    host, divider, top, bottom, gutter = self.make_host(width, height, ratio)
                    y = (top + bottom) / 2.0
                    left, point = host.panel_and_point_at(divider * .5, y)
                    self.assertIs(left, host.left)
                    self.assertEqual(point, (divider * .5, y))
                    right_x = divider + gutter + (width - divider - gutter) * .5
                    right, point = host.panel_and_point_at(right_x, y)
                    self.assertIs(right, host.right)
                    self.assertEqual(point, (right_x, y))
                    panel, point = host.panel_and_point_at(divider + gutter * .5, y)
                    self.assertIsNone(panel)
                    self.assertIsNone(point)

    def test_resize_uses_new_rect_immediately_not_old_divider_cache(self):
        host, divider, top, bottom, gutter = self.make_host(900, 700, .5)
        host._last_panel_divider = divider  # deliberately stale legacy cache
        host._last_content_size = (900, 700)
        # Resize + move divider left in the current frame.
        host.left.rect = (0.0, top, 260.0, bottom)
        host.right.rect = (268.0, top, 1200.0, bottom)
        panel, point = host.panel_and_point_at(700.0, (top + bottom) / 2.0)
        self.assertIs(panel, host.right)
        self.assertEqual(point[0], 700.0)
        panel, _ = host.panel_and_point_at(264.0, (top + bottom) / 2.0)
        self.assertIsNone(panel)

    def test_missing_live_geometry_never_guesses_from_cache(self):
        host, _, _, _, _ = self.make_host(900, 700)
        host.left.rect = None
        host.right.rect = None
        host._last_panel_divider = 450
        host._last_content_size = (900, 700)
        panel, point = host.panel_and_point_at(100, 200)
        self.assertIsNone(panel)
        self.assertIsNone(point)

    def make_preview(self, content=(180.0, 60.0)):
        helper = object.__new__(DragPreviewHelper)
        helper.active = True
        helper._primary_viewport = True
        helper._group = Mock()
        helper._content_size = content
        helper._runtime = None
        return helper

    def test_preview_stays_inside_each_live_window_size(self):
        for width, height in ((320, 240), (640, 480), (900, 700),
                              (1920, 1080), (2560, 1440)):
            with self.subTest(size=(width, height)):
                helper = self.make_preview()
                helper._paint_bounds = Mock(return_value=(0.0, 0.0, float(width), float(height)))
                with patch.object(QCursor, 'paintPos', return_value=(width - 2, height - 2)):
                    helper.moveToCursor()
                x, y = helper._group.setTranslation.call_args.args
                self.assertGreaterEqual(x, 4.0)
                self.assertGreaterEqual(y, 4.0)
                self.assertLessEqual(x + helper._content_size[0], width - 4.0 + 1e-6)
                self.assertLessEqual(y + helper._content_size[1], height - 4.0 + 1e-6)

    def test_preview_uses_paint_cursor_offset_when_not_near_edge(self):
        helper = self.make_preview((160.0, 55.0))
        helper._paint_bounds = Mock(return_value=(0.0, 0.0, 900.0, 700.0))
        with patch.object(QCursor, 'paintPos', return_value=(200, 150)):
            helper.moveToCursor()
        helper._group.setTranslation.assert_called_once_with(
            200.0 + helper.OFFSET_X, 150.0 + helper.OFFSET_Y)


if __name__ == '__main__':
    unittest.main(verbosity=2)
