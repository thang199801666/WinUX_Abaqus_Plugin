"""Retained/native text reconciliation without a GUI context."""
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.widgets.editors import ImGuiLineEdit
from DearUIQt.widgets.widget import QWidget


class EditorValueSyncTests(unittest.TestCase):
    def editor(self, retained, native):
        values = {'value': native}
        backend = SimpleNamespace(set_value=Mock(side_effect=lambda tag, text: values.update(value=text)))
        editor = SimpleNamespace(tag=123, _properties={'value': retained}, backend=backend,
                                 text=lambda: values['value'], textChanged=Mock(),
                                 _modified=True, _editing_dirty=True)
        editor._set_value = lambda text: QWidget._set_value(editor, text)
        return editor

    def test_repeated_set_reconciles_overwritten_native_value(self):
        editor = self.editor('new text', 'old native buffer')
        ImGuiLineEdit._set_text(editor, 'new text')
        editor.backend.set_value.assert_called_once_with(123, 'new text')
        self.assertEqual(editor.text(), 'new text')
        editor.textChanged.emit.assert_not_called()

    def test_unchanged_synchronized_text_is_still_idempotent(self):
        editor = self.editor('same', 'same')
        ImGuiLineEdit._set_text(editor, 'same')
        editor.backend.set_value.assert_not_called()
        editor.textChanged.emit.assert_not_called()

    def test_new_text_updates_native_and_emits_once(self):
        editor = self.editor('old', 'old')
        ImGuiLineEdit._set_text(editor, 'new')
        editor.backend.set_value.assert_called_once_with(123, 'new')
        editor.textChanged.emit.assert_called_once_with('new')
        self.assertFalse(editor._editing_dirty)


if __name__ == '__main__':
    unittest.main(verbosity=2)
