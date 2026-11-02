"""ODB submenu grouping, selection gating and unchanged command routing."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.ui.components.file_panel import FilePanel
from WinUx.ui.components.jobs_view import JobsView


class OdbToolsTests(unittest.TestCase):
    def panel(self, kind='server', connected=True):
        panel = FilePanel.__new__(FilePanel)
        panel.panel_id = kind
        panel.callbacks = {
            'server_connected': lambda: connected,
            'file_clipboard_available': lambda: False,
            'check_odb': Mock(), 'extract_odb': Mock(), 'upgrade_odb': Mock(),
        }
        panel.visible_files = lambda extension: []
        panel.listview = SimpleNamespace(set_context_menu_item_enabled=Mock())
        return panel

    def item(self, name='sample.odb', *, directory=False, parent=False):
        return SimpleNamespace(name=name, path='/test/' + name, size=123,
                               is_dir=directory, data={'parent': parent})

    def states(self, panel, items):
        panel._context_menu_open(items)
        return dict(call.args for call in panel.listview.set_context_menu_item_enabled.call_args_list)

    def test_server_groups_all_three_commands_in_one_flat_submenu(self):
        panel = self.panel()
        with patch('WinUx.ui.components.file_panel.ResourceTextures.get', return_value=None):
            menu = panel._context_menu_spec()
        tools = [entry for entry in menu if isinstance(entry, dict) and entry.get('label') == 'Odb Tools']
        self.assertEqual(len(tools), 1)
        self.assertEqual([entry['label'] for entry in tools[0]['children']],
                         ['Quick Check', 'Extract Data', 'Upgrade ODB'])
        self.assertEqual([entry['action'] for entry in tools[0]['children']],
                         ['check_odb', 'extract_odb', 'upgrade_odb'])
        self.assertFalse(any(isinstance(entry, dict) and entry.get('action') in
                             ('check_odb', 'extract_odb', 'upgrade_odb') for entry in menu))
        self.assertTrue(any(isinstance(entry, tuple) and entry[0] == 'Check INP' for entry in menu))

    def test_local_groups_existing_commands_without_adding_remote_extraction(self):
        panel = self.panel('local')
        with patch('WinUx.ui.components.file_panel.ResourceTextures.get', return_value=None):
            menu = panel._context_menu_spec()
        group = next(entry for entry in menu if isinstance(entry, dict) and entry.get('id') == 'odb_tools_group')
        self.assertEqual([entry['action'] for entry in group['children']], ['check_odb', 'upgrade_odb'])

    def test_single_odb_enables_all_server_tools(self):
        states = self.states(self.panel(), [self.item('sample.ODB')])
        for action in ('odb_tools_group', 'check_odb', 'extract_odb', 'upgrade_odb'):
            self.assertTrue(states[action], action)

    def test_mixed_batch_keeps_group_accessible_for_upgrade(self):
        for kind in ('server', 'local'):
            states = self.states(self.panel(kind), [self.item(), self.item('input.inp')])
            self.assertTrue(states['odb_tools_group'])
            self.assertTrue(states['upgrade_odb'])
            self.assertFalse(states['check_odb'])
            if kind == 'server':
                self.assertFalse(states['extract_odb'])

    def test_empty_non_odb_and_directory_selections_disable_group(self):
        for items in ([], [self.item('input.inp')], [self.item(directory=True)], [self.item('..', parent=True)]):
            states = self.states(self.panel(), items)
            self.assertFalse(states['odb_tools_group'])

    def test_server_disconnect_disables_tools_but_not_local_odb_inspection(self):
        states = self.states(self.panel(connected=False), [self.item()])
        for action in ('odb_tools_group', 'check_odb', 'extract_odb', 'upgrade_odb'):
            self.assertFalse(states[action])
        states = self.states(self.panel('local', connected=False), [self.item()])
        self.assertTrue(states['odb_tools_group'])
        self.assertTrue(states['check_odb'])

    def test_actions_keep_selection_snapshot_and_upgrade_filters_non_odb(self):
        panel = self.panel()
        odb = self.item()
        panel._menu_action('check_odb', [odb])
        panel.callbacks['check_odb'].assert_called_once_with(panel, ['/test/sample.odb'])
        panel._menu_action('extract_odb', [odb])
        panel.callbacks['extract_odb'].assert_called_once_with(panel, ['/test/sample.odb'])
        panel._menu_action('upgrade_odb', [odb, self.item('input.inp'), self.item('folder.odb', directory=True)])
        panel.callbacks['upgrade_odb'].assert_called_once_with(panel, ['/test/sample.odb'])

    def test_job_menu_uses_same_group_name_and_keeps_job_actions(self):
        with patch('WinUx.ui.components.jobs_view.ResourceTextures.get', return_value=None):
            menu = JobsView.job_context_menu()
        group = next(entry for entry in menu if entry.get('id') == 'job_check_odb_group')
        self.assertEqual(group['label'], 'Odb Tools')
        self.assertEqual([entry['action'] for entry in group['children']],
                         ['job_check_odb', 'job_extract_odb'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
