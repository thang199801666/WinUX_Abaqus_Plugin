"""Hidden Explorer surfaces must not intercept file-list input."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_winux
run_winux._configure_bundled_dependencies(str(Path(__file__).resolve().parents[1]))
from WinUx.ui.components.explorer_pointer_dispatch import ExplorerPointerDispatchMixin
from WinUx.ui.components.explorer_hit_testing import ExplorerHitTestingMixin
from DearUIQt.core import QEvent, QMouseEvent, QPoint, Qt


class FileListPointerRoutingTests(unittest.TestCase):
    def test_captured_left_drag_survives_lagging_move_button_snapshot(self):
        listing = SimpleNamespace(
            _qt_pointer_event=None, _mouse_down=True, _pointer_input_owned=True,
            _on_mouse_move=Mock(), _on_left_drag=Mock())
        for buttons in (Qt.NoButton, Qt.RightButton):
            event = QMouseEvent(QEvent.MouseMove, (50, 135), buttons=buttons)
            self.assertTrue(ExplorerPointerDispatchMixin._handle_qt_pointer_event(listing, event))
        self.assertEqual(listing._on_left_drag.call_count, 2)

    def test_canceled_or_unowned_gesture_cannot_be_revived_by_mouse_move(self):
        for down, owned in ((False, True), (True, False), (False, False)):
            listing = SimpleNamespace(
                _qt_pointer_event=None, _mouse_down=down, _pointer_input_owned=owned,
                _on_mouse_move=Mock(), _on_left_drag=Mock())
            event = QMouseEvent(QEvent.MouseMove, (50, 135), buttons=Qt.NoButton)
            ExplorerPointerDispatchMixin._handle_qt_pointer_event(listing, event)
            listing._on_left_drag.assert_not_called()

    def test_parent_row_rejects_stale_native_hover_over_first_file(self):
        listing = SimpleNamespace(
            _pinned_item=object(), pinned_canvas=10, window_tag=20,
            _qt_pointer_event=QMouseEvent(QEvent.MouseButtonPress, (50, 135)),
            _safe_item_rect=lambda tag: (0, 100, 200, 123) if tag == 10 else (0, 70, 200, 300))
        with patch('WinUx.ui.components.explorer_hit_testing.QRetainedItem') as retained, \
                patch('WinUx.ui.components.explorer_hit_testing.QCursor.pos', return_value=QPoint(50, 110)):
            retained.return_value.exists.return_value = True
            retained.return_value.isVisible.return_value = True
            retained.return_value.underMouse.return_value = True
            self.assertFalse(ExplorerHitTestingMixin._mouse_in_pinned_row(listing))

    def test_parent_row_uses_delivered_press_not_later_native_hover(self):
        listing = SimpleNamespace(
            _pinned_item=object(), pinned_canvas=10, window_tag=20,
            _qt_pointer_event=QMouseEvent(QEvent.MouseButtonPress, (50, 110)),
            _safe_item_rect=lambda tag: (0, 100, 200, 123) if tag == 10 else (0, 70, 200, 300))
        with patch('WinUx.ui.components.explorer_hit_testing.QRetainedItem') as retained, \
                patch('WinUx.ui.components.explorer_hit_testing.QCursor.pos', return_value=QPoint(50, 135)):
            retained.return_value.exists.return_value = True
            retained.return_value.isVisible.return_value = True
            retained.return_value.underMouse.return_value = False
            self.assertTrue(ExplorerHitTestingMixin._mouse_in_pinned_row(listing))

    def test_hidden_ancestor_rejects_stale_hover_and_geometry(self):
        view = SimpleNamespace(window_tag=10, _safe_item_rect=Mock(return_value=(0, 0, 200, 200)))
        with patch('WinUx.ui.components.explorer_pointer_dispatch.dpg') as backend:
            backend.does_item_exist.return_value = True
            backend.get_item_parent.side_effect = lambda tag: {10: 20, 20: 30, 30: 0}[tag]
            backend.is_item_shown.side_effect = lambda tag: tag != 20
            backend.is_item_hovered.return_value = True
            self.assertFalse(ExplorerPointerDispatchMixin._qt_pointer_hit_test(view, (20, 20)))
            backend.is_item_hovered.assert_not_called()
            view._safe_item_rect.assert_not_called()
            backend.is_item_shown.return_value = True
            backend.is_item_shown.side_effect = None
            self.assertTrue(ExplorerPointerDispatchMixin._qt_pointer_hit_test(view, (20, 20)))

if __name__ == '__main__':
    unittest.main(verbosity=2)
