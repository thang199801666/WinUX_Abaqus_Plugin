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
    WIDTH = 900
    HEIGHT = 700
    FILE_STATUS_HEIGHT = 20
    FILE_PANEL_SPLITTER_GUTTER_SIZE = 8
    _top_ratio = .6


class M35DragCoordinateContractTests(unittest.TestCase):
    def make_host(self):
        left = SimpleNamespace(
            screen_rect=lambda: (0.0, 60.0, 440.0, 470.0),
            _last_size=(440, 410),
        )
        right = SimpleNamespace(
            screen_rect=lambda: (448.0, 60.0, 900.0, 470.0),
            _last_size=(452, 410),
        )
        host = Host()
        host.left = left
        host.right = right
        host.left_parent = None
        host.right_parent = None
        host.layout_root = None
        host._last_content_size = (900, 700)
        host._last_panel_divider = 440
        return host, left, right

    def test_internal_drag_uses_exact_primary_client_point(self):
        host, left, right = self.make_host()
        panel, point = host.panel_and_point_at(120, 240)
        self.assertIs(panel, left)
        self.assertEqual(point, (120.0, 240.0))
        panel, point = host.panel_and_point_at(720, 240)
        self.assertIs(panel, right)
        self.assertEqual(point, (720.0, 240.0))

    def test_desktop_offset_variant_is_not_probed(self):
        host, left, right = self.make_host()
        # Pretend the host window is at desktop x=500.  The old +/- heuristic
        # could turn this off-pane primary-client point into x=120 and silently
        # report the left pane.  M35 must reject it instead.
        import WinUx.ui.behaviors.input.pointer as pointer_module
        old_dpg = pointer_module.dpg
        pointer_module.dpg = SimpleNamespace(
            does_item_exist=lambda _tag: False,
            get_viewport_client_width=lambda: 900,
            get_viewport_client_height=lambda: 700,
        )
        try:
            panel, point = host.panel_and_point_at(620, 540)
        finally:
            pointer_module.dpg = old_dpg
        self.assertIsNone(panel)
        self.assertIsNone(point)

    def test_preview_uses_viewport_paint_space_not_client_hit_test_space(self):
        helper = object.__new__(DragPreviewHelper)
        helper.active = True
        helper._primary_viewport = True
        helper._group = Mock()
        helper._content_size = (160.0, 60.0)
        helper._runtime = None
        helper._paint_bounds = Mock(return_value=None)
        with patch.object(QCursor, 'viewportPos', return_value=(120, 240)) as viewport, \
             patch.object(QCursor, 'paintPos', return_value=(620, 540)) as paint:
            helper.moveToCursor()
        helper._group.setTranslation.assert_called_once_with(
            620.0 + helper.OFFSET_X, 540.0 + helper.OFFSET_Y)
        paint.assert_called_once_with()
        viewport.assert_not_called()

    def test_preview_flips_near_right_edge_and_stays_adjacent_to_cursor(self):
        helper = object.__new__(DragPreviewHelper)
        helper.active = True
        helper._primary_viewport = True
        helper._group = Mock()
        helper._content_size = (160.0, 60.0)
        helper._runtime = None
        helper._paint_bounds = Mock(return_value=(500.0, 100.0, 1400.0, 800.0))
        helper.moveToCursor(pointer=(1380.0, 300.0))
        helper._group.setTranslation.assert_called_once_with(
            1380.0 - 160.0 - helper.OFFSET_X, 300.0 + helper.OFFSET_Y)

    def test_preview_flips_near_bottom_edge_and_stays_adjacent_to_cursor(self):
        helper = object.__new__(DragPreviewHelper)
        helper.active = True
        helper._primary_viewport = True
        helper._group = Mock()
        helper._content_size = (160.0, 60.0)
        helper._runtime = None
        helper._paint_bounds = Mock(return_value=(500.0, 100.0, 1400.0, 800.0))
        helper.moveToCursor(pointer=(900.0, 790.0))
        helper._group.setTranslation.assert_called_once_with(
            900.0 + helper.OFFSET_X, 790.0 - 60.0 - helper.OFFSET_Y)


if __name__ == '__main__':
    unittest.main(verbosity=2)
