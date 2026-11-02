"""File masks, saved columns, retry and conflict policy regression tests."""
import itertools
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.services.file_filter import compile_file_filter
from WinUx.preferences.navigation import NavigationPreferences
from WinUx.ui.components.explorer_list_model import ListViewItem, DEFAULT_COLUMNS
from WinUx.ui.components.explorer_columns import ExplorerColumnsMixin
from WinUx.dialogs.logic.transfer import TransferCenterLogic
from WinUx.controllers.transfer import TransferController
from WinUx.services.remote_filesystem import RemoteFilesystemMixin


class Center(TransferCenterLogic):
    def __init__(self):
        self.tasks, self._row_to_task, self.updates = [], {}, {}
        self._row_ids = itertools.count(1)
        self.view = SimpleNamespace(after=lambda delay, callback, *args: callback(*args))
        self.show, self.hide = Mock(), Mock()
    def post(self, *args):
        return True
    def update_row(self, row_id, **values):
        self.updates.setdefault(row_id, {}).update(values)


class WorkflowTests(unittest.TestCase):
    def test_masks_and_substring_compatibility(self):
        rows = [ListViewItem(name, path='/work/' + name, item_type='Text Document')
                for name in ('Job.INP', 'Job.odb', 'Job.inp.bak', 'other.txt', '.hidden.inp')]
        def names(query):
            return [r.name for r in rows if compile_file_filter(query)(r)]
        self.assertEqual(names('*.inp;*.odb|.hidden*'), ['Job.INP', 'Job.odb'])
        self.assertEqual(names('|*.bak'), ['Job.INP', 'Job.odb', 'other.txt', '.hidden.inp'])
        self.assertEqual(names('job'), ['Job.INP', 'Job.odb', 'Job.inp.bak'])
        self.assertEqual(names('text document'), [r.name for r in rows])
        self.assertEqual(names('/work'), [r.name for r in rows])
        self.assertEqual(names(''), [r.name for r in rows])
        self.assertEqual(names('Job.?db'), ['Job.odb'])
        self.assertIs(compile_file_filter('*.inp'), compile_file_filter('*.inp'))
        for i in range(200):
            compile_file_filter('*.{}'.format(i))
        self.assertLessEqual(compile_file_filter.cache_info().currsize, 128)

    def columns(self):
        obj = ExplorerColumnsMixin()
        obj.columns = [dict(c) for c in DEFAULT_COLUMNS]
        obj.MIN_COLUMN_WIDTH = 40
        obj._column_widths, obj.auto_width_enabled = {}, True
        obj._ensure_column_widths, obj._rebuild_draw_items = Mock(), Mock()
        obj._fit_columns_auto_width = Mock()
        obj._available_width = lambda: 800
        return obj

    def test_column_state_validation_and_new_defaults(self):
        listing = self.columns()
        self.assertFalse(listing.restore_column_state({'columns': 'bad'}))
        self.assertTrue(listing.restore_column_state({'columns': [
            {'key': 'owner', 'visible': True, 'width': 150, 'align': 'right'},
            {'key': 'size', 'width': 'nan'}, {'key': 'removed', 'visible': True},
            {'key': 'owner', 'width': 999}, {'key': ['bad']}, None], 'auto_width': False}))
        self.assertEqual(listing.columns[0]['key'], 'owner')
        self.assertTrue(listing.columns[0]['visible'])
        self.assertEqual(listing._column_widths['owner'], 150)
        self.assertFalse(listing.auto_width_enabled)
        self.assertNotIn('size', listing._column_widths)
        self.assertEqual(len(listing.columns), len(DEFAULT_COLUMNS))
        listing.restore_column_state({'columns': [dict(key=c['key'], visible=False) for c in DEFAULT_COLUMNS]})
        self.assertTrue(listing.get_column('name')['visible'])

    def test_column_preferences_separate_panels(self):
        root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
        with tempfile.TemporaryDirectory(dir=root) as profile:
            prefs = NavigationPreferences(root=profile)
            self.assertIsNone(prefs.load_columns('local'))
            state = self.columns().column_state()
            prefs.save_columns('local', state)
            self.assertEqual(prefs.load_columns('local'), state)
            self.assertIsNone(prefs.load_columns('server'))
            listing = self.columns()
            listing.restore_column_state(prefs.load_columns('local'))
            self.assertEqual(listing.columns, [dict(c) for c in DEFAULT_COLUMNS])

    def test_failed_batch_retry_is_explicit_and_deduplicated(self):
        center = Center()
        task = center.add_task('Upload', threading.Event(), ['a', 'b'])
        retry = Mock()
        task.set_retry(retry)
        task.fail('network error')
        self.assertEqual(center.updates[task.rows[0].row_id]['action'], 'Retry')
        center._handle_row_action(task.rows[0].row_id)
        center._handle_row_action(task.rows[1].row_id)
        retry.assert_called_once_with(task)
        task.retry_ready()
        self.assertTrue(task.request_retry())
        self.assertEqual(retry.call_count, 2)
        center.clear_finished()
        self.assertIsNone(task._retry_callback)

    def test_cancelled_task_does_not_retry(self):
        center = Center()
        event = threading.Event()
        task = center.add_task('Download', event, ['a'])
        task.set_retry(Mock())
        event.set()
        task.fail('Operation cancelled')
        self.assertEqual(task.state, 'cancelled')
        self.assertFalse(task.request_retry())

    def controller(self):
        app = SimpleNamespace(_closing=False, view=Mock(),
                              server=SimpleNamespace(host='site', _port=22, username='user'),
                              _ensure_server_online=Mock(return_value=True))
        return TransferController(app)

    def test_retry_frozen_destination_and_site_guard(self):
        controller = self.controller()
        source, target = SimpleNamespace(panel_id='local'), SimpleNamespace(panel_id='server', current_path='/new')
        center = Center()
        task = center.add_task('Upload', threading.Event(), ['a'])
        controller._attach_retry(task, source, target, [Path('a')], '/original')
        task.fail('error')
        controller.process_queued_drop = Mock()
        task.request_retry()
        confirmed = controller.view.confirm_action_async.call_args.args[2]
        confirmed(False)
        self.assertFalse(task._retry_pending)
        task.request_retry()
        controller.view.confirm_action_async.call_args.args[2](True)
        controller.process_queued_drop.assert_called_once_with(source, target, '/original', True, (Path('a'),))
        self.assertNotIn(task, center.tasks)

        task = center.add_task('Upload', threading.Event(), ['a'])
        controller._attach_retry(task, source, target, [Path('a')], '/original')
        task.fail('error')
        controller.server.host = 'other-site'
        task.request_retry()
        controller.view.confirm_action_async.call_args.args[2](True)
        self.assertIn(task, center.tasks)
        self.assertFalse(task._retry_pending)
        self.assertEqual(controller.process_queued_drop.call_count, 1)

    def test_skip_conflicts_only_transfers_remaining_sources(self):
        controller = self.controller()
        controller.continue_drop_after_overwrite = Mock()
        controller.app.POST_MODAL_TRANSFER_DELAY_MS = 0
        source = SimpleNamespace(panel_id='local', status=Mock())
        target = SimpleNamespace(panel_id='server')
        center, event = Center(), threading.Event()
        original = center.add_task('Upload', event, ['a', 'b'])
        replacement = center.add_task('Upload', event, ['b'])
        controller.view.show_transfer_progress.return_value = replacement
        controller.drop_conflicts_ready(source, target, [Path('a'), Path('b')], '/dest', True, ['a'], original, event)
        callback = controller.view.confirm_action_checkbox_async.call_args.args[2]
        callback(True, True)
        args = controller.continue_drop_after_overwrite.call_args.args
        self.assertEqual(args[3], [Path('b')])
        self.assertIs(args[6], replacement)
        self.assertNotIn(original, center.tasks)

    def test_skip_all_never_starts_transfer(self):
        controller = self.controller()
        controller.continue_quick_after_overwrite = Mock()
        source = SimpleNamespace(panel_id='local', status=Mock())
        target = SimpleNamespace(panel_id='server')
        controller.quick_conflicts_ready(source, target, [Path('a')], '/dest', '.inp', 'Upload', ['a'])
        controller.view.confirm_action_checkbox_async.call_args.args[2](True, True)
        controller.continue_quick_after_overwrite.assert_not_called()

    def test_old_confirmation_cannot_retry_cleared_task(self):
        controller = self.controller()
        center = Center()
        task = center.add_task('Upload', threading.Event(), ['a'])
        controller._attach_retry(task, SimpleNamespace(panel_id='local'), SimpleNamespace(panel_id='server'), [Path('a')], '/dest')
        task.fail('error')
        task.request_retry()
        confirmed = controller.view.confirm_action_async.call_args.args[2]
        center.clear_finished()
        controller.process_queued_drop = Mock()
        confirmed(True)
        controller.process_queued_drop.assert_not_called()

    def test_name_only_conflict_listing(self):
        remote = RemoteFilesystemMixin()
        remote.connected = True
        remote._connection_lock = threading.RLock()
        remote.normalize = str
        remote.sftp = Mock()
        remote.sftp.listdir.return_value = ['existing.inp']
        self.assertEqual(remote.list_directory_names('/dest'), ['existing.inp'])
        remote.sftp.listdir_attr.assert_not_called()
        controller = self.controller()
        controller.app.server = remote
        self.assertEqual(controller.cross_panel_conflicts(SimpleNamespace(panel_id='server'),
                         [Path('existing.inp'), Path('new.inp')], '/dest'), ['existing.inp'])

    def test_queue_rejection_and_connection_changed_before_execution(self):
        controller = self.controller()
        controller.app._connection_generation = 1
        controller.app._submit_transfer = Mock(return_value=SimpleNamespace(state='queued'))
        controller.server.upload = Mock()
        controller.transfer_failed = Mock()
        source, target = SimpleNamespace(panel_id='local', status=Mock()), SimpleNamespace(panel_id='server', status=Mock())
        dialog = Mock()
        controller.start_drop_transfer(source, target, [Path('a')], '/dest', True, dialog)
        worker = controller.app._submit_transfer.call_args.args[1]
        controller.app._connection_generation = 2
        worker()
        controller.server.upload.assert_not_called()
        controller.view.after.call_args.args[1]()
        self.assertIn('Server connection changed', controller.transfer_failed.call_args.args[0])
        controller.app._submit_transfer.return_value = SimpleNamespace(state='rejected')
        controller.start_drop_transfer(source, target, [Path('a')], '/dest', True, dialog)
        controller.transfer_failed.assert_called_with('Transfer queue is full', dialog)

    def test_connection_change_during_confirmation_or_delay(self):
        controller = self.controller()
        controller.app._connection_generation = 1
        controller.app.POST_MODAL_TRANSFER_DELAY_MS = 0
        controller.start_drop_transfer = Mock()
        controller.transfer_failed = Mock()
        source, target = SimpleNamespace(panel_id='local', status=Mock()), SimpleNamespace(panel_id='server', status=Mock())
        dialog, event = Mock(), threading.Event()
        controller.drop_conflicts_ready(source, target, [Path('a')], '/dest', True, ['a'], dialog, event)
        confirmed = controller.view.confirm_action_checkbox_async.call_args.args[2]
        controller.app._connection_generation = 2
        confirmed(True, False)
        controller.start_drop_transfer.assert_not_called()
        dialog.fail.assert_called_once()
        controller.continue_drop_after_overwrite(True, source, target, [Path('a')], '/dest', True, dialog, event)
        start = controller.view.after.call_args.args[1]
        controller.app._connection_generation = 3
        start()
        controller.start_drop_transfer.assert_not_called()
        self.assertIn('Server connection changed', controller.transfer_failed.call_args.args[0])

    def test_quick_transfer_only_waits_after_an_actual_modal(self):
        controller = self.controller()
        controller.app.POST_MODAL_TRANSFER_DELAY_MS = 20
        controller.start_quick_transfer = Mock()
        source, target = SimpleNamespace(status=Mock()), SimpleNamespace(status=Mock())
        controller.quick_conflicts_ready(source, target, [Path('a')], '/dest', '.inp', 'Upload', [])
        self.assertEqual(controller.view.after.call_args.args[0], 0)
        controller.view.after.call_args.args[1]()
        controller.start_quick_transfer.assert_called_once()
        controller.continue_quick_after_overwrite(True, source, target, [Path('a')], '/dest', '.inp', 'Upload')
        self.assertEqual(controller.view.after.call_args.args[0], 20)


if __name__ == '__main__':
    unittest.main(verbosity=2)
