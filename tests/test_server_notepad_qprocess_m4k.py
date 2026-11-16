from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from WinUx.dialogs.server_notepad_dialog import ServerNotepadDialog


class _MonitoredProcess:
    def __init__(self, running=True):
        self.running = running
        self.poll_calls = 0

    def isMonitoring(self):
        return True

    def isRunning(self):
        return self.running

    def poll(self):
        self.poll_calls += 1
        raise AssertionError('UI path must not poll a monitored QProcess')


class _View:
    def __init__(self):
        self.errors = []

    def after(self, _delay, callback, *args):
        callback(*args)

    def show_error(self, title, message):
        self.errors.append((title, message))


class ServerNotepadQProcessM4kTests(unittest.TestCase):
    def test_monitored_process_uses_cached_qprocess_state_without_poll(self):
        process = _MonitoredProcess(True)
        self.assertTrue(ServerNotepadDialog._process_is_running(process))
        self.assertEqual(process.poll_calls, 0)
        process.running = False
        self.assertFalse(ServerNotepadDialog._process_is_running(process))
        self.assertEqual(process.poll_calls, 0)

    def test_finished_signal_path_marks_facade_closed(self):
        dialog = ServerNotepadDialog.__new__(ServerNotepadDialog)
        dialog.view = _View()
        dialog._closed = threading.Event()
        dialog._startup_watchdog_generation = 0
        dialog._native_input_hwnd = None
        dialog._stderr_path = 'server-notepad.log'
        dialog._process = _MonitoredProcess(False)
        # Avoid importing the native input gate in this focused lifecycle test.
        dialog._unregister_input_surface = lambda: None

        import WinUx.dialogs.server_notepad_dialog as module
        calls = []
        original = module.unregister_child_process
        module.unregister_child_process = lambda process: calls.append(process)
        try:
            dialog._on_process_finished(0)
        finally:
            module.unregister_child_process = original

        self.assertTrue(dialog._closed.is_set())
        self.assertEqual(calls, [dialog._process])
        # A child that exits before the facade sees a normal close is surfaced.
        self.assertEqual(len(dialog.view.errors), 1)


if __name__ == '__main__':
    unittest.main()
