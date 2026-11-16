import unittest
from types import SimpleNamespace
from unittest.mock import patch

from DearUIQt.core import QPoint
from WinUx.ui.components.explorer.hit_testing import ExplorerHitTestingMixin
from WinUx.ui.components.explorer.pointer_dispatch import ExplorerPointerDispatchMixin


class _FakeRetained:
    def __init__(self, tag):
        self.tag = tag
        self.backend = object()
    def exists(self): return True
    def isVisible(self): return True
    def verticalScrollMaximum(self): return 0.0
    def horizontalScrollMaximum(self): return 0.0
    def verticalScrollValue(self): return 0.0
    def horizontalScrollValue(self): return 0.0


class _Host(ExplorerPointerDispatchMixin, ExplorerHitTestingMixin):
    ROW_HEIGHT = 20
    HEADER_HEIGHT = 26
    SCROLLBAR_HIT_SIZE = 14
    MIN_COLUMN_WIDTH = 20

    def __init__(self):
        self.window_tag = 'pane'
        self.header_canvas = 'header'
        self.body_window = 'body'
        self.body_canvas = 'canvas'
        self.pinned_canvas = 'pinned'
        self._pinned_item = None
        self.items = list(range(20))
        self._column_widths = {'name': 300}

    def _row_content_width(self): return 300.0
    def _visible_columns(self): return [{'key': 'name'}]
    def _safe_item_rect(self, tag):
        # Deliberately wrong/stale app coordinates. Physical hit testing must
        # never use these to resolve the selected row.
        return (0.0, 0.0, 300.0, 400.0)


_SCREEN_RECTS = {
    'pane': (500.0, 250.0, 820.0, 560.0),
    'header': (500.0, 250.0, 820.0, 276.0),
    'body': (500.0, 276.0, 820.0, 560.0),
    # canvas is scrolled 40 px upward: screen y=336 -> content y=100 -> row 5
    'canvas': (500.0, 236.0, 800.0, 636.0),
    'pinned': (500.0, 276.0, 820.0, 296.0),
}


class PhysicalCursorHitTests(unittest.TestCase):
    def setUp(self):
        self.host = _Host()
        self.retained = patch(
            'WinUx.ui.components.explorer.hit_testing.QRetainedItem', _FakeRetained)
        self.screen_rect = patch(
            'WinUx.ui.components.explorer.hit_testing.item_screen_rect',
            side_effect=lambda backend, tag: _SCREEN_RECTS.get(tag))
        self.retained.start(); self.addCleanup(self.retained.stop)
        self.screen_rect.start(); self.addCleanup(self.screen_rect.stop)

    def test_row_uses_real_screen_cursor_not_stale_app_position(self):
        # Stale app/renderer coordinate would resolve near row 0/1. The actual
        # physical cursor is over content row 5.
        self.host._pointer_position = lambda: (20.0, 20.0)
        with patch('WinUx.ui.components.explorer.hit_testing.QCursor.screenPos',
                   return_value=QPoint(550, 336)):
            self.assertEqual(self.host._row_at_mouse(), 5)

    def test_blank_physical_body_does_not_fall_back_to_fake_app_row(self):
        self.host._pointer_position = lambda: (20.0, 20.0)
        # x=810 is in the visible body but beyond actual 300px row content
        # because canvas starts at 500; it must remain blank, not select row 1.
        with patch('WinUx.ui.components.explorer.hit_testing.QCursor.screenPos',
                   return_value=QPoint(810, 336)):
            self.assertIsNone(self.host._row_at_mouse())

    def test_qapplication_target_hit_test_uses_physical_screen_position(self):
        # Supplied QApplication position is intentionally nonsense. The physical
        # cursor is inside the pane, so this view must own the event.
        self.host._physical_pointer_position = lambda: (550.0, 336.0)
        fake_dpg = SimpleNamespace(
            does_item_exist=lambda tag: True,
            is_item_shown=lambda tag: True,
            get_item_parent=lambda tag: None,
            is_item_hovered=lambda tag: False,
        )
        with patch('WinUx.ui.components.explorer.pointer_dispatch.dpg', fake_dpg):
            self.assertTrue(self.host._qt_pointer_hit_test((99999.0, 99999.0)))


if __name__ == '__main__':
    unittest.main()
