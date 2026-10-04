from pathlib import Path, PurePosixPath
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from WinUx.controllers.file_commands import FileCommandController


def fixture(remote=True):
    workers, callbacks = [], []
    panel = SimpleNamespace(panel_id='server' if remote else 'local',
        current_path=PurePosixPath('/folder') if remote else Path('folder'),
        status=SimpleNamespace(set=Mock()), clear_selection=Mock(),
        selected_transfer_paths=Mock(return_value=[PurePosixPath('/folder/a')]),
        selected_paths=Mock(return_value=[PurePosixPath('/folder/a')]),
        parent_selected=lambda: False, row_for_path=Mock(return_value=0),
        begin_inline_rename=Mock(), refocus_inline_rename=Mock(), select_row=Mock())
    app = SimpleNamespace(_closing=False, _connection_generation=1,
        view=SimpleNamespace(after=lambda delay, cb, *args: callbacks.append((cb, args)),
            winfo_exists=lambda: True, show_error=Mock(), confirm_action_async=Mock()),
        server=SimpleNamespace(delete=Mock(return_value=['/folder/a']),
            new_file=Mock(return_value=PurePosixPath('/folder/new')), new_folder=Mock(return_value=PurePosixPath('/folder/new')),
            rename=Mock(return_value=PurePosixPath('/folder/b'))),
        model=SimpleNamespace(delete=Mock(), rename=Mock(return_value=Path('folder/b'))),
        _refresh_all=Mock(), _select_path=Mock(), open_path=Mock())
    def submit(name, worker):
        workers.append(worker)
        return SimpleNamespace(state='pending')
    app._submit_background = Mock(side_effect=submit)
    return app, panel, FileCommandController(app), workers, callbacks


def drain(callbacks):
    while callbacks:
        cb, args = callbacks.pop(0)
        cb(*args)


