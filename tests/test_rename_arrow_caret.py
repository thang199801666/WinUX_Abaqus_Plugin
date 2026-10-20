"""Explorer rename: Right collapses the basename selection before its dot."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from WinUx.ui.components.native_rename import NativeRenameEditor, basename_select_end
from WinUx.ui.components.explorer_rename_textbox import ExplorerRenameTextBox


class RenameArrowCaretTests(unittest.TestCase):
    def editor(self, text="Test-17-0285.inp"):
        editor = NativeRenameEditor()
        end = basename_select_end(text)
        editor.get_selection = Mock(return_value=(0, end))
        editor.set_selection = Mock(return_value=True)
        return editor, end

    def test_right_collapses_before_extension(self):
        editor, end = self.editor()
        self.assertTrue(editor.collapse_selection_right())
        editor.set_selection.assert_called_once_with(end, end)

    def test_second_right_uses_native_caret_navigation(self):
        editor, end = self.editor()
        editor.get_selection.return_value = (end, end)
        self.assertFalse(editor.collapse_selection_right())
        editor.set_selection.assert_not_called()

    def test_modified_arrows_keep_native_selection_and_word_navigation(self):
        for modifier in ("shift", "control", "alt"):
            with self.subTest(modifier=modifier):
                editor, _ = self.editor()
                self.assertFalse(editor.collapse_selection_right(**{modifier: True}))
                editor.set_selection.assert_not_called()

    def test_unicode_uses_utf16_caret_position(self):
        editor, end = self.editor("a\U0001f600.inp")
        self.assertEqual(end, 3)
        self.assertTrue(editor.collapse_selection_right())
        editor.set_selection.assert_called_once_with(3, 3)

    def test_initial_focus_repair_does_not_reselect_after_arrow(self):
        editor, _ = self.editor()
        editor.collapse_selection_right()
        editor.set_selection.reset_mock()
        textbox = SimpleNamespace(_native_reselect_pending=True)
        ExplorerRenameTextBox._stabilize_native_editor(textbox, editor)
        self.assertFalse(textbox._native_reselect_pending)
        editor.set_selection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
