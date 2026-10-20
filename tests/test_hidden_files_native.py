"""Check hidden-file filtering and the Settings control with native DPG."""
import sys
from pathlib import PurePosixPath
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

if sys.platform != 'win32':
    raise unittest.SkipTest('requires native Windows Dear PyGui')
try:
    from WinUx.ui.components.explorer_list_view import dpg
except (ImportError, OSError) as exc:
    raise unittest.SkipTest('native Dear PyGui unavailable') from exc

from WinUx.ui.components.file_panel import FilePanel
from WinUx.dialogs.settings_form import SettingsDialog
from WinUx.models import FileItem
from WinUx.preferences.general import GeneralPreferences


class NativeHiddenFileTests(unittest.TestCase):
    def test_settings_checkbox_and_both_native_file_lists(self):
        dpg.create_context()
        try:
            parent = dpg.add_window(width=1000, height=600)
            panels = [FilePanel(parent, kind, {}, has_toolbar=False) for kind in ('local', 'server')]
            path = PurePosixPath('/work')
            items = [FileItem(name, path / name, is_dir, 0, 0, is_hidden=hidden)
                     for name, is_dir, hidden in (
                         ('model.inp', False, False), ('.ssh', True, False),
                         ('.bashrc', False, False), ('hidden.txt', False, True))]
            for panel in panels:
                panel.display(path, items)
                self.assertEqual([item.name for item in panel.listview.items], ['model.inp'])
                self.assertEqual(panel.listview._pinned_item.name, '..')
                self.assertEqual(dpg.get_value(panel.status_tag), '1 items')

            with tempfile.TemporaryDirectory() as root:
                prefs = GeneralPreferences(root=root)
                view = SimpleNamespace(after=lambda *args: None)
                with patch('WinUx.dialogs.settings_form.GeneralPreferences', return_value=prefs):
                    form = SettingsDialog(view)
                self.assertFalse(dpg.get_value(form.show_hidden_files))
                self.assertEqual(dpg.get_item_configuration(form.show_hidden_files)['label'],
                                 'Show hidden files and folders')
                dpg.set_value(form.show_hidden_files, True)
                prefs.save(auto_login=False, show_hidden_files=dpg.get_value(form.show_hidden_files))
                for panel in panels:
                    panel.set_show_hidden_files(prefs.load_show_hidden_files())
                    self.assertEqual(len(panel.listview.items), 4)
                    self.assertEqual(len(panel.listview._row_registry), 4)
                    self.assertEqual(dpg.get_value(panel.status_tag), '4 items')
                prefs.save_show_hidden_files(False)
                for panel in panels:
                    panel.set_show_hidden_files(prefs.load_show_hidden_files())
                    self.assertEqual([item.name for item in panel.listview.items], ['model.inp'])
                    self.assertEqual(len(panel.listview._row_registry), 1)
                    self.assertEqual(panel.listview._pinned_item.name, '..')
        finally:
            dpg.destroy_context()
