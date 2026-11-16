"""Stopped timer callbacks must not retain timers on non-cancellable hosts."""
import gc
from pathlib import Path
import sys
import threading
import unittest
import weakref

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.core import QTimer


class Host:
    def __init__(self):
        self.pending = []

    def after(self, delay, callback, *args):
        self.pending.append((delay, callback, args))

    def fire(self, index=0):
        _, callback, args = self.pending.pop(index)
        callback(*args)
        return callback


class TimerRetentionTests(unittest.TestCase):
    def timer(self, host):
        timer = QTimer(after=host.after)
        self.addCleanup(timer.delete)
        return timer

    def test_stopped_timer_is_collectible_with_callback_still_pending(self):
        host = Host()
        timer = QTimer(after=host.after)
        reference = weakref.ref(timer)
        timer.start(60000)
        timer.stop()
        del timer
        gc.collect()
        self.assertIsNone(reference())
        self.assertEqual(len(host.pending), 1)
        host.fire()
        self.assertFalse(host.pending)

    def test_deleted_timer_and_payload_are_released_before_due_time(self):
        class Payload: pass
        host = Host()
        payload = Payload()
        timer = QTimer.singleShot(60000, lambda captured=payload: captured, after=host.after)
        timer_ref, payload_ref = weakref.ref(timer), weakref.ref(payload)
        timer.delete()
        del timer, payload
        gc.collect()
        self.assertIsNone(timer_ref())
        self.assertIsNone(payload_ref())
        host.fire()

    def test_restart_stale_callback_cannot_consume_new_tick(self):
        host, calls = Host(), []
        timer = self.timer(host)
        timer.timeout.connect(lambda: calls.append(True))
        timer.start(60000)
        old = timer._scheduled_tick
        timer.start(5)
        new = timer._scheduled_tick
        host.fire()
        self.assertFalse(calls)
        self.assertIs(timer._scheduled_tick, new)
        self.assertIsNone(old._timer)
        host.fire()
        self.assertEqual(calls, [True])
        self.assertEqual(len(host.pending), 1)

    def test_active_unowned_single_shot_survives_until_delivery(self):
        host, calls = Host(), []
        timer = QTimer.singleShot(0, lambda: calls.append('once'), after=host.after)
        reference = weakref.ref(timer)
        del timer
        gc.collect()
        self.assertIsNotNone(reference())
        host.fire()
        gc.collect()
        self.assertEqual(calls, ['once'])
        self.assertIsNone(reference())

    def test_duplicate_host_delivery_does_not_create_two_repeating_chains(self):
        host, calls = Host(), []
        timer = self.timer(host)
        timer.timeout.connect(lambda: calls.append(True))
        timer.start(0)
        self.assertEqual(host.pending[0][0], 1)
        callback = host.fire()
        callback()
        self.assertEqual(calls, [True])
        self.assertEqual(len(host.pending), 1)

    def test_wrong_thread_delivery_is_rejected_without_consuming_callback(self):
        host, calls, errors = Host(), [], []
        timer = self.timer(host)
        timer.timeout.connect(lambda: calls.append(True))
        timer.start(5)
        callback = timer._scheduled_tick
        def worker():
            try:
                callback()
            except RuntimeError as error:
                errors.append(error)
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(2)
        self.assertEqual(len(errors), 1)
        self.assertIs(callback._timer, timer)
        self.assertFalse(calls)
        host.fire()
        self.assertEqual(calls, [True])

    def test_restarting_and_stopping_inside_timeout(self):
        host, calls = Host(), []
        timer = self.timer(host)
        def timeout():
            calls.append(True)
            if len(calls) == 1:
                timer.start(12)
            else:
                timer.stop()
        timer.timeout.connect(timeout)
        timer.start(1)
        host.fire()
        self.assertEqual(len(host.pending), 1)
        self.assertEqual(host.pending[0][0], 12)
        host.fire()
        self.assertEqual(len(calls), 2)
        self.assertFalse(timer.isActive())
        self.assertFalse(host.pending)

    def test_schedule_failure_detaches_callback_retained_by_broken_host(self):
        pending = []
        def after(delay, callback, *args):
            pending.append(callback)
            raise RuntimeError('failed after retaining callback')
        timer = QTimer(after=after)
        reference = weakref.ref(timer)
        with self.assertRaises(RuntimeError):
            timer.start(100)
        self.assertFalse(timer.isActive())
        self.assertIsNone(timer._scheduled_tick)
        del timer
        gc.collect()
        self.assertIsNone(reference())
        pending[0]()

    def test_failed_host_cancel_still_detaches_the_stopped_timer(self):
        class BrokenCancelHost(Host):
            def after(self, delay, callback, *args):
                super().after(delay, callback, *args)
                return len(self.pending)
            def after_cancel(self, handle):
                raise RuntimeError('cannot cancel host handle')
        host = BrokenCancelHost()
        timer = QTimer(after=host.after)
        reference = weakref.ref(timer)
        timer.start(60000)
        timer.stop()
        del timer
        gc.collect()
        self.assertIsNone(reference())
        host.fire()

    def test_repeating_timer_still_schedules_after_slot_exception(self):
        host = Host()
        timer = self.timer(host)
        def fail(): raise ValueError('timeout failed')
        timer.timeout.connect(fail)
        timer.start(10)
        with self.assertRaisesRegex(ValueError, 'timeout failed'):
            host.fire()
        self.assertTrue(timer.isActive())
        self.assertEqual(len(host.pending), 1)
        timer.stop()
        host.fire()
        self.assertFalse(timer.isActive())


if __name__ == '__main__':
    unittest.main(verbosity=2)
