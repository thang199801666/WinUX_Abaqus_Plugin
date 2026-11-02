"""Save in place, Save As and scoped Ctrl+S handling."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt.core import Qt
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog


class DigitizerProjectSaveTests(unittest.TestCase):
    def view(self):
        dialog = PlotDigitizerDialog.__new__(PlotDigitizerDialog)
        dialog._project_path = str(ROOT / 'existing.pdg')
        dialog._file_directory = str(ROOT)
        dialog._file_picker = Mock()
        dialog._capture_project_view = Mock(return_value={'version': 1})
        dialog._set_status = Mock()
        dialog.engine = Mock()
        return dialog

    def test_save_existing_project_does_not_open_picker(self):
        dialog = self.view()
        dialog._choose_save_project()
        dialog._file_picker.assert_not_called()
        dialog.engine.save_project.assert_called_once_with(
            str(ROOT / 'existing.pdg'), view_state={'version': 1})

    def test_unnamed_project_uses_save_as(self):
        dialog = self.view()
        dialog._project_path = None
        dialog._choose_save_project()
        self.assertEqual(dialog._file_picker.call_args.kwargs['default_filename'], 'plot_digitizer.pdg')
        dialog.engine.save_project.assert_not_called()

    def test_save_as_prefills_name_and_does_not_change_path_until_success(self):
        dialog = self.view()
        dialog._choose_save_project_as()
        self.assertEqual(dialog._file_picker.call_args.kwargs['default_filename'], 'existing.pdg')
        self.assertEqual(dialog._project_path, str(ROOT / 'existing.pdg'))
        callback = dialog._file_picker.call_args.kwargs['callback']
        callback(str(ROOT / 'another'))
        self.assertEqual(dialog._project_path, str(ROOT / 'another.pdg'))

    def test_failed_save_does_not_replace_current_path(self):
        dialog = self.view()
        dialog.engine.save_project.side_effect = OSError('denied')
        dialog._save_project(str(ROOT / 'another.pdg'))
        self.assertEqual(dialog._project_path, str(ROOT / 'existing.pdg'))
        self.assertIn('Could not save project', dialog._set_status.call_args.args[0])

    def test_ctrl_s_and_ctrl_shift_s_are_scoped_document_commands(self):
        for shift in (False, True):
            dialog = self.view()
            dialog._accepts_edit_shortcut = Mock(return_value=True)
            dialog._choose_save_project = Mock()
            dialog._choose_save_project_as = Mock()
            modifiers = Qt.ControlModifier | (Qt.ShiftModifier if shift else 0)
            with patch('WinUx.plotdigitizer.ui.dialog._renderer_backend', return_value=Mock()), \
                    patch('WinUx.plotdigitizer.ui.dialog.QKeyboard.modifiers', return_value=modifiers):
                dialog._edit_key(None, key=Qt.Key_S)
            dialog._accepts_edit_shortcut.assert_called_once_with(allow_editor=True)
            expected = dialog._choose_save_project_as if shift else dialog._choose_save_project
            expected.assert_called_once()

    def test_blocked_dialog_cannot_save_through_modal(self):
        dialog = self.view()
        dialog._accepts_edit_shortcut = Mock(return_value=False)
        dialog._choose_save_project = Mock()
        with patch('WinUx.plotdigitizer.ui.dialog._renderer_backend', return_value=Mock()), \
                patch('WinUx.plotdigitizer.ui.dialog.QKeyboard.modifiers', return_value=Qt.ControlModifier):
            dialog._edit_key(None, key=Qt.Key_S)
        dialog._choose_save_project.assert_not_called()

    def test_native_child_shortcuts_use_own_hwnd_not_main_app_hwnd(self):
        dialog = self.view()
        dialog.tag = 'digitizer'
        dialog.winfo_exists = Mock(return_value=True)
        dialog._visible_state = True
        dialog.isVisible = Mock(return_value=True)
        dialog._file_dialog = None
        dialog.view = SimpleNamespace(_find_main_viewport_hwnd=lambda: 100)
        dialog._native_window_backend = SimpleNamespace(winId=lambda tag: 200)
        with patch('DearUIQt.input_gate.native_modal_input_active', return_value=False), \
                patch('WinUx.ui.native.dialog_focus.foreground_hwnd', return_value=200), \
                patch('WinUx.ui.native.dialog_focus.window_state', return_value=(True, True)), \
                patch('WinUx.plotdigitizer.ui.dialog.QRetainedItem.focusedItem', return_value=None):
            self.assertTrue(dialog._accepts_edit_shortcut(allow_editor=True))