class FileCommandTests(unittest.TestCase):
    def test_delete_confirmation_is_scoped_to_original_session(self):
        app, panel, commands, workers, callbacks = fixture()
        commands.command(panel, 'delete')
        callback = app.view.confirm_action_async.call_args.args[2]
        app._connection_generation += 1
        callback(True)
        self.assertEqual(workers, [])
        app.server.delete.assert_not_called()

    def test_delete_uses_frozen_selection_and_runs_off_ui(self):
        app, panel, commands, workers, callbacks = fixture()
        selected = [PurePosixPath('/original')]
        commands.command(panel, 'delete', selected)
        selected[:] = [PurePosixPath('/new')]
        app.view.confirm_action_async.call_args.args[2](True)
        app.server.delete.assert_not_called()
        workers[0]()
        drain(callbacks)
        app.server.delete.assert_called_once_with([PurePosixPath('/original')])
        panel.clear_selection.assert_called_once_with()
        app._refresh_all.assert_called_once_with()

    def test_stale_queued_delete_never_contacts_new_server(self):
        app, panel, commands, workers, callbacks = fixture()
        commands._delete_server_items(panel, ['/a'])
        app._connection_generation += 1
        workers[0]()
        drain(callbacks)
        app.server.delete.assert_not_called()
        app._refresh_all.assert_not_called()

    def test_delete_result_cannot_refresh_replacement_session(self):
        app, panel, commands, workers, callbacks = fixture()
        commands._delete_server_items(panel, ['/a'])
        workers[0]()
        app._connection_generation += 1
        drain(callbacks)
        panel.clear_selection.assert_not_called()
        app._refresh_all.assert_not_called()

    def test_rejected_delete_reports_without_refresh_or_server_call(self):
        app, panel, commands, workers, callbacks = fixture()
        app._submit_background = Mock(return_value=SimpleNamespace(state='rejected'))
        commands._delete_server_items(panel, ['/a'])
        drain(callbacks)
        app._refresh_all.assert_not_called()
        app.server.delete.assert_not_called()
        self.assertIn('queue is full', app.view.show_error.call_args.args[-1])

    def test_partial_delete_failure_still_refreshes(self):
        app, panel, commands, workers, callbacks = fixture()
        app.server.delete.side_effect = OSError('partial failure')
        commands._delete_server_items(panel, ['/a'])
        workers[0]()
        drain(callbacks)
        app._refresh_all.assert_called_once_with()
        app.view.show_error.assert_called_once_with('Delete from server', 'partial failure')

    def test_local_delete_survives_ssh_reconnect_but_not_shutdown(self):
        app, panel, commands, workers, callbacks = fixture(remote=False)
        commands.command(panel, 'delete')
        confirm = app.view.confirm_action_async.call_args.args[2]
        app._connection_generation += 1
        confirm(True)
        app.model.delete.assert_called_once()
        app.model.delete.reset_mock()
        app._closing = True
        confirm(True)
        app.model.delete.assert_not_called()

    def test_create_runs_off_ui_and_preserves_requested_folder(self):
        for action in ('new_file', 'new_folder'):
            with self.subTest(action=action):
                app, panel, commands, workers, callbacks = fixture()
                commands.command(panel, action)
                getattr(app.server, action).assert_not_called()
                panel.current_path = PurePosixPath('/other')
                workers[0]()
                drain(callbacks)
                getattr(app.server, action).assert_called_once_with(PurePosixPath('/folder'))
                app.open_path.assert_not_called()
                panel.begin_inline_rename.assert_not_called()

    def test_create_success_starts_rename_for_same_directory(self):
        app, panel, commands, workers, callbacks = fixture()
        commands.command(panel, 'new_file')
        workers[0]()
        drain(callbacks)
        panel.begin_inline_rename.assert_called_once()
        app._connection_generation += 1
        rename = panel.begin_inline_rename.call_args.args[-1]
        self.assertFalse(rename('changed'))
        app.server.rename.assert_not_called()

    def test_stale_or_rejected_creation_makes_no_server_call(self):
        app, panel, commands, workers, callbacks = fixture()
        commands.command(panel, 'new_file')
        app._connection_generation += 1
        workers[0]()
        drain(callbacks)
        app.server.new_file.assert_not_called()
        app._submit_background = Mock(return_value=SimpleNamespace(state='rejected'))
        commands.command(panel, 'new_folder')
        drain(callbacks)
        app.server.new_folder.assert_not_called()
        self.assertIn('queue is full', app.view.show_error.call_args.args[-1])

    def test_existing_inline_rename_rejects_new_session(self):
        app, panel, commands, workers, callbacks = fixture()
        commands.command(panel, 'rename')
        callback = panel.begin_inline_rename.call_args.args[-1]
        app._connection_generation += 1
        self.assertFalse(callback('new'))
        app.server.rename.assert_not_called()

    def test_rename_keeps_result_and_error_contract(self):
        app, panel, commands, workers, callbacks = fixture(remote=False)
        result = commands._finish_inline_rename(panel, '/a', 'b')
        self.assertEqual(result, Path('folder/b'))
        drain(callbacks)
        app._select_path.assert_called_once_with(panel, result)
        app.model.rename.side_effect = ValueError('bad name')
        self.assertFalse(commands._finish_inline_rename(panel, '/a', 'bad'))
        app.view.show_error.assert_called_once_with('Rename failed', 'bad name')

    def test_remote_rename_returns_pending_and_finishes_on_ui_delivery(self):
        app, panel, commands, workers, callbacks = fixture()
        result = commands._finish_inline_rename(panel, '/a', 'b')
        app.server.rename.assert_not_called()
        self.assertFalse(result.done)
        changes = []
        result.then(changes.append)
        workers[0]()
        self.assertFalse(result.done)
        drain(callbacks)
        self.assertEqual(changes, [True])
        app._select_path.assert_called_once_with(panel, PurePosixPath('/folder/b'))

    def test_remote_rename_failure_and_queue_rejection_keep_editor_contract(self):
        for rejected in (False, True):
            with self.subTest(rejected=rejected):
                app, panel, commands, workers, callbacks = fixture()
                if rejected:
                    app._submit_background = Mock(return_value=SimpleNamespace(state='rejected'))
                else:
                    app.server.rename.side_effect = RuntimeError('SSH failure')
                result = commands._finish_inline_rename(panel, '/a', 'b')
                if workers:
                    workers[0]()
                drain(callbacks)
                self.assertTrue(result.done)
                self.assertFalse(result.success)
                app.view.show_error.assert_called_once()
                app._refresh_all.assert_not_called()

    def test_stale_remote_rename_settles_without_new_session_io_or_ui(self):
        app, panel, commands, workers, callbacks = fixture()
        result = commands._finish_inline_rename(panel, '/a', 'b')
        app._connection_generation += 1
        workers[0]()
        drain(callbacks)
        app.server.rename.assert_not_called()
        app.view.show_error.assert_not_called()
        self.assertTrue(result.done)
        self.assertFalse(result.success)

    def test_rename_result_does_not_navigate_after_directory_or_session_change(self):
        for reconnect in (False, True):
            with self.subTest(reconnect=reconnect):
                app, panel, commands, workers, callbacks = fixture()
                result = commands._finish_inline_rename(panel, '/a', 'b')
                workers[0]()
                if reconnect:
                    app._connection_generation += 1
                else:
                    panel.current_path = PurePosixPath('/other')
                drain(callbacks)
                app._refresh_all.assert_not_called()
                app._select_path.assert_not_called()
                self.assertEqual(result.success, not reconnect)

    def test_completed_rename_does_not_refresh_away_a_new_editor(self):
        app, panel, commands, workers, callbacks = fixture()
        panel._rename_commit_callback = Mock()
        result = commands._finish_inline_rename(panel, '/a', 'b')
        workers[0]()
        panel._rename_commit_callback = Mock()
        drain(callbacks)
        self.assertTrue(result.success)
        app._refresh_all.assert_not_called()
        app._select_path.assert_not_called()

    def test_shortcut_and_clipboard_dispatch_keeps_existing_pipelines(self):
        app, panel, commands, workers, callbacks = fixture()
        app.transfer_selected = Mock()
        app.edit_server_file = Mock()
        app._publish_file_clipboard = Mock()
        app._paste_file_clipboard = Mock()
        panel.item_for_row = Mock(return_value=SimpleNamespace(is_dir=False))
        selected = [PurePosixPath('/folder/a')]
        for action in ('transfer_selected', 'upload_selected', 'download_selected'):
            commands.command(panel, action, selected)
        self.assertEqual(app.transfer_selected.call_count, 3)
        app.transfer_selected.assert_called_with(panel, selected)
        commands.command(panel, 'edit', selected)
        app.edit_server_file.assert_called_once_with(panel, selected)
        commands.command(panel, 'copy', selected)
        app._publish_file_clipboard.assert_called_once_with(panel, selected, move=False)
        commands.command(panel, 'cut', selected)
        app._publish_file_clipboard.assert_called_with(panel, selected, move=True)
        commands.command(panel, 'paste', selected)
        app._paste_file_clipboard.assert_called_once_with(panel)
        commands.command(panel, 'parent')
        app.open_path.assert_called_once_with(panel, PurePosixPath('/'))
        self.assertEqual(workers, [])

    def test_warning_keeps_bounded_preview_and_count(self):
        message = FileCommandController._delete_warning_message(
            [PurePosixPath('/folder/file{}'.format(n)) for n in range(10)], 'server')
        self.assertIn('10 item(s)', message)
        self.assertIn('- file5', message)
        self.assertNotIn('- file6', message)
        self.assertIn('4 more', message)
        self.assertIn('cannot be undone', message)


if __name__ == '__main__':
    unittest.main()
