from collections import deque
from pathlib import Path
import socket
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from DearUIQt import QProcess, QSocketNotifier


class Scheduler:
    def __init__(self):
        self.callbacks = deque()
        self.sequence = 0

    def after(self, _delay, callback, *args):
        self.sequence += 1
        self.callbacks.append((self.sequence, callback, args))
        return self.sequence

    def after_cancel(self, token):
        retained = deque(item for item in self.callbacks if item[0] != token)
        changed = len(retained) != len(self.callbacks)
        self.callbacks = retained
        return changed

    def turn(self):
        if not self.callbacks:
            return False
        _token, callback, args = self.callbacks.popleft()
        callback(*args)
        return True


class FakePopen:
    def __init__(self, *_args, **_kwargs):
        self.pid = 12345
        self.stdin = None
        self.stdout = None
        self.stderr = None
        self._poll_values = deque((None, 7))

    def poll(self):
        if len(self._poll_values) > 1:
            return self._poll_values.popleft()
        return self._poll_values[0]

    def wait(self, timeout=None):
        del timeout
        return 7

    def terminate(self):
        self._poll_values = deque((-15,))

    def kill(self):
        self._poll_values = deque((-9,))


class ProcessNotifierTests(unittest.TestCase):
    def test_root_and_qtcore_export_socket_notifier(self):
        from DearUIQt.QtCore import QSocketNotifier as CoreNotifier
        self.assertIs(CoreNotifier, QSocketNotifier)

    def test_qprocess_emits_finished_from_ui_timer_without_manual_poll(self):
        scheduler = Scheduler()
        process = QProcess(after=scheduler.after)
        states = []
        finished = []
        process.stateChanged.connect(states.append)
        process.finished.connect(finished.append)
        with mock.patch('DearUIQt.core.process.subprocess.Popen', FakePopen):
            process.start('fake-program')
        self.assertEqual(process.state(), QProcess.Running)
        self.assertTrue(process.isMonitoring())
        self.assertEqual(states, [QProcess.Starting, QProcess.Running])
        self.assertTrue(scheduler.turn())
        self.assertEqual(process.state(), QProcess.Running)
        self.assertEqual(finished, [])
        self.assertTrue(scheduler.turn())
        self.assertEqual(process.state(), QProcess.NotRunning)
        self.assertEqual(process.exitCode(), 7)
        self.assertEqual(finished, [7])
        self.assertFalse(process.isMonitoring())
        self.assertEqual(states[-1], QProcess.NotRunning)
        process.delete()

    def test_qprocess_polling_interval_updates_active_monitor(self):
        scheduler = Scheduler()
        process = QProcess(after=scheduler.after)
        with mock.patch('DearUIQt.core.process.subprocess.Popen', FakePopen):
            process.start('fake-program')
        process.setPollingInterval(125)
        self.assertEqual(process.pollingInterval(), 125)
        self.assertTrue(process.isMonitoring())
        process.delete()

    def test_socket_notifier_read_activation_stays_on_scheduler(self):
        scheduler = Scheduler()
        left, right = socket.socketpair()
        try:
            notifier = QSocketNotifier(left, QSocketNotifier.Read, after=scheduler.after,
                                       interval=5)
            activated = []
            notifier.activated.connect(activated.append)
            self.assertTrue(notifier.isEnabled())
            self.assertTrue(scheduler.turn())
            self.assertEqual(activated, [])
            right.send(b'x')
            self.assertTrue(scheduler.turn())
            self.assertEqual(activated, [left.fileno()])
            notifier.setEnabled(False)
            self.assertFalse(notifier.isEnabled())
            notifier.delete()
        finally:
            left.close()
            right.close()

    def test_socket_notifier_disables_closed_descriptor(self):
        scheduler = Scheduler()
        left, right = socket.socketpair()
        notifier = QSocketNotifier(left, QSocketNotifier.Read, after=scheduler.after)
        left.close()
        try:
            self.assertTrue(scheduler.turn())
            self.assertFalse(notifier.isEnabled())
        finally:
            notifier.delete()
            right.close()


if __name__ == '__main__':
    unittest.main()
