"""Plot Digitizer Edit-mode selection keyboard behavior."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.core import Qt
from DearUIQt.widgets import QApplication, QRetainedItem
from DearUIQt.modelview.base import _QtAbstractItemView
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog


class EditSelectionShortcutTests(unittest.TestCase):
    def test_history_keys_route_once_and_are_consumed(self):
        dialog = self.make_dialog()
        dialog._trigger_history_command = Mock()
        for key, modifiers, expected in (
                (Qt.Key_Z, Qt.ControlModifier, 'undo'),
                (Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier, 'redo'),
                (Qt.Key_Y, Qt.ControlModifier, 'redo')):
            with self.subTest(key=key, modifiers=modifiers):
                dialog._trigger_history_command.reset_mock()
                self.assertTrue(dialog._edit_key(None, key=key, modifiers=modifiers))
                dialog._trigger_history_command.assert_called_once_with(expected)

    def test_history_does_not_steal_editor_modal_or_foreign_window_keys(self):
        dialog = self.make_dialog()
        dialog._trigger_history_command = Mock()
        dialog._accepts_edit_shortcut = lambda **_kwargs: False
        dialog._edit_key(None, key=Qt.Key_Z, modifiers=Qt.ControlModifier)
        dialog._trigger_history_command.assert_not_called()
        dialog._accepts_edit_shortcut = lambda **_kwargs: True
        dialog._edit_key(None, key=Qt.Key_Z, modifiers=Qt.ControlModifier | Qt.AltModifier)
        dialog._trigger_history_command.assert_not_called()

    def test_undo_cancels_both_background_jobs_before_restoring_state(self):
        dialog = self.make_dialog()
        dialog._tick_calibration_runner = Mock(busy=True)
        dialog._smart_runner = Mock(busy=True)
        dialog._finish_progress = Mock()
        dialog._refresh_dataset_controls = Mock()
        dialog._cancel_pick = Mock()
        dialog.engine = Mock(can_undo=True, _undo_stack=[('Delete points', {})])
        def restore():
            dialog._tick_calibration_runner.cancel.assert_called_once_with()
            dialog._smart_runner.cancel.assert_called_once_with()
            return True
        dialog.engine.undo.side_effect = restore
        dialog._undo()
        self.assertIsNone(dialog._region_alignment_preview)
        self.assertEqual(2, dialog._finish_progress.call_count)
        dialog.engine.undo.assert_called_once_with()

    def make_dialog(self, selected=True):
        dialog = PlotDigitizerDialog.__new__(PlotDigitizerDialog)
        dialog._edit_enabled = True
        dialog._active_tool = 'extract'
        dialog._pick_mode = None
        dialog._native_delete_snapshot = Mock(return_value=None)
        dialog._selected_point = ('manual', 0) if selected else None
        keys = {'manual:0'} if selected else set()
        dialog.result_grid = SimpleNamespace(
            selectedKeys=lambda: set(keys),
            hasFocus=lambda: False,
        )
        dialog._accepts_edit_shortcut = lambda **_kwargs: True
        dialog._clear_point_selection = Mock()
        dialog._refresh_point_editor = Mock()
        dialog._redraw = Mock()
        dialog._set_status = Mock()
        dialog._delete_points = Mock()
        dialog._mouse_in_canvas = lambda: False
        return dialog

    def test_escape_clears_selection_without_disabling_edit_mode(self):
        dialog = self.make_dialog(selected=True)
        handled = dialog._edit_key(None, key=Qt.Key_Escape, modifiers=0)
        self.assertTrue(handled)
        dialog._clear_point_selection.assert_called_once_with()
        dialog._refresh_point_editor.assert_called_once_with()
        dialog._redraw.assert_called_once_with()
        self.assertTrue(dialog._edit_enabled)

    def test_delete_removes_selected_points_in_edit_mode(self):
        dialog = self.make_dialog(selected=True)
        handled = dialog._edit_key(None, key=Qt.Key_Delete, modifiers=0)
        self.assertTrue(handled)
        dialog._delete_points.assert_called_once_with()

    def test_dialog_escape_path_clears_selection_before_leaving_edit_mode(self):
        dialog = self.make_dialog(selected=True)
        dialog._point_press = None
        dialog._pick_mode = None
        dialog._edit_mode_toggled = Mock()
        dialog._cancel_pick = Mock()
        dialog.destroy = Mock()
        dialog._close_from_escape()
        dialog._clear_point_selection.assert_called_once_with()
        dialog._edit_mode_toggled.assert_not_called()
        dialog.destroy.assert_not_called()

    def test_delete_is_ignored_without_selection(self):
        dialog = self.make_dialog(selected=False)
        handled = dialog._edit_key(None, key=Qt.Key_Delete, modifiers=0)
        self.assertIsNone(handled)
        dialog._delete_points.assert_not_called()

    def test_canvas_focus_uses_logical_focus_when_drawlist_cannot_take_native_focus(self):
        dialog = self.make_dialog(selected=True)
        canvas = Mock()
        canvas.setFocus.return_value = False
        dialog._canvas_widget = canvas
        application = Mock()
        with patch.object(QApplication, 'instance', return_value=application):
            focused = dialog._focus_canvas_keyboard()
        self.assertTrue(focused)
        application.setFocusObject.assert_called_once_with(canvas)

    def test_stale_native_editor_focus_does_not_block_delete_after_canvas_focus(self):
        dialog = self.make_dialog(selected=True)
        canvas = Mock()
        dialog._canvas_widget = canvas
        dialog._visible_state = True
        dialog.isVisible = lambda: True
        dialog.winfo_exists = lambda: True
        dialog._file_dialog = None
        dialog._settings_dialog = None
        dialog.dataset_menu = None
        dialog.enter_editors = {'stale-input'}
        dialog.view = SimpleNamespace(_find_main_viewport_hwnd=lambda: 0)
        dialog._native_window_backend = None
        application = Mock()
        application.focusObject.return_value = canvas
        application.activeModalWidget.return_value = None
        application.activePopupWidget.return_value = None
        stale_focused_item = Mock()
        stale_focused_item.itemType.return_value = 'mvAppItemType::mvInputText'
        with patch.object(QApplication, 'instance', return_value=application), \
             patch('DearUIQt.input_gate.native_modal_input_active', return_value=False), \
             patch.object(QRetainedItem, 'focusedItem', return_value=stale_focused_item):
            self.assertTrue(PlotDigitizerDialog._accepts_edit_shortcut(dialog))

    def test_canvas_logical_focus_survives_process_host_hwnd_mismatch(self):
        dialog = self.make_dialog(selected=True)
        canvas = Mock()
        dialog._canvas_widget = canvas
        dialog._visible_state = True
        dialog.isVisible = lambda: True
        dialog.winfo_exists = lambda: True
        dialog._file_dialog = None
        dialog._settings_dialog = None
        dialog.dataset_menu = None
        dialog.enter_editors = set()
        dialog.view = SimpleNamespace(_find_main_viewport_hwnd=lambda: 100)
        dialog._native_window_backend = None
        application = Mock()
        application.focusObject.return_value = canvas
        application.activeModalWidget.return_value = None
        application.activePopupWidget.return_value = None
        with patch.object(QApplication, 'instance', return_value=application), \
             patch('DearUIQt.input_gate.native_modal_input_active', return_value=False), \
             patch('WinUx.ui.native.dialog_focus.foreground_hwnd', return_value=200), \
             patch('WinUx.ui.native.dialog_focus.window_state', return_value=(True, True, True)), \
             patch.object(QRetainedItem, 'focusedItem', return_value=None):
            self.assertTrue(PlotDigitizerDialog._accepts_edit_shortcut(dialog))

    def test_delete_removes_calibration_selection_not_curve_points(self):
        dialog = self.make_dialog()
        dialog._active_tool = 'axes'
        dialog._selected_calibration_point = ('y', 1)
        dialog._remove_calibration_point = Mock()
        self.assertTrue(dialog._edit_key(None, key=Qt.Key_Delete, modifiers=0))
        dialog._remove_calibration_point.assert_called_once_with()
        dialog._delete_points.assert_not_called()

    def test_axes_delete_without_calibration_selection_does_not_delete_curve(self):
        dialog = self.make_dialog()
        dialog._active_tool = 'axes'
        dialog._selected_calibration_point = None
        dialog._edit_key(None, key=Qt.Key_Delete, modifiers=0)
        dialog._delete_points.assert_not_called()

    def test_data_table_delete_works_without_canvas_edit_mode(self):
        dialog = self.make_dialog()
        dialog._active_tool = 'data'
        dialog._edit_enabled = False
        dialog.result_grid.hasFocus = lambda: True
        self.assertTrue(dialog._edit_key(None, key=Qt.Key_Delete, modifiers=0))
        dialog._delete_points.assert_called_once_with()

    def test_pending_calibration_pick_is_not_deleted(self):
        dialog = self.make_dialog()
        dialog._active_tool = 'axes'
        dialog._selected_calibration_point = ('x', 1)
        dialog._pick_mode = 'calibration_x'
        dialog._remove_calibration_point = Mock()
        dialog._edit_key(None, key=Qt.Key_Delete, modifiers=0)
        dialog._remove_calibration_point.assert_not_called()

    def test_native_delete_is_consumed_once_while_held(self):
        dialog = self.make_dialog()
        dialog._native_delete_snapshot.return_value = (True, 0, True)
        self.assertTrue(dialog._edit_key(None, key=Qt.Key_Delete, modifiers=0))
        self.assertTrue(dialog._edit_key(None, key=Qt.Key_Delete, modifiers=0))
        dialog._delete_points.assert_called_once_with()
        dialog._native_delete_snapshot.return_value = (False, 0, True)
        dialog._poll_delete_key()
        dialog._native_delete_snapshot.return_value = (True, 0, True)
        dialog._edit_key(None, key=Qt.Key_Delete, modifiers=0)
        self.assertEqual(2, dialog._delete_points.call_count)

    def test_native_poll_uses_edges_not_renderer_visibility_callbacks(self):
        dialog = self.make_dialog()
        dialog._native_delete_snapshot.return_value = (True, 0, True)
        dialog._edit_key = Mock()
        dialog._poll_delete_key()
        dialog._poll_delete_key()
        dialog._edit_key.assert_called_once_with(None, key=Qt.Key_Delete, modifiers=0)

    def test_native_poll_does_not_capture_background_delete(self):
        dialog = self.make_dialog()
        dialog._native_delete_snapshot.return_value = (True, 0, False)
        dialog._edit_key = Mock()
        dialog._poll_delete_key()
        dialog._edit_key.assert_not_called()

    def test_native_snapshot_checks_window_ownership_and_modifiers(self):
        dialog = self.make_dialog()
        dialog.view = SimpleNamespace(_find_main_viewport_hwnd=lambda: 100)
        dialog._native_window_backend = None
        user32 = SimpleNamespace(GetAsyncKeyState=lambda key: 0x8000 if key in (0x2E, 0x11) else 0)
        with patch('ctypes.windll.user32', user32), \
                patch('WinUx.ui.native.dialog_focus.foreground_hwnd', return_value=100), \
                patch('WinUx.ui.native.dialog_focus.window_state', return_value=(True, True, True)):
            self.assertEqual((True, Qt.ControlModifier, True), PlotDigitizerDialog._native_delete_snapshot(dialog))
        with patch('ctypes.windll.user32', user32), \
                patch('WinUx.ui.native.dialog_focus.foreground_hwnd', return_value=200), \
                patch('WinUx.ui.native.dialog_focus.window_state', return_value=(True, True, True)):
            self.assertFalse(PlotDigitizerDialog._native_delete_snapshot(dialog)[2])

    def test_idle_native_poll_does_not_resolve_window_handles(self):
        dialog = self.make_dialog()
        dialog._native_window_backend = SimpleNamespace(winId=Mock(side_effect=AssertionError('unnecessary HWND query')))
        with patch('ctypes.windll.user32', SimpleNamespace(GetAsyncKeyState=lambda key: 0)):
            self.assertEqual((False, 0, False), PlotDigitizerDialog._native_delete_snapshot(dialog))

    def test_point_table_focus_updates_application_keyboard_receiver(self):
        view = object.__new__(_QtAbstractItemView)
        view._set_view_focus = Mock()
        view._focus_current = Mock()
        with patch('DearUIQt.widgets.widget.QWidget.setFocus', return_value=True) as widget_focus:
            self.assertIs(view, _QtAbstractItemView.setFocus(view))
        widget_focus.assert_called_once_with()
        view._focus_current.assert_called_once_with()

    def test_modal_dialog_blocks_document_delete_even_with_canvas_focus(self):
        dialog = self.make_dialog()
        dialog.winfo_exists = lambda: True
        dialog._visible_state = True
        dialog.isVisible = lambda: True
        app = SimpleNamespace(activeModalWidget=lambda: object(), activePopupWidget=lambda: None)
        with patch.object(QApplication, 'instance', return_value=app), \
                patch('DearUIQt.input_gate.native_modal_input_active', return_value=False):
            self.assertFalse(PlotDigitizerDialog._accepts_edit_shortcut(dialog))

    def test_canvas_tick_polls_delete_as_renderer_fallback(self):
        dialog = self.make_dialog(selected=True)
        dialog._layout_canvas = Mock()
        dialog._middle_drag = False
        dialog._mouse_move = Mock()
        dialog._sync_canvas_cursor = Mock()
        dialog.view = SimpleNamespace(after_render=lambda *args: None)
        dialog._edit_key = Mock(return_value=True)
        with patch('WinUx.plotdigitizer.ui.dialog._renderer_backend', return_value=SimpleNamespace()), \
             patch('WinUx.plotdigitizer.ui.dialog.QKeyboard.isKeyPressed', return_value=True), \
             patch('WinUx.plotdigitizer.ui.dialog.QKeyboard.modifiers', return_value=0):
            dialog._canvas_pointer_tick()
        dialog._edit_key.assert_called_once_with(None, key=Qt.Key_Delete, modifiers=0)


if __name__ == '__main__':
    unittest.main()
