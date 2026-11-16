from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_winux
run_winux._configure_bundled_dependencies(str(Path(__file__).resolve().parents[1]))

from DearUIQt.gui import QCursor
from WinUx.ui.components.explorer.hit_testing import ExplorerHitTestingMixin
from WinUx.ui.components.file_panel import FilePanel


class FakeBodyItem:
    def horizontalScrollValue(self): return 0.0
    def verticalScrollValue(self): return 48.0


class HitHost(ExplorerHitTestingMixin):
    ROW_HEIGHT = 24
    SCROLLBAR_HIT_SIZE = 12
    body_window = 'body'
    items = list(range(20))
    def _body_viewport_rect(self):
        # Header/pinned chrome ends at y=130 even though the outer child starts
        # much higher.  This origin may change after resize.
        return (20.0, 130.0, 620.0, 430.0)
    def _mouse_over_body_scrollbar(self, mx=None, my=None, viewport=None):
        return False


class M38DropRowGeometryTests(unittest.TestCase):
    def test_explicit_drop_row_uses_live_body_viewport_origin(self):
        host = HitHost()
        fake = FakeBodyItem()
        with patch('WinUx.ui.components.explorer.hit_testing.QRetainedItem', return_value=fake):
            # y=142 => 12 px into viewport + 48 scroll = row 2.
            self.assertEqual(host.row_at_viewport_point(100, 142), 2)

    def test_row_mapping_tracks_resize_origin_immediately(self):
        host = HitHost()
        fake = FakeBodyItem()
        with patch('WinUx.ui.components.explorer.hit_testing.QRetainedItem', return_value=fake):
            self.assertEqual(host.row_at_viewport_point(100, 142), 2)
            host._body_viewport_rect = lambda: (20.0, 190.0, 820.0, 590.0)
            # Same absolute pointer is now above the body after resize.
            self.assertIsNone(host.row_at_viewport_point(100, 142))
            # A point 12 px into the new viewport resolves to the same row.
            self.assertEqual(host.row_at_viewport_point(100, 202), 2)

    def test_file_panel_delegates_drop_row_to_physical_screen_geometry(self):
        panel = object.__new__(FilePanel)
        panel.listview = SimpleNamespace(
            _pinned_item=None,
            pinned_canvas=None,
            items=list(range(8)),
            row_at_screen_point=lambda x, y: 5,
        )
        pinned, index = panel._drop_row_at_point(333, 222)
        self.assertFalse(pinned)
        self.assertEqual(index, 5)

    def test_mouse_helpers_sample_physical_screen_coordinates(self):
        panel = object.__new__(FilePanel)
        panel.current_path = 'root'
        panel.drop_destination_at = lambda x, y: (x, y)
        with patch.object(QCursor, 'screenPos', return_value=SimpleNamespace(toTuple=lambda: (1321, 756))) as screen, \
             patch.object(QCursor, 'viewportPos', side_effect=AssertionError('viewportPos() must not authorize drops')), \
             patch.object(QCursor, 'pos', side_effect=AssertionError('ambiguous pos() must not be used')):
            self.assertEqual(panel.drop_destination_at_mouse(), (1321, 756))
        screen.assert_called_once_with()


if __name__ == '__main__':
    unittest.main(verbosity=2)
