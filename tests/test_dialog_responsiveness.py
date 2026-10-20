"""Confirmations must not lose requests or leave Exit permanently pending."""
from collections import deque
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from WinUx.controller import WinUXController
from WinUx.view import WinUXView
from WinUx.ui.hosting.floating_dialog import FloatingDialogController
from WinUx.ui.hosting.host import QDialogLease


class ConfirmationQueueTests(unittest.TestCase):
    def setUp(self):
        self.view = object.__new__(WinUXView)
        self.view._alive = True
        self.jobs = deque()
        self.view.after = lambda delay, callback, *args: self.jobs.append((callback, args))
        self.dialogs = []

        def construct(view, title, message, kind, **kwargs):
            dialog = SimpleNamespace(title=title, complete=kwargs["on_result"],
                                     lift=Mock(), winfo_exists=lambda: True)
            self.dialogs.append(dialog)
            return dialog

        self.factory = patch("WinUx.view._dialog_type", return_value=construct)
        self.factory.start()
        self.addCleanup(self.factory.stop)

    def pump(self):
        while self.jobs:
            callback, args = self.jobs.popleft()
            callback(*args)

    def controller(self):
        controller = object.__new__(WinUXController)
        controller._closing = controller._close_confirmation_pending = False
        controller.view = self.view
        controller.job_schedules = Mock(return_value=[])
        controller._finish_close = Mock()
        return controller

    def test_close_queued_behind_other_confirm_is_not_lost(self):
        delete_result = Mock()
        self.view.confirm_action_async("Delete?", "Delete file?", delete_result)
        app = self.controller()
        app.close()
        app.close()  # repeated X must not enqueue another Exit
        self.assertTrue(app._close_confirmation_pending)
        self.assertEqual(len(self.dialogs), 1)
        self.dialogs[0].complete(False)
        self.pump()
        self.assertEqual([dialog.title for dialog in self.dialogs],
                         ["Delete?", "Confirm Close App"])
        delete_result.assert_called_once_with(False)
        self.dialogs[1].complete(False)
        self.pump()
        self.assertFalse(app._close_confirmation_pending)
        app._finish_close.assert_not_called()
        app.close()
        self.dialogs[2].complete(True)
        self.pump()
        app._finish_close.assert_called_once_with()

    def test_old_completion_cannot_clear_a_new_confirm(self):
        first, second = Mock(), Mock()
        self.view.confirm_action_async("First", "", first)
        self.view.confirm_action_async("Second", "", second)
        self.dialogs[0].complete(False)
        self.pump()
        self.dialogs[0].complete(True)
        self.assertIs(self.view._async_confirm_dialog, self.dialogs[1])
        self.dialogs[1].complete(True)
        self.pump()
        first.assert_called_once_with(False)
        second.assert_called_once_with(True)

    def test_constructor_error_resets_close_pending_and_allows_retry(self):
        app = self.controller()
        with patch("WinUx.view._dialog_type", side_effect=ImportError("broken dialog")):
            with self.assertRaises(ImportError):
                app.close()
        self.assertFalse(app._close_confirmation_pending)
        self.pump()
        app.close()
        self.assertEqual(self.dialogs[-1].title, "Confirm Close App")

    def test_callback_error_does_not_block_next_confirmation(self):
        self.view.confirm_action_async("First", "", Mock(side_effect=ValueError("callback")))
        result = Mock()
        self.view.confirm_action_async("Second", "", result)
        with self.assertRaises(ValueError):
            self.dialogs[0].complete(False)
        self.pump()
        self.assertEqual(self.dialogs[1].title, "Second")

    def test_held_schedule_lock_does_not_block_close_confirmation(self):
        from WinUx.controllers.job_schedule import JobScheduleController
        app = self.controller()
        app._schedule_execution = JobScheduleController(app)
        app.job_schedules = lambda **kwargs: app._schedule_execution.rows(**kwargs)
        # Holding a non-reentrant lock models a scheduler worker mid-update.
        with app._schedule_execution.run_lock:
            started = time.monotonic()
            app.close()
            self.assertLess(time.monotonic() - started, .25)
        self.assertEqual(self.dialogs[0].title, "Confirm Close App")
        app._finish_close.assert_not_called()


class DialogFailureTests(unittest.TestCase):
    def test_error_popup_failure_does_not_spawn_another_error_popup(self):
        dialog = object.__new__(FloatingDialogController)
        dialog._closed = False
        dialog._failure_notice = True
        dialog._reuse_host = True
        dialog.title = "Confirm Close App"
        dialog.view = SimpleNamespace(show_error=Mock(), after=Mock(),
                                      right=SimpleNamespace(status=Mock()))
        dialog._append_failure_log = Mock(return_value=True)
        dialog.destroy = Mock()
        dialog._failed("Cannot start child")
        dialog.destroy.assert_called_once_with()
        self.assertFalse(dialog._reuse_host)
        dialog.view.after.assert_not_called()
        dialog.view.right.status.set.assert_called_once()

    def test_close_before_handshake_wakes_writer_without_error(self):
        dialog = object.__new__(FloatingDialogController)
        dialog._connection_ready = Mock()
        dialog._connection = None
        dialog.view = SimpleNamespace(after=Mock())
        dialog._write_commands()
        dialog.view.after.assert_not_called()

    def test_dead_child_is_detected_without_waiting_full_startup_timeout(self):
        host = SimpleNamespace(listener=Mock(), process=Mock(), log_path="dialog.log")
        host.listener.accept.side_effect = socket.timeout()
        host.process.poll.return_value = 1
        lease = object.__new__(QDialogLease)
        lease.host = host
        lease.from_prewarm = False
        started = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "exited before connecting"):
            lease.open_messages(25)
        self.assertLess(time.monotonic() - started, .25)

    def test_child_import_failure_reports_error_over_ipc_immediately(self):
        from WinUx.services.floating_protocol import encode_message, read_messages
        root = Path(__file__).resolve().parents[1]
        script = root / "WinUx/services/floating_dialog_process.py"
        code = """
import builtins, runpy, sys
original = builtins.__import__
def checked(name, *args, **kwargs):
    if name == 'WinUx.dialogs.floating_runtime':
        raise ImportError('simulated UI import failure')
    return original(name, *args, **kwargs)
builtins.__import__ = checked
runpy.run_path(sys.argv[1], run_name='__main__')
"""
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(10)
            environment = dict(os.environ, WINUX_FLOAT_DIALOG_PORT=str(listener.getsockname()[1]),
                               WINUX_FLOAT_DIALOG_TOKEN="test-token")
            environment.pop("WINUX_FLOAT_DIALOG_PREWARM", None)
            process = subprocess.Popen([sys.executable, "-c", code, str(script)],
                                       cwd=str(root), env=environment,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(5)
                    messages = read_messages(connection)
                    self.assertEqual(next(messages)["event"], "hello")
                    connection.sendall(encode_message({"command": "init", "lease": "test-lease"}))
                    message = next(messages)
                    self.assertEqual(message["event"], "error")
                    self.assertEqual(message["lease"], "test-lease")
                    self.assertIn("simulated UI import failure", message["message"])
                process.communicate(timeout=5)
                self.assertEqual(process.returncode, 1)
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
