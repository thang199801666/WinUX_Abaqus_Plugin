"""Exercise production editor transitions without importing native Dear PyGui."""
import ast
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from WinUx.runtime.rename_result import RenameResult


def methods(path, names, namespace):
    namespace.update(__name__='WinUx.components._rename_test', __package__='WinUx.components')
    tree = ast.parse(path.read_text(encoding='utf-8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and any(isinstance(member, ast.FunctionDef) and member.name in names for member in node.body))
    cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in names]
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[cls.name]


class AsyncEditorTests(unittest.TestCase):
    def fixture(self):
        root = Path(__file__).resolve().parents[1]
        cls = methods(root / 'WinUx/components/explorer_rename.py',
            {'commit_inline_rename', '_finish_inline_rename_ui', '_rename_completed', 'cancel_inline_rename'},
            {'os': os, 'RenameResult': RenameResult})
        editor = cls()
        result = RenameResult()
        editor._rename_active, editor._rename_index = True, 0
        editor.items = [SimpleNamespace(path='/a', name='a')]
        editor.on_rename_commit = Mock(return_value=result)
        editor._rename_textbox = SimpleNamespace(close=Mock())
        editor.refocus_inline_rename = Mock()
        editor.on_selection_change = Mock()
        editor.get_selected = Mock(return_value=editor.items)
        return editor, result

    def test_pending_editor_remains_open_and_duplicate_commits_do_not_dispatch(self):
        editor, result = self.fixture()
        self.assertTrue(editor.commit_inline_rename('b'))
        self.assertFalse(editor.commit_inline_rename('c'))
        editor.on_rename_commit.assert_called_once()
        editor._rename_textbox.close.assert_not_called()
        result.complete(True)
        editor._rename_textbox.close.assert_called_once_with()
        editor.on_selection_change.assert_called_once_with(editor.items)

    def test_failure_refocuses_and_allows_retry(self):
        editor, result = self.fixture()
        editor.commit_inline_rename('b')
        result.complete(False)
        editor.refocus_inline_rename.assert_called_once_with()
        editor._rename_textbox.close.assert_not_called()
        editor.on_rename_commit.return_value = RenameResult()
        self.assertTrue(editor.commit_inline_rename('retry'))
        self.assertEqual(editor.on_rename_commit.call_count, 2)

    def test_old_completion_cannot_close_new_editor(self):
        editor, result = self.fixture()
        editor.commit_inline_rename('b')
        editor.cancel_inline_rename()
        editor._rename_active, editor._rename_index = True, 0
        current = RenameResult()
        editor.on_rename_commit.return_value = current
        editor.commit_inline_rename('c')
        editor._rename_textbox.close.reset_mock()
        result.complete(True)
        editor._rename_textbox.close.assert_not_called()
        self.assertIs(editor._rename_pending, current)
        current.complete(True)
        editor._rename_textbox.close.assert_called_once_with()

    def test_completion_is_once_and_late_subscriber_gets_result(self):
        result = RenameResult()
        early, late = Mock(), Mock()
        result.then(early)
        result.complete(True)
        result.complete(False)
        result.then(late)
        early.assert_called_once_with(True)
        late.assert_called_once_with(True)

    def test_panel_pending_callback_survives_failure_and_cannot_clear_new_callback(self):
        root = Path(__file__).resolve().parents[1]
        cls = methods(root / 'WinUx/components/file_panel.py',
            {'_rename_commit', '_rename_callback_completed'},
            {'ListViewItem': object, 'Any': object})
        panel = cls.__new__(cls)
        failed = RenameResult()
        callback = Mock(return_value=failed)
        panel._rename_commit_callback = callback
        self.assertIs(panel._rename_commit(None, 'name'), failed)
        self.assertIs(panel._rename_commit_callback, callback)
        failed.complete(False)
        self.assertIs(panel._rename_commit_callback, callback)
        pending = RenameResult()
        callback.return_value = pending
        panel._rename_commit(None, 'name')
        replacement = Mock()
        panel._rename_commit_callback = replacement
        pending.complete(True)
        self.assertIs(panel._rename_commit_callback, replacement)

    def test_panel_success_releases_original_callback(self):
        root = Path(__file__).resolve().parents[1]
        cls = methods(root / 'WinUx/components/file_panel.py',
            {'_rename_commit', '_rename_callback_completed'},
            {'ListViewItem': object, 'Any': object})
        panel = cls.__new__(cls)
        result = RenameResult()
        panel._rename_commit_callback = Mock(return_value=result)
        panel._rename_commit(None, 'name')
        result.complete(True)
        self.assertIsNone(panel._rename_commit_callback)


if __name__ == '__main__':
    unittest.main()
