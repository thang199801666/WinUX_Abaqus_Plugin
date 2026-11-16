"""Core dispatcher deadlines, lifecycle, native wake hooks and QTimer reuse."""
import gc
from pathlib import Path
import sys
import threading
import unittest
import weakref
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt import QEventDispatcher
from DearUIQt.core import QTimer
from DearUIQt.runtime import StandaloneUiHost


class DispatcherTests(unittest.TestCase):
    def dispatcher(self):
        now = [10.0]
        return QEventDispatcher(clock=lambda: now[0]), now

    def test_deadlines_fifo_and_cancellation(self):
        dispatcher, now = self.dispatcher()
        received = []
        first = dispatcher.after(50, received.append, 1)
        dispatcher.after(50, received.append, 2)
        self.assertAlmostEqual(dispatcher.nextDeadlineMs(), 50)
        self.assertFalse(dispatcher.hasPendingEvents())
        self.assertEqual(dispatcher.processEvents(), 0)
        self.assertTrue(dispatcher.after_cancel(first))
        now[0] += .06
        self.assertTrue(dispatcher.hasPendingEvents())
        self.assertEqual(dispatcher.processEvents(), 1)
        self.assertEqual(received, [2])
        self.assertIsNone(dispatcher.nextDeadlineMs())

    def test_earlier_worker_deadline_wakes_once_outside_lock(self):
        dispatcher, now = self.dispatcher()
        dispatcher.after(1000, lambda: None)
        wakes = []
        dispatcher.setWakeCallback(lambda: wakes.append(dispatcher.pendingCount()))
        def produce():
            dispatcher.after(2000, lambda: None)  # No earlier deadline.
            dispatcher.after(500, lambda: None)
            dispatcher.after(0, lambda: None)     # Same pending native wake.
        worker = threading.Thread(target=produce, daemon=True)
        worker.start()
        worker.join(2)
        self.assertFalse(worker.is_alive(), 'Wake callback ran with scheduler lock held')
        self.assertEqual(len(wakes), 1)
        dispatcher.processEvents()
        # A fresh turn acknowledges the previous wake and allows another one.
        worker = threading.Thread(target=lambda: dispatcher.after(0, lambda: None))
        worker.start()
        worker.join()
        self.assertEqual(len(wakes), 2)

    def test_posting_from_owner_does_not_wake_native_loop(self):
        dispatcher, _ = self.dispatcher()
        wake = Mock()
        dispatcher.setWakeCallback(wake)
        dispatcher.after(0, lambda: None)
        wake.assert_not_called()

    def test_reentrant_posts_and_nested_pump_wait_for_next_turn(self):
        dispatcher, _ = self.dispatcher()
        received = []
        def first():
            received.append(1)
            dispatcher.after(0, received.append, 3)
            self.assertEqual(dispatcher.processEvents(), 0)
        dispatcher.after(0, first)
        dispatcher.after(0, received.append, 2)
        self.assertEqual(dispatcher.processEvents(), 2)
        self.assertEqual(received, [1, 2])
        self.assertEqual(dispatcher.processEvents(), 1)
        self.assertEqual(received, [1, 2, 3])

    def test_earlier_callback_can_cancel_later_due_callback(self):
        dispatcher, _ = self.dispatcher()
        received = []
        tokens = []
        dispatcher.after(0, lambda: dispatcher.after_cancel(tokens[0]))
        tokens.append(dispatcher.after(0, received.append, 'cancelled'))
        self.assertEqual(dispatcher.processEvents(), 1)
        self.assertFalse(received)

    def test_new_immediate_work_is_not_behind_future_intake(self):
        dispatcher, _ = self.dispatcher()
        received = []
        for _ in range(5000):
            dispatcher.after(60000, lambda: None)
        dispatcher.after(0, received.append, 'ready')
        self.assertEqual(dispatcher.processEvents(max_callbacks=1), 1)
        self.assertEqual(received, ['ready'])

    def test_callback_and_time_budgets_leave_ready_work(self):
        dispatcher, now = self.dispatcher()
        def slow():
            now[0] += .02
        for _ in range(10):
            dispatcher.after(0, slow)
        self.assertEqual(dispatcher.processEvents(max_callbacks=0), 0)
        self.assertEqual(dispatcher.processEvents(time_budget_ms=1), 1)
        self.assertTrue(dispatcher.hasPendingEvents())
        self.assertEqual(dispatcher.processEvents(max_callbacks=2, time_budget_ms=None), 2)
        self.assertEqual(dispatcher.pendingCount(), 7)

    def test_callback_errors_do_not_drop_unrelated_work(self):
        dispatcher, _ = self.dispatcher()
        received = []
        def fail():
            raise ValueError('expected')
        dispatcher.after(0, fail)
        dispatcher.after(0, received.append, 2)
        with self.assertRaisesRegex(ValueError, 'expected'):
            dispatcher.processEvents()
        self.assertEqual(received, [2])
        dispatcher.after(0, fail)
        errors = []
        dispatcher.processEvents(on_error=lambda callback, error: errors.append(error))
        self.assertIsInstance(errors[0], ValueError)

    def test_pump_requires_owner_thread(self):
        dispatcher, _ = self.dispatcher()
        errors = []
        def worker():
            try:
                dispatcher.processEvents()
            except RuntimeError as error:
                errors.append(error)
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertEqual(len(errors), 1)

    def test_cancel_reclaims_payloads_and_tombstones_before_pump(self):
        dispatcher, _ = self.dispatcher()
        dispatcher.after(1000, lambda: None)
        class Payload:
            def call(self):
                pass
        payload = Payload()
        ref = weakref.ref(payload)
        for _ in range(5000):
            token = dispatcher.after(60000, payload.call)
            self.assertTrue(dispatcher.after_cancel(token))
        del payload
        gc.collect()
        self.assertIsNone(ref())
        self.assertEqual(dispatcher.pendingCount(), 1)
        self.assertLessEqual(len(dispatcher._deadlines), 64)

    def test_close_during_callback_prevents_later_delivery(self):
        dispatcher, _ = self.dispatcher()
        callback = Mock()
        dispatcher.after(0, dispatcher.close)
        dispatcher.after(0, callback)
        self.assertEqual(dispatcher.processEvents(), 1)
        callback.assert_not_called()
        self.assertTrue(dispatcher.isClosed())
        self.assertEqual(dispatcher.pendingCount(), 0)
        self.assertIsNone(dispatcher.after(0, callback))
        self.assertFalse(dispatcher.setWakeCallback(callback))

    def test_concurrent_cancellation_and_owner_delivery(self):
        dispatcher = QEventDispatcher()
        delivered = []
        callbacks = [dispatcher.after(0, delivered.append, index) for index in range(2000)]
        thread = threading.Thread(target=lambda: [dispatcher.after_cancel(token) for token in callbacks[::2]])
        thread.start()
        while dispatcher.hasPendingEvents():
            dispatcher.processEvents(max_callbacks=32)
        thread.join()
        self.assertEqual(len(delivered), len(set(delivered)))
        self.assertTrue(set(range(1, 2000, 2)).issubset(delivered))

    def test_qtimer_restarts_cancel_old_deadlines_and_stop_on_slot(self):
        host = StandaloneUiHost(backend=object())
        host.dispatcher, now = self.dispatcher()
        timer = QTimer(after=host.after)
        received = []
        timer.timeout.connect(lambda: (received.append('tick'), timer.stop()))
        for _ in range(1000):
            timer.start(10)
        self.assertEqual(host.dispatcher.pendingCount(), 1)
        now[0] += .02
        self.assertEqual(host.pump(), 1)
        self.assertEqual(received, ['tick'])
        self.assertFalse(timer.isActive())
        self.assertIsNone(host.next_deadline_ms())
        timer.delete()
        host.close()

    def test_standalone_error_hook_preserves_legacy_default(self):
        host = StandaloneUiHost(backend=object())
        def fail():
            raise ValueError('expected')
        host.after(0, fail)
        self.assertEqual(host.pump(), 1)  # Legacy default isolates callback errors.
        errors = []
        host.on_callback_error = lambda callback, error: errors.append(error)
        host.after(0, fail)
        host.pump()
        self.assertIsInstance(errors[0], ValueError)
        host.close()
        self.assertFalse(host.winfo_exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
