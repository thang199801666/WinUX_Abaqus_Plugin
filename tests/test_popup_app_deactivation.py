"""Dropdowns must not remain above another application's windows."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from DearUIQt.backends.native_windows import NativeWindowBackend
from DearUIQt.gui import popup_tracking


class PopupDeactivationTests(unittest.TestCase):
    def test_foreground_requires_a_known_foreign_process(self):
        native = NativeWindowBackend(object())
        user32 = Mock()
        with patch.object(NativeWindowBackend, 'isEnabled', return_value=True), \
                patch('DearUIQt.backends.native_windows.ctypes.windll', create=True) as windll, \
                patch('DearUIQt.backends.native_windows._window_process_id') as pid:
            windll.user32 = user32
            user32.GetForegroundWindow.return_value = 123
            for process_id, expected in ((os.getpid(), False), (0, False),
                                         (os.getpid() + 1, True)):
                pid.return_value = process_id
                self.assertEqual(native.hasForeignForeground(), expected)
            user32.GetForegroundWindow.return_value = 0
            pid.reset_mock()
            self.assertFalse(native.hasForeignForeground())
            pid.assert_not_called()

    def test_disabled_native_backend_does_not_query_foreground(self):
        with patch.object(NativeWindowBackend, 'isEnabled', return_value=False):
            self.assertFalse(NativeWindowBackend(object()).hasForeignForeground())

    def test_external_activation_closes_root_and_submenu_without_refresh(self):
        backend = object()
        root = Mock(backend=backend, _parent_menu=None)
        child = Mock(backend=backend, _parent_menu=root)
        def hide_root():
            popup_tracking.untrack_popup(root)
            child.hide()
            popup_tracking.untrack_popup(child)
        root.hide.side_effect = hide_root
        popup_tracking.track_popup(root)
        popup_tracking.track_popup(child)
        try:
            with patch.object(NativeWindowBackend, 'hasForeignForeground', return_value=True):
                popup_tracking.update_popup_positions(backend)
                popup_tracking.update_popup_positions(backend)
            root.hide.assert_called_once_with()
            child.hide.assert_called_once_with()
            root._refresh_popup_position.assert_not_called()
            child._refresh_popup_position.assert_not_called()
        finally:
            popup_tracking.clear_popup_tracking(backend)

    def test_same_process_activation_keeps_menu_open_and_tracking(self):
        backend = object()
        menu = Mock(backend=backend, _parent_menu=None)
        popup_tracking.track_popup(menu)
        try:
            with patch.object(NativeWindowBackend, 'hasForeignForeground', return_value=False):
                popup_tracking.update_popup_positions(backend)
            menu.hide.assert_not_called()
            menu._refresh_popup_position.assert_called_once_with()
        finally:
            popup_tracking.clear_popup_tracking(backend)


if __name__ == '__main__':
    unittest.main()
