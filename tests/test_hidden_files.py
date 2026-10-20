import ast
import __future__
import os
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from WinUx.models import FileItem, FileSystemModel
from WinUx.preferences.general import GeneralPreferences
from WinUx.ui.components.explorer_list_model import ListViewItem


ROOT = Path(__file__).resolve().parents[1]


def load_class(relative_path, name, **namespace):
    path = ROOT / relative_path
    tree = ast.parse(path.read_text(encoding='utf-8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
    cls.bases = []
    module = ast.Module(body=[cls], type_ignores=[])
    exec(compile(module, str(path), 'exec', flags=__future__.annotations.compiler_flag), namespace)
    return namespace[name]


def panel_fixture(panel_id='server'):
    cls = load_class('WinUx/ui/components/file_panel.py', 'FilePanel',
                     ListViewItem=ListViewItem, PurePosixPath=PurePosixPath, os=os, dpg=Mock())
    panel = cls.__new__(cls)
    panel.panel_id = panel_id
    panel.current_path = PurePosixPath('/work')
    panel._show_hidden_files = False
    panel._source_items = []
    panel._filter_query = ''
    panel._pinned_parent = None
    panel._pending_created_rename = None
    panel.history = []
    panel.history_index = -1
    panel.toolbar = None
    panel.has_status = True
    panel.status_prefix = ''
    panel.status = Mock()
    panel.selected_status = Mock()
    panel._render_items = Mock()
    return panel


class HiddenFilePreferencesTests(unittest.TestCase):
    def test_default_is_hidden_and_setting_survives_reload(self):
        with tempfile.TemporaryDirectory() as root:
            prefs = GeneralPreferences(root=root)
            self.assertFalse(prefs.load_show_hidden_files())
            prefs.save_show_hidden_files(True)
            self.assertTrue(GeneralPreferences(root=root).load_show_hidden_files())
            prefs.save_show_hidden_files(False)
            self.assertFalse(GeneralPreferences(root=root).load_show_hidden_files())

    def test_save_preserves_console_and_other_general_preferences(self):
        with tempfile.TemporaryDirectory() as root:
            prefs = GeneralPreferences(root=root)
            prefs.save_console_visible(True)
            prefs.save(auto_login=True, show_hidden_files=True)
            prefs.save_auto_login(False)
            self.assertEqual(prefs.load(), {
                'auto_login': False, 'console_visible': True, 'show_hidden_files': True})
            prefs.save_show_hidden_files(False)
            self.assertTrue(prefs.load_console_visible())


class HiddenFileBrowsingTests(unittest.TestCase):
    def items(self):
        return [
            FileItem('model.inp', PurePosixPath('/work/model.inp'), False, 1, 0),
            FileItem('results', PurePosixPath('/work/results'), True, 0, 0),
            FileItem('.bashrc', PurePosixPath('/work/.bashrc'), False, 1, 0),
            FileItem('.ssh', PurePosixPath('/work/.ssh'), True, 0, 0),
            FileItem('hidden.txt', PurePosixPath('/work/hidden.txt'), False, 1, 0, is_hidden=True),
        ]

    def test_local_and_server_hide_files_and_folders_by_default(self):
        for panel_id in ('local', 'server'):
            panel = panel_fixture(panel_id)
            panel.display(PurePosixPath('/work'), self.items())
            visible = panel._render_items.call_args.args[0]
            self.assertEqual([item.name for item in visible], ['model.inp', 'results'])
            self.assertEqual(len(panel._source_items), 5)
            self.assertEqual(panel._pinned_parent.name, '..')
            panel.status.set.assert_called_with('2 items')

    def test_toggle_reuses_loaded_items_and_preserves_search_and_history(self):
        panel = panel_fixture()
        panel.display(PurePosixPath('/work'), self.items())
        history = list(panel.history)
        panel.apply_filter('ssh')
        self.assertEqual(panel._filtered_items(), [])
        panel.set_show_hidden_files(True)
        self.assertEqual([item.name for item in panel._filtered_items()], ['.ssh'])
        self.assertEqual(panel._filter_query, 'ssh')
        self.assertEqual(panel.history, history)
        panel.status.set.assert_called_with('1 of 5 items')
        panel.set_show_hidden_files(False)
        self.assertEqual(panel._filtered_items(), [])
        self.assertEqual(panel.history, history)
        panel.status.set.assert_called_with('0 of 2 items')

    def test_toggle_renders_all_loaded_items_when_search_is_empty(self):
        panel = panel_fixture()
        panel.display(PurePosixPath('/work'), self.items())
        panel.set_show_hidden_files(True)
        self.assertEqual(len(panel._render_items.call_args.args[0]), 5)
        panel.status.set.assert_called_with('5 items')
        panel.set_show_hidden_files(False)
        self.assertEqual(len(panel._render_items.call_args.args[0]), 2)

    def test_hidden_attribute_change_is_detected_by_directory_refresh_signature(self):
        panel = panel_fixture()
        visible = self.items()[0]
        hidden = FileItem(visible.name, visible.path, visible.is_dir, visible.size,
                          visible.modified, is_hidden=True)
        self.assertNotEqual(panel._item_signature(visible), panel._item_signature(hidden))
        self.assertEqual(panel._item_signature(hidden), panel._item_signature(panel._convert(hidden)))

    def test_local_listing_records_windows_hidden_attributes_without_extra_stat_calls(self):
        entry = Mock()
        entry.name, entry.path = 'normal_name.txt', '/work/normal_name.txt'
        entry.stat.return_value = SimpleNamespace(st_size=1, st_mtime=0, st_file_attributes=2)
        entry.is_dir.return_value = False
        scan = Mock()
        scan.__enter__ = Mock(return_value=[entry])
        scan.__exit__ = Mock(return_value=False)
        with patch('WinUx.models.filesystem.os.scandir', return_value=scan):
            items = FileSystemModel().list_directory(Path('/work'))
        self.assertTrue(items[0].is_hidden)
        entry.stat.assert_called_once_with(follow_symlinks=False)

    def test_settings_saved_event_updates_both_panels(self):
        adapter = load_class('WinUx/dialogs/floating_adapters.py', 'SettingsDialog')
        view = SimpleNamespace(panels=[panel_fixture('local'), panel_fixture('server')])
        # Load only the real main-view method without native GUI imports.
        path = ROOT / 'WinUx/view.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'WinUXView')
        method = next(node for node in cls.body if isinstance(node, ast.FunctionDef)
                      and node.name == 'apply_general_preferences')
        namespace = {}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
        view.apply_general_preferences = lambda values: namespace['apply_general_preferences'](view, values)
        dialog = adapter.__new__(adapter)
        dialog.view = view
        dialog.handle_event('settings_saved', {'values': {'show_hidden_files': True}})
        self.assertTrue(all(panel._show_hidden_files for panel in view.panels))
        dialog.handle_event('settings_saved', {'values': {'show_hidden_files': False}})
        self.assertFalse(any(panel._show_hidden_files for panel in view.panels))
