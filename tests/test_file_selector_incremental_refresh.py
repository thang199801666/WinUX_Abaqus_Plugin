"""Incremental selector refresh and keyboard routing regressions."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from DearUIQt.core import Qt
from DearUIQt.modelview.models import QtListItem
from WinUx.dialogs.local_folder_form import FolderListView, LocalPathDialog


class _Cell:
    def __init__(self, value):
        self.value = value
        self.set_calls = []
    def text(self):
        return self.value
    def setText(self, value):
        self.value = value
        self.set_calls.append(value)


class SelectorIncrementalRefreshTests(unittest.TestCase):
    def test_same_key_details_refresh_updates_metadata_in_place(self):
        view = FolderListView.__new__(FolderListView)
        view._details_table = SimpleNamespace(_deleted=False)
        view.items = {'a.txt': 'native-name'}
        view.entry_is_dirs = {'a.txt': False}
        view.entry_types = {'a.txt': 'Text document'}
        view.entry_sizes = {'a.txt': 2048}
        view.details = {'a.txt': 0}
        cells = {(0, 1): _Cell('1 KB'), (0, 2): _Cell('Old type'), (0, 3): _Cell('old')}
        view._details_table.item = lambda row, column: cells.get((row, column))
        view.backend = Mock()
        view._refresh_details_row_content([QtListItem('a.txt', 'a.txt')])
        view.backend.configure_item.assert_called_once_with('native-name', label='a.txt')
        self.assertEqual(cells[(0, 1)].value, '2.00 KiB')
        self.assertEqual(cells[(0, 2)].value, 'Text document')
        self.assertEqual(cells[(0, 3)].value, '')

    def test_arrow_navigation_routes_through_retained_model(self):
        dialog = LocalPathDialog.__new__(LocalPathDialog)
        dialog.winfo_exists = lambda: True
        dialog.isVisible = lambda: True
        dialog._folder_menu_is_open = lambda: False
        dialog._folder_menu_action_pending = False
        dialog._rename_path = dialog._rename_after_load = None
        dialog._list_keyboard_active = lambda: True
        dialog.listbox = SimpleNamespace(navigate=Mock())
        dialog.multiple = False
        with patch('WinUx.dialogs.local_folder_form.QKeyboard.modifiers', return_value=Qt.NoModifier):
            dialog._browser_key(None, None, Qt.Key_Down)
        dialog.listbox.navigate.assert_called_once_with(Qt.Key_Down, ctrl=False, shift=False)

    def test_ctrl_a_routes_to_multiple_selection_model(self):
        dialog = LocalPathDialog.__new__(LocalPathDialog)
        dialog.winfo_exists = lambda: True
        dialog.isVisible = lambda: True
        dialog._folder_menu_is_open = lambda: False
        dialog._folder_menu_action_pending = False
        dialog._rename_path = dialog._rename_after_load = None
        dialog._list_keyboard_active = lambda: True
        dialog.listbox = SimpleNamespace(navigate=Mock())
        dialog.multiple = True
        with patch('WinUx.dialogs.local_folder_form.QKeyboard.modifiers', return_value=Qt.ControlModifier):
            dialog._browser_key(None, None, Qt.Key_A)
        dialog.listbox.navigate.assert_called_once_with(Qt.Key_A, ctrl=True, shift=False)


if __name__ == '__main__':
    unittest.main()
