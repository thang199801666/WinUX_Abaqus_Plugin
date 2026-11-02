"""Chooser folder semantics must not depend on localized Shell Type labels."""
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from DearUIQt.backends import dpg
from DearUIQt.modelview import QtListItem
from WinUx.dialogs import local_folder_form as folders
from WinUx.dialogs.local_file_form import LocalFileDialog
from WinUx.dialogs.path_selection import PathSelectionOptions
from WinUx.platform.windows_icons import WindowsIconRegistry


class FileSelectorMetadataTests(unittest.TestCase):
    def test_folder_double_click_override_accepts_shared_row_key(self):
        # Both selectors inherit this override. It deliberately disables the
        # shared detector: their routed same-row press history owns activation.
        listing = SimpleNamespace()
        self.assertFalse(folders.FolderListView._is_double_click(listing))
        self.assertFalse(folders.FolderListView._is_double_click(listing, 'folder'))

    def test_scan_preserves_directory_flag_independent_of_type_and_stat(self):
        root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
        with tempfile.TemporaryDirectory(dir=root) as directory:
            (Path(directory) / 'folder.inp').mkdir()
            (Path(directory) / 'model.inp').write_text('test')
            dialog = SimpleNamespace(
                _generation=0, _current_path=directory, _show_hidden_items=False,
                winfo_exists=lambda: True, _set_status=Mock(),
                _include_entry=lambda entry, is_dir: True,
                _apply_entries=Mock(),
                runAsync=lambda worker, on_result: on_result(worker()))
            with patch.object(folders, 'file_type_name', return_value='Localized label'):
                folders.LocalFolderDialog._refresh(dialog)
            args = dialog._apply_entries.call_args.args
            self.assertEqual(set(args[5].values()), {'Localized label'})
            self.assertEqual(args[7], {
                str(Path(directory) / 'folder.inp'): True,
                str(Path(directory) / 'model.inp'): False})

    def test_select_folder_does_not_replace_filename(self):
        dialog = SimpleNamespace(
            _entries={'folder.inp': 'folder.inp', 'model.inp': 'model.inp'},
            _entry_is_dirs={'folder.inp': True, 'model.inp': False},
            file_edit='filename', folder_edit='filename', _overwrite_path='existing',
            multiple=False, selection_options=PathSelectionOptions('file'),
            _folder_edit_control=Mock(), _sync_right_pane=Mock())
        with patch.object(folders, 'set_editor_text') as set_value:
            LocalFileDialog._selection_changed(dialog, 'folder.inp')
            set_value.assert_not_called()
            self.assertEqual(dialog._overwrite_path, 'existing')
            LocalFileDialog._selection_changed(dialog, 'model.inp')
            set_value.assert_called_once_with(dialog._folder_edit_control, 'model.inp')
            self.assertIsNone(dialog._overwrite_path)

    def test_rows_use_directory_metadata_for_icon_and_size(self):
        dpg.create_context()
        listing = None
        try:
            window = dpg.add_window()
            listing = folders.FolderListView(parent=window)
            listing.entry_types = {'folder.inp': 'File folder', 'model.inp': 'Folder'}
            listing.entry_is_dirs = {'folder.inp': True, 'model.inp': False}
            listing.entry_sizes = {'folder.inp': 999, 'model.inp': 123}
            with patch.object(folders, 'folder_item_texture', wraps=folders.folder_item_texture) as folder_icon, \
                    patch.object(WindowsIconRegistry, 'get_icon', wraps=WindowsIconRegistry.get_icon) as icon, \
                    patch.object(listing, '_format_size', wraps=listing._format_size) as format_size:
                listing.setItems([QtListItem(key, key, key) for key in listing.entry_types])
                folder_icon.assert_called_once_with(size=folders.METRICS.list_icon_size, padding=1)
                self.assertTrue(any(call.args == ('.inp',) for call in icon.call_args_list))
                format_size.assert_called_once_with(123)
            image = dpg.get_item_configuration(listing.icons['folder.inp'])
            content_height = folders.METRICS.row_height - 2 * folders.METRICS.table_cell_padding_y
            # Native image widgets replaced the old clipped draw-image rect.
            self.assertEqual(image['width'], folders.METRICS.list_icon_size + 2)
            self.assertEqual(image['height'], folders.METRICS.list_icon_size + 2)
            self.assertLessEqual(image['height'], content_height)
            listing.setCurrentKey('model.inp')
            listing._qt_bridge_click = None
            # A reused native navigation target may report row zero before the
            # authoritative press router runs. It must not change the model.
            with patch.object(listing, '_table_row_key_at', return_value='folder.inp'):
                listing._clicked(listing.items['folder.inp'], True, 'folder.inp')
            self.assertEqual(listing.current, 'model.inp')
            self.assertEqual(listing.selected, {'model.inp'})
            self.assertFalse(dpg.get_value(listing.items['folder.inp']))
            self.assertTrue(listing._route_pointer_key('folder.inp'))
            self.assertEqual(listing.selected, {'folder.inp'})
            # Release notifications must not undo the routed selection.
            listing._clicked(listing.items['model.inp'], True, 'model.inp')
            self.assertEqual(listing.selected, {'folder.inp'})
        finally:
            if listing is not None:
                listing.delete()
            WindowsIconRegistry.reset()
            dpg.destroy_context()


if __name__ == '__main__':
    unittest.main(verbosity=2)
