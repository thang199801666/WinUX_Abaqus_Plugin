"""Restart only the interactive SSH channel, with confirmation and no GUI I/O."""
from pathlib import Path, PurePosixPath
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.controller import WinUXController
from WinUx.server_model import SSHServerModel


class Shell:
    def __init__(self, fail=False):
        self.closed = False
        self.sent = []
        self.fail = fail
    def get_pty(self, **kwargs):
        self.pty = kwargs
    def invoke_shell(self):
        if self.fail:
            raise OSError('PTY unavailable')
    def close(self):
        self.closed = True
    def sendall(self, text):
        self.sent.append(text)
    def recv_ready(self):
        return False


class ConsoleRefreshTests(unittest.TestCase):
    def model(self):
        model = SSHServerModel()
        model.client, model.sftp = object(), object()
        model.home = PurePosixPath('/home/test')
        model.shell = Shell()
        model._shell_completion_directory = PurePosixPath('/work/current')
        model._shell_output.append('old raw output')
        model._shell_visible_output.append('old transcript')
        return model

    def test_refresh_replaces_only_pty_clears_streams_and_restores_cwd(self):
        model = self.model()
        old, stop = model.shell, model._shell_stop
        client, sftp, generation = model.client, model.sftp, model._shell_generation
        new = Shell()
        with patch.object(model, '_active_transport', return_value=object()), \
                patch.object(model, '_open_transport_session', return_value=new), \
                patch('WinUx.server_model.threading.Thread'):
            self.assertTrue(model.refresh_shell('/fallback', expected_client=client))
        self.assertIs(model.shell, new)
        self.assertTrue(old.closed and stop.is_set())
        self.assertIs(model.client, client)
        self.assertIs(model.sftp, sftp)
        self.assertNotEqual(model._shell_generation, generation)
        self.assertEqual(model.shell_raw_output(), '')
        self.assertEqual(model.shell_output(), '')
        self.assertEqual(new.sent, ["cd '/work/current'\n"])
        self.assertFalse(model._shell_stop.is_set())

    def test_failed_replacement_preserves_old_shell_and_transcript(self):
        model = self.model()
        old, generation = model.shell, model._shell_generation
        new = Shell(fail=True)
        with patch.object(model, '_active_transport', return_value=object()), \
                patch.object(model, '_open_transport_session', return_value=new):
            with self.assertRaisesRegex(OSError, 'PTY unavailable'):
                model.refresh_shell()
        self.assertIs(model.shell, old)
        self.assertFalse(old.closed or model._shell_stop.is_set())
        self.assertTrue(new.closed)
        self.assertEqual(model._shell_generation, generation)
        self.assertEqual(model.shell_output(), 'old transcript')

    def test_changed_connection_is_not_refreshed(self):
        model = self.model()
        with patch.object(model, '_open_shell') as open_shell:
            with self.assertRaisesRegex(RuntimeError, 'connection changed'):
                model.refresh_shell(expected_client=object())
            open_shell.assert_not_called()

    def test_in_flight_old_reader_cannot_append_to_replacement_stream(self):
        model = self.model()
        channel = Shell()
        with patch.object(model, '_active_transport', return_value=object()), \
                patch.object(model, '_open_transport_session', return_value=channel), \
                patch('WinUx.server_model.threading.Thread') as thread:
            model._open_shell()
        reader = thread.call_args.kwargs['target']
        stop = model._shell_stop
        channel.recv_ready = lambda: True
        def late_chunk(_size):
            stop.set()
            model.shell = Shell()
            return b'stale output'
        channel.recv = late_chunk
        reader()
        self.assertEqual(model.shell_raw_output(), '')
        self.assertEqual(model.shell_output(), '')

    def controller(self):
        workers = []
        app = SimpleNamespace(
            _closing=False, _connection_generation=1, _server_current_path=PurePosixPath('/work'),
            _ensure_server_online=Mock(return_value=True),
            server=SimpleNamespace(client=object(), refresh_shell=Mock()),
            view=SimpleNamespace(confirm_action_async=Mock(), show_error=Mock(),
                                 after=lambda delay, callback, *args: callback(*args)),
            _submit_background=Mock(side_effect=lambda name, worker, **kwargs:
                                    (workers.append(worker) or SimpleNamespace(state='queued'))))
        return app, workers

    def test_confirmation_then_worker_and_duplicate_request_guard(self):
        app, workers = self.controller()
        self.assertTrue(WinUXController.console_refresh(app))
        self.assertFalse(WinUXController.console_refresh(app))
        self.assertEqual(workers, [])
        app.view.confirm_action_async.call_args.args[2](True)
        app.server.refresh_shell.assert_not_called()
        self.assertEqual(len(workers), 1)
        workers.pop()()
        app.server.refresh_shell.assert_called_once_with(
            app._server_current_path, expected_client=app.server.client)
        self.assertFalse(app._console_refresh_active)

    def test_cancel_and_offline_do_not_restart_shell(self):
        app, workers = self.controller()
        WinUXController.console_refresh(app)
        app.view.confirm_action_async.call_args.args[2](False)
        self.assertEqual(workers, [])
        self.assertFalse(app._console_refresh_active)
        app._ensure_server_online.return_value = False
        self.assertFalse(WinUXController.console_refresh(app))
        app.server.refresh_shell.assert_not_called()

    def test_queue_rejection_reports_error_and_allows_retry(self):
        app, _workers = self.controller()
        app._submit_background.side_effect = None
        app._submit_background.return_value = SimpleNamespace(state='rejected')
        WinUXController.console_refresh(app)
        app.view.confirm_action_async.call_args.args[2](True)
        self.assertFalse(app._console_refresh_active)
        app.view.show_error.assert_called_once()

    def test_connection_switch_before_worker_skips_restart(self):
        app, workers = self.controller()
        WinUXController.console_refresh(app)
        app.view.confirm_action_async.call_args.args[2](True)
        app._connection_generation = 2
        workers.pop()()
        app.server.refresh_shell.assert_not_called()
        self.assertFalse(app._console_refresh_active)

    def test_confirmation_failure_does_not_leave_refresh_latched(self):
        app, _workers = self.controller()
        app.view.confirm_action_async.side_effect = RuntimeError('dialog unavailable')
        self.assertFalse(WinUXController.console_refresh(app))
        self.assertFalse(app._console_refresh_active)
        app.view.show_error.assert_called_once()


if __name__ == '__main__':
    unittest.main(verbosity=2)
