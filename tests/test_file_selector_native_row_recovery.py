"""Native chooser press recovery: edges, ownership and duplicate suppression."""
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from DearUIQt.core import QPoint, QRect, Qt, QEvent, QMouseEvent
from WinUx.dialogs.local_folder_form import FolderListView, LocalPathDialog
from DearUIQt.dialogs.qt_dialog import QtDialog


class NativeRowRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.user32 = SimpleNamespace(GetAsyncKeyState=Mock(return_value=0x8000),
                                      GetForegroundWindow=Mock(return_value=11),
                                      IsWindowEnabled=Mock(return_value=True))
        self.dialog = SimpleNamespace(
            winfo_exists=Mock(return_value=True), isVisible=Mock(return_value=True),
            _finished=False, _native_row_left_down=False, _native_row_last_up=10,
            _native_row_press_recovered=False,
            _native_window_backend=SimpleNamespace(winId=Mock(return_value=11)),
            tag='chooser', folder_region='folder',
            listbox=SimpleNamespace(_qt_bridge_click=None, backend=Mock()),
            native_pointer_press=Mock(return_value=True))
        self.dialog._native_row_pointer_position = lambda: LocalPathDialog._native_row_pointer_position(self.dialog)
        self.rect = SimpleNamespace(globalGeometry=Mock(return_value=QRect(100, 100, 200, 200)))
        self.patches = [
            patch('ctypes.windll.user32', self.user32),
            patch('WinUx.dialogs.local_folder_form.QRetainedItem', return_value=self.rect),
            patch('WinUx.dialogs.local_folder_form.QCursor.screenPos', return_value=QPoint(540, 650)),
            patch('DearUIQt.gui.placement.item_screen_rect', return_value=(500, 600, 700, 800)),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def recover(self):
        LocalPathDialog._recover_native_row_press(self.dialog)

    def test_recovers_once_and_maps_desktop_to_retained_coordinates(self):
        self.recover()
        self.recover()  # Holding the button cannot become a double-click.
        self.dialog.native_pointer_press.assert_called_once_with((140, 150))
        self.assertTrue(self.dialog._native_row_press_recovered)

    def test_normal_qt_route_wins(self):
        self.dialog.listbox._qt_bridge_click = ('second.png', 8, 11)
        self.recover()
        self.dialog.native_pointer_press.assert_not_called()

    def test_background_and_disabled_windows_never_recover(self):
        self.user32.GetForegroundWindow.return_value = 12
        self.recover()
        self.dialog.native_pointer_press.assert_not_called()
        self.dialog._native_row_left_down = False
        self.user32.GetForegroundWindow.return_value = 11
        self.user32.IsWindowEnabled.return_value = False
        self.recover()
        self.dialog.native_pointer_press.assert_not_called()

    def test_does_not_recover_outside_file_list_or_after_close(self):
        self.rect.globalGeometry.side_effect = [QRect(100, 100, 200, 200), QRect(300, 300, 100, 100)]
        self.recover()
        self.dialog.native_pointer_press.assert_not_called()
        self.dialog._native_row_left_down = False
        self.dialog._finished = True
        self.recover()
        self.dialog.native_pointer_press.assert_not_called()

    def test_fresh_qt_press_is_not_suppressed_by_previous_recovery(self):
        self.dialog._native_row_press_recovered = True
        self.dialog._view_mode_pointer_hit = Mock(return_value=False)
        self.dialog._selector_pointer_hit = Mock(return_value=True)
        self.dialog.listbox.current = None
        self.dialog.listbox.selected = set()
        app = SimpleNamespace(activeModalWidget=lambda: self.dialog, frameCount=lambda: 10)
        event = QMouseEvent(QEvent.MouseButtonPress, (150, 150),
                            button=Qt.LeftButton, buttons=Qt.LeftButton)
        with patch('WinUx.dialogs.local_folder_form.QApplication.instance', return_value=app):
            self.assertTrue(LocalPathDialog.event(self.dialog, event))
        self.dialog._selector_pointer_hit.assert_called_once()

    def test_delayed_qt_press_after_recovery_is_consumed(self):
        self.dialog._native_row_press_recovered = True
        self.dialog._native_row_left_down = True
        self.dialog._view_mode_pointer_hit = Mock(return_value=False)
        self.dialog._selector_pointer_hit = Mock(return_value=True)
        app = SimpleNamespace(activeModalWidget=lambda: self.dialog)
        event = QMouseEvent(QEvent.MouseButtonPress, (150, 150),
                            button=Qt.LeftButton, buttons=Qt.LeftButton)
        with patch('WinUx.dialogs.local_folder_form.QApplication.instance', return_value=app):
            self.assertTrue(LocalPathDialog.event(self.dialog, event))
        self.dialog._selector_pointer_hit.assert_not_called()

    def test_stale_renderer_row_position_uses_owned_physical_cursor(self):
        self.dialog._view_mode_pointer_hit = Mock(return_value=False)
        self.dialog._selector_pointer_hit = Mock(return_value=True)
        self.dialog.listbox.current = None
        self.dialog.listbox.selected = set()
        app = SimpleNamespace(activeModalWidget=lambda: self.dialog, frameCount=lambda: 10)
        # The renderer still reports the first row; the real click is elsewhere.
        event = QMouseEvent(QEvent.MouseButtonPress, (110, 110),
                            button=Qt.LeftButton, buttons=Qt.LeftButton)
        with patch('WinUx.dialogs.local_folder_form.QApplication.instance', return_value=app):
            self.assertTrue(LocalPathDialog.event(self.dialog, event))
        self.dialog._selector_pointer_hit.assert_called_once_with((140, 150))

    def test_first_row_press_cancels_deferred_initial_focus(self):
        self.dialog._view_mode_pointer_hit = Mock(return_value=False)
        self.dialog._selector_pointer_hit = Mock(return_value=True)
        self.dialog.listbox.current = 'second.png'
        self.dialog.listbox.selected = {'second.png'}
        self.dialog._initial_pointer_activity = False
        self.dialog._focus_initial = Mock()
        app = SimpleNamespace(activeModalWidget=lambda: self.dialog, frameCount=lambda: 10)
        event = QMouseEvent(QEvent.MouseButtonPress, (150, 150),
                            button=Qt.LeftButton, buttons=Qt.LeftButton)
        with patch('WinUx.dialogs.local_folder_form.QApplication.instance', return_value=app):
            self.assertTrue(LocalPathDialog.event(self.dialog, event))
        self.assertFalse(QtDialog._apply_initial_focus_if_idle(self.dialog))
        self.dialog._focus_initial.assert_not_called()

    def test_native_recovery_also_cancels_deferred_initial_focus(self):
        self.dialog._selector_pointer_hit = Mock(return_value=True)
        self.dialog._initial_pointer_activity = False
        self.dialog._focus_initial = Mock()
        app = SimpleNamespace(activeModalWidget=lambda: self.dialog)
        with patch('WinUx.dialogs.local_folder_form.QApplication.instance', return_value=app), \
                patch('DearUIQt.input_gate.native_background_input_blocked', return_value=False), \
                patch('DearUIQt.input_gate.native_modal_input_active', return_value=False):
            self.assertTrue(LocalPathDialog.native_pointer_press(self.dialog, (140, 150)))
        self.assertFalse(QtDialog._apply_initial_focus_if_idle(self.dialog))
        self.dialog._focus_initial.assert_not_called()

    def test_wheel_cancels_deferred_focus_and_scroll_restore(self):
        self.dialog._initial_pointer_activity = False
        self.dialog._pointer_interaction_serial = 8
        self.dialog._focus_initial = Mock()
        listing = SimpleNamespace(
            _deleted=False, backend=Mock(), window=lambda: self.dialog,
            globalGeometry=lambda **kw: QRect(100, 100, 200, 200),
            _cancel_scroll_restore=Mock(), _last_click_key='first.png')
        with patch('WinUx.dialogs.local_folder_form.QCursor.pos', return_value=QPoint(150, 150)):
            FolderListView._row_pointer_wheel(listing)
        self.assertFalse(QtDialog._apply_initial_focus_if_idle(self.dialog))
        self.dialog._focus_initial.assert_not_called()
        self.assertEqual(self.dialog._pointer_interaction_serial, 9)
        listing._cancel_scroll_restore.assert_called_once()


if __name__ == '__main__':
    unittest.main()
