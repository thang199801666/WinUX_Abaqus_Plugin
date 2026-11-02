"""Latest-value delivery remains cancellable until each callback begins."""
import gc
from pathlib import Path
import sys
import threading
import unittest
import weakref
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt import LatestCallQueue, QDebouncer
from DearUIQt.core import QObject, QEventDispatcher
from DearUIQt.runtime import StandaloneUiHost
from DearUIQt.widgets import QWidget
from test_dearuiqt_core_resources import Scheduler, Backend


class UpdateBurstTests(unittest.TestCase):
    def test_discard_invalidates_an_already_selected_batch_entry(self):
        scheduler, received = Scheduler(), []
        queue = LatestCallQueue(scheduler.after)
        queue.post('first', lambda: queue.discard('second'))
        queue.post('second', received.append, 'stale')
        scheduler.flush()
        self.assertFalse(received)

    def test_replacement_of_ready_entry_runs_only_next_turn(self):
        scheduler, received = Scheduler(), []
        queue = LatestCallQueue(scheduler.after)
        queue.post('first', lambda: queue.post('second', received.append, 'new'))
        queue.post('second', received.append, 'old')
        scheduler.turn()
        self.assertFalse(received)
        self.assertEqual(len(scheduler.callbacks), 1)
        scheduler.turn()
        self.assertEqual(received, ['new'])

    def test_close_stops_ready_callbacks_and_releases_payload_in_turn(self):
        scheduler, received = Scheduler(), []
        queue = LatestCallQueue(scheduler.after)
        class Payload:
            def call(self):
                received.append('must not run')
        payload = Payload()
        reference = weakref.ref(payload)
        def close():
            queue.close()
            gc.collect()
            self.assertIsNone(reference())
        queue.post('first', close)
        queue.post('second', payload.call)
        del payload
        scheduler.flush()
        self.assertFalse(received)

    def test_widget_ui_override_during_worker_batch_is_authoritative(self):
        scheduler, backend = Scheduler(), Backend()
        widget = QWidget(1, backend=backend, after=scheduler.after)
        queue = widget._update_queue()
        queue.post('first', lambda: widget.setEnabled(True))
        thread = threading.Thread(target=lambda: widget.setEnabled(False))
        thread.start()
        thread.join()
        scheduler.flush()
        self.assertTrue(widget.isEnabled())
        self.assertFalse(backend.writes)
        widget.delete()

    def test_time_budget_yields_and_preserves_fifo_tail(self):
        scheduler, received = Scheduler(), []
        queue = LatestCallQueue(scheduler.after, time_budget_ms=3)
        now = [0.0]
        def slow(index):
            received.append(index)
            now[0] += .002
        for index in range(10):
            queue.post(index, slow, index)
        with patch('DearUIQt.dispatch.time.perf_counter', side_effect=lambda: now[0]):
            scheduler.turn()
            self.assertEqual(received, [0, 1])
            self.assertEqual(len(scheduler.callbacks), 1)
            scheduler.flush()
        self.assertEqual(received, list(range(10)))

    def test_payload_finalizer_can_reenter_queue_on_discard(self):
        scheduler, received = Scheduler(), []
        queue = LatestCallQueue(scheduler.after)
        class Payload:
            def call(self):
                pass
            def __del__(self):
                queue.post('finalizer', received.append, 'released')
        payload = Payload()
        queue.post('old', payload.call)
        del payload
        thread = threading.Thread(target=lambda: queue.discard('old'), daemon=True)
        thread.start()
        thread.join(2)
        self.assertFalse(thread.is_alive(), 'Payload was released with queue lock held')
        scheduler.flush()
        self.assertEqual(received, ['released'])

    def test_payload_finalizers_can_reenter_on_replace_and_close(self):
        for operation in ('replace', 'close'):
            with self.subTest(operation=operation):
                scheduler, received, released = Scheduler(), [], []
                queue = LatestCallQueue(scheduler.after)
                class Payload:
                    def call(self):
                        pass
                    def __del__(self):
                        released.append(queue.post('finalizer', received.append, 'released'))
                payload = Payload()
                queue.post('value', payload.call)
                del payload
                action = (lambda: queue.post('value', received.append, 'replacement')) \
                    if operation == 'replace' else queue.close
                thread = threading.Thread(target=action, daemon=True)
                thread.start()
                thread.join(2)
                self.assertFalse(thread.is_alive(), 'Finalizer reentered a locked queue')
                scheduler.flush()
                self.assertEqual(released, [operation == 'replace'])
                self.assertEqual(received, ['replacement', 'released'] if operation == 'replace' else [])


