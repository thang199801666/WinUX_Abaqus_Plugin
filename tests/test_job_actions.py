from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from WinUx.controllers.job_actions import JobActionsController


def fixture():
    workers, callbacks = [], []
    dialog = SimpleNamespace(update_progress=Mock(), complete=Mock(), fail=Mock(),
                             winfo_exists=lambda: True)
    view = SimpleNamespace(
        after=lambda delay, cb, *args: callbacks.append((cb, args)),
        winfo_exists=lambda: True, show_error=Mock(), show_message=Mock(),
        confirm_action_async=Mock(), edit_job=Mock(), get_job_plots=Mock(return_value=None),
        close_job_plots=Mock(), show_transfer_progress=Mock(return_value=dialog),
        left=SimpleNamespace(current_path=Path('local')), right=object())
    app = SimpleNamespace(
        _closing=False, _connection_generation=1, view=view,
        server=SimpleNamespace(username='owner', cancel_job=Mock(),
            read_job_status=Mock(return_value='running'), job_details=Mock(return_value='details'),
            find_job_temp_folder=Mock(return_value='/tmp/job'), hot_download=Mock(return_value=Path('local/a.odb'))),
        _job_edit_settings={}, _schedule_job_deletion=Mock(),
        _selected_job_values=Mock(return_value=['1', 'job', 'owner']),
        _refresh_jobs_now=Mock(), _job_odb_command=Mock(), _open_job_plots=Mock(),
        open_path=Mock(), _select_path=Mock())
    def submit(name, worker):
        workers.append(worker)
        return SimpleNamespace(state='pending')
    app._submit_background = Mock(side_effect=submit)
    return app, JobActionsController(app), workers, callbacks, dialog


def drain(callbacks):
    while callbacks:
        cb, args = callbacks.pop(0)
        cb(*args)


class JobActionsTests(unittest.TestCase):
    def test_queued_modal_does_not_open_after_reconnect(self):
        app, actions, workers, callbacks, _ = fixture()
        actions.job_command('cancel')
        app._connection_generation += 1
        drain(callbacks)
        app.view.confirm_action_async.assert_not_called()
        self.assertEqual(workers, [])

    def test_confirmation_does_not_cancel_replacement_session(self):
        app, actions, workers, callbacks, _ = fixture()
        actions.job_command('cancel')
        drain(callbacks)
        confirm = app.view.confirm_action_async.call_args.args[-1]
        app._connection_generation += 1
        confirm(True)
        self.assertEqual(workers, [])

    def test_edit_does_not_schedule_after_reconnect(self):
        app, actions, _, callbacks, _ = fixture()
        actions.job_command('edit')
        drain(callbacks)
        edit = app.view.edit_job.call_args.args[-1]
        app._connection_generation += 1
        edit({'delay': 5})
        self.assertEqual(app._job_edit_settings, {})
        app._schedule_job_deletion.assert_not_called()

    def test_cancel_worker_checks_session_before_server_call(self):
        app, actions, workers, callbacks, _ = fixture()
        actions._continue_job_command('cancel', ['1', 'job', 'owner'])
        app._connection_generation += 1
        workers[0]()
        drain(callbacks)
        app.server.cancel_job.assert_not_called()
        app.view.show_error.assert_not_called()

    def test_cancel_success_refreshes_without_extra_server_query(self):
        app, actions, workers, callbacks, _ = fixture()
        actions._continue_job_command('cancel', ['1', 'job', 'OWNER'])
        workers[0]()
        drain(callbacks)
        app.server.cancel_job.assert_called_once_with('1')
        app._refresh_jobs_now.assert_called_once_with()

    def test_job_reads_capture_selection_and_suppress_old_results(self):
        for action, method in [('check', 'read_job_status'), ('details', 'job_details'),
                               ('open_temp', 'find_job_temp_folder')]:
            with self.subTest(action=action):
                app, actions, workers, callbacks, _ = fixture()
                actions.job_command(action)
                app._selected_job_values.return_value[:] = ['2', 'other', 'owner']
                workers[0]()
                self.assertEqual(getattr(app.server, method).call_args.args[0], '1')
                app._connection_generation += 1
                drain(callbacks)
                app.view.show_message.assert_not_called()
                app.open_path.assert_not_called()

    def test_old_queued_read_performs_no_server_call(self):
        app, actions, workers, callbacks, _ = fixture()
        actions.job_command('check')
        app._connection_generation += 1
        workers[0]()
        drain(callbacks)
        app.server.read_job_status.assert_not_called()

    def test_rejected_queue_reports_error_and_finishes_progress(self):
        for action in ['cancel', 'check', 'hot_download']:
            with self.subTest(action=action):
                app, actions, workers, callbacks, dialog = fixture()
                app._submit_background = Mock(return_value=SimpleNamespace(state='rejected'))
                if action == 'cancel':
                    actions._continue_job_command(action, ['1', 'job', 'owner'])
                else:
                    actions.job_command(action)
                drain(callbacks)
                receiver = dialog.fail if action == 'hot_download' else app.view.show_error
                self.assertIn('queue is full', receiver.call_args.args[-1])
                self.assertEqual(workers, [])

    def test_hot_download_old_session_finishes_window_without_navigation(self):
        app, actions, workers, callbacks, dialog = fixture()
        actions.job_command('hot_download')
        app._connection_generation += 1
        workers[0]()
        drain(callbacks)
        app.server.hot_download.assert_not_called()
        dialog.fail.assert_called_once()
        app.open_path.assert_not_called()

    def test_hot_download_progress_requests_cancel_on_session_change(self):
        app, actions, workers, callbacks, dialog = fixture()
        def download(*args, **kwargs):
            app._connection_generation += 1
            kwargs['progress']('file', 1, 2, 1, 2)
            self.assertTrue(kwargs['cancel'].is_set())
            return Path('local/a.odb')
        app.server.hot_download.side_effect = download
        actions.job_command('hot_download')
        with patch('WinUx.controllers.job_actions.AbaqusVersionPreferences'):
            workers[0]()
        drain(callbacks)
        dialog.update_progress.assert_not_called()
        dialog.fail.assert_called_once()
        app._select_path.assert_not_called()

    def test_plot_toggle_and_refresh_preserve_behavior(self):
        app, actions, workers, callbacks, _ = fixture()
        actions.job_command('job_plots')
        drain(callbacks)
        app._open_job_plots.assert_called_once_with(('1', 'job', 'owner'))
        app.view.get_job_plots.return_value = object()
        actions.job_command('job_plots')
        drain(callbacks)
        app.view.close_job_plots.assert_called_once_with('1')
        actions.job_command('refresh')
        app._refresh_jobs_now.assert_called_once_with()
        self.assertEqual(workers, [])

    def test_hot_download_success_uses_original_local_folder_and_selects_result(self):
        app, actions, workers, callbacks, dialog = fixture()
        actions.job_command('hot_download')
        app.view.left.current_path = Path('changed')
        with patch('WinUx.controllers.job_actions.AbaqusVersionPreferences') as preferences:
            preferences.return_value.ordered_commands.return_value = ['abq2026']
            workers[0]()
        drain(callbacks)
        call = app.server.hot_download.call_args
        self.assertEqual(call.args, ('1', 'job', Path('local')))
        self.assertEqual(call.kwargs['abaqus_commands'], ['abq2026'])
        dialog.complete.assert_called_once_with()
        app.open_path.assert_called_once_with(app.view.left, Path('local'), False)
        app._select_path.assert_called_once_with(app.view.left, Path('local/a.odb'))

    def test_cancelled_download_closes_progress_without_error(self):
        app, actions, workers, callbacks, dialog = fixture()
        app.server.hot_download.side_effect = RuntimeError('Operation cancelled')
        actions.job_command('hot_download')
        with patch('WinUx.controllers.job_actions.AbaqusVersionPreferences'):
            workers[0]()
        drain(callbacks)
        dialog.complete.assert_called_once_with()
        dialog.fail.assert_not_called()
        app.open_path.assert_not_called()

    def test_owner_and_shutdown_prevent_command_submission(self):
        app, actions, workers, callbacks, _ = fixture()
        app._selected_job_values.return_value = ['1', 'job', 'another']
        actions.job_command('check')
        app._closing = True
        actions.job_command('details')
        self.assertEqual(workers, [])
        self.assertEqual(callbacks, [])


if __name__ == '__main__':
    unittest.main()