class DebouncerTests(unittest.TestCase):
    def setUp(self):
        self.now = [10.0]
        self.host = StandaloneUiHost(backend=object())
        self.host.dispatcher = QEventDispatcher(clock=lambda: self.now[0])
        self.context = QObject(after=self.host.after)

    def tearDown(self):
        self.context.delete()
        self.host.close()

    def test_latest_arguments_after_quiet_period(self):
        received = []
        debounce = QDebouncer(lambda *a, **k: received.append((a, k)), 100, self.context)
        debounce.trigger('old')
        self.now[0] += .05
        debounce.trigger('latest', option=2)
        self.now[0] += .06
        self.assertEqual(self.host.pump(), 0)
        self.assertTrue(debounce.isPending())
        self.now[0] += .06
        self.host.pump()
        self.assertEqual(received, [(('latest',), {'option': 2})])
        self.assertFalse(debounce.isPending())

    def test_burst_reuses_one_timer_and_one_live_deadline(self):
        received = []
        debounce = QDebouncer(received.append, 100, self.context)
        timer = debounce._timer
        for index in range(2000):
            debounce.trigger(index)
        self.assertIs(debounce._timer, timer)
        self.assertEqual(len(debounce.children()), 1)
        self.assertEqual(self.host.dispatcher.pendingCount(), 1)
        self.now[0] += .2
        self.host.pump()
        self.assertEqual(received, [1999])

    def test_cancel_and_flush_are_idempotent(self):
        received = []
        debounce = QDebouncer(received.append, 100, self.context)
        self.assertFalse(debounce.cancel())
        self.assertFalse(debounce.flush())
        debounce.trigger('cancel')
        self.assertTrue(debounce.cancel())
        self.assertEqual(self.host.dispatcher.pendingCount(), 0)
        debounce.trigger('flush')
        self.assertTrue(debounce.flush())
        self.assertEqual(received, ['flush'])
        self.assertFalse(debounce.flush())
        self.now[0] += 1
        self.host.pump()
        self.assertEqual(received, ['flush'])

    def test_callback_can_retrigger_without_losing_new_work(self):
        received = []
        def callback(value):
            received.append(value)
            if value == 1:
                debounce.trigger(2)
        debounce = QDebouncer(callback, 0, self.context)
        debounce.trigger(1)
        self.host.pump()
        self.assertEqual(received, [1])
        self.assertTrue(debounce.isPending())
        self.host.pump()
        self.assertEqual(received, [1, 2])

    def test_cancel_releases_arguments_and_context_delete_releases_callback(self):
        class Payload:
            pass
        payload = Payload()
        reference = weakref.ref(payload)
        debounce = QDebouncer(lambda value: None, 100, self.context)
        debounce.trigger(payload)
        del payload
        debounce.cancel()
        gc.collect()
        self.assertIsNone(reference())
        self.context.delete()
        self.assertTrue(debounce._deleted)
        self.assertIsNone(debounce._callback)
        self.assertEqual(self.host.dispatcher.pendingCount(), 0)

    def test_bound_callback_infers_parent(self):
        class Receiver(QObject):
            def consume(self, value):
                pass
        receiver = Receiver(after=self.host.after)
        reference = weakref.ref(receiver)
        debounce = QDebouncer(receiver.consume)
        self.assertIs(debounce.parent, receiver)
        debounce.trigger('data')
        receiver.delete()
        del receiver
        gc.collect()
        self.assertIsNone(reference())
        self.assertTrue(debounce._deleted)

    def test_bound_receiver_delete_also_cancels_with_a_different_parent(self):
        class Receiver(QObject):
            def consume(self, value):
                raise AssertionError('Deleted callback target was invoked')
        receiver = Receiver(after=self.host.after)
        debounce = QDebouncer(receiver.consume, parent=self.context)
        debounce.trigger('pending')
        receiver.delete()
        self.assertTrue(debounce._deleted)
        self.assertEqual(self.host.dispatcher.pendingCount(), 0)

    def test_schedule_failure_leaves_no_pending_payload(self):
        def fail(*args):
            raise RuntimeError('schedule failed')
        debounce = QDebouncer(lambda: None, after=fail)
        try:
            with self.assertRaisesRegex(RuntimeError, 'schedule failed'):
                debounce.trigger()
            self.assertFalse(debounce.isPending())
            self.assertFalse(debounce._timer.isActive())
        finally:
            debounce.delete()

    def test_change_interval_and_recover_after_callback_error(self):
        calls, errors = [], []
        def callback():
            calls.append('called')
            if len(calls) == 1:
                raise ValueError('expected')
        debounce = QDebouncer(callback, 100, self.context)
        self.host.on_callback_error = lambda callback, error: errors.append(error)
        debounce.trigger()
        debounce.setInterval(10)
        self.now[0] += .02
        self.host.pump()
        self.assertEqual(len(errors), 1)
        self.assertFalse(debounce.isPending())
        debounce.trigger()
        self.now[0] += .02
        self.host.pump()
        self.assertEqual(calls, ['called', 'called'])

    def test_worker_trigger_is_rejected_without_pending_state(self):
        debounce = QDebouncer(lambda: None, parent=self.context)
        errors = []
        def worker():
            try:
                debounce.trigger()
            except RuntimeError as error:
                errors.append(error)
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertEqual(len(errors), 1)
        self.assertFalse(debounce.isPending())
        self.assertEqual(self.host.dispatcher.pendingCount(), 0)

    def test_validates_callback_interval_parent_and_scheduler(self):
        for interval in (-1, 1.5, True):
            with self.assertRaises(ValueError):
                QDebouncer(lambda: None, interval, self.context)
        with self.assertRaises(TypeError):
            QDebouncer(None, parent=self.context)
        with self.assertRaises(TypeError):
            QDebouncer(lambda: None, parent=object())
        with self.assertRaises(RuntimeError):
            QDebouncer(lambda: None)
        self.assertFalse(self.context.children())


if __name__ == '__main__':
    unittest.main(verbosity=2)
