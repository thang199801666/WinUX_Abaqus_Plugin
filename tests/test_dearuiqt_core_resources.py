"""DearUIQt resource/dispatch policies without constructing a WinUx application."""
from collections import deque
import gc
from pathlib import Path
import sys
import threading
import unittest
import weakref

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt.dispatch import LatestCallQueue
from DearUIQt.widgets.widget import QWidget
from DearUIQt.widgets.retained import QRetainedItem
from DearUIQt.core.object import QEvent
from DearUIQt.core.application import QApplication


class Scheduler:
    def __init__(self):
        self.callbacks = deque()
        self.lock = threading.Lock()
        self.wakes = 0

    def after(self, delay, callback, *args):
        with self.lock:
            self.callbacks.append((callback, args))
            self.wakes += 1

    def turn(self):
        with self.lock:
            callback, args = self.callbacks.popleft()
        callback(*args)

    def flush(self):
        while self.callbacks:
            self.turn()


class Backend:
    def __init__(self):
        self.alive = True
        self.writes = []
        self.owner = threading.get_ident()

    def does_item_exist(self, tag):
        return self.alive

    def configure_item(self, tag, **values):
        assert threading.get_ident() == self.owner
        self.writes.append((tag, values))

    def delete_item(self, tag):
        self.alive = False


class CoreResourceTests(unittest.TestCase):
    def test_ui_only_widget_does_not_allocate_worker_queue(self):
        scheduler, backend = Scheduler(), Backend()
        widget = QWidget(1, after=scheduler.after, backend=backend)
        widget.setEnabled(False)
        widget.setEnabled(True)
        self.assertIsNone(widget._updates)
        self.assertEqual(len(backend.writes), 2)
        self.assertEqual(scheduler.wakes, 0)
        widget.delete()

    def test_application_native_batching_still_uses_one_turn(self):
        scheduler, backend = Scheduler(), Backend()
        application = QApplication(after=scheduler.after)
        widget = QWidget(1, after=scheduler.after, backend=backend)
        try:
            widget.setEnabled(False)
            widget.setEnabled(True)
            self.assertFalse(backend.writes)
            self.assertEqual(scheduler.wakes, 1)
            self.assertIsNone(widget._updates)
            scheduler.flush()
            self.assertEqual(backend.writes, [(1, {'enabled': True})])
            received = []
            widget.changeEvent = lambda event: received.append(event.type())
            for _ in range(10):
                widget.updateGeometry()
            self.assertIsNone(widget._updates)
            scheduler.flush()
            self.assertEqual(received, [QEvent.LayoutRequest])
        finally:
            widget.delete()
            application.delete()

    def test_many_worker_writes_keep_latest_and_one_wake(self):
        scheduler, backend = Scheduler(), Backend()
        widget = QWidget(1, after=scheduler.after, backend=backend)
        def producer():
            for index in range(1000):
                widget._on_ui('label', widget._configure, 'label', str(index))
        worker = threading.Thread(target=producer)
        worker.start()
        worker.join()
        self.assertIsNotNone(widget._updates)
        self.assertEqual(scheduler.wakes, 1)
        self.assertFalse(backend.writes)
        scheduler.flush()
        self.assertEqual(backend.writes, [(1, {'label': '999'})])
        widget.delete()

    def test_simultaneous_first_use_has_one_shared_queue(self):
        scheduler, backend = Scheduler(), Backend()
        widget = QWidget(1, after=scheduler.after, backend=backend)
        barrier = threading.Barrier(8)
        queues = []
        def producer(index):
            barrier.wait()
            for offset in range(20):
                value = '{}:{}'.format(index, offset)
                widget._on_ui(value, widget._configure, 'label', value)
            queues.append(widget._updates)
        workers = [threading.Thread(target=producer, args=(i,)) for i in range(8)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertTrue(all(queue is widget._updates for queue in queues))
        self.assertEqual(scheduler.wakes, 1)
        scheduler.flush()
        self.assertEqual(len(backend.writes), 160)
        widget.delete()

    def test_ui_write_discards_older_worker_value(self):
        scheduler, backend = Scheduler(), Backend()
        widget = QWidget(1, after=scheduler.after, backend=backend)
        worker = threading.Thread(target=lambda: widget.setEnabled(False))
        worker.start()
        worker.join()
        widget.setEnabled(True)
        scheduler.flush()
        self.assertTrue(widget.isEnabled())
        self.assertFalse(backend.writes)
        widget.delete()

    def test_delete_before_first_worker_use_cannot_recreate_live_queue(self):
        scheduler, backend = Scheduler(), Backend()
        widget = QWidget(1, after=scheduler.after, backend=backend)
        widget.delete()
        worker = threading.Thread(target=lambda: widget._on_ui('label', widget._configure, 'label', 'late'))
        worker.start()
        worker.join()
        self.assertEqual(scheduler.wakes, 0)
        self.assertFalse(widget._update_queue().post('late', lambda: None))

    def test_delete_drops_pending_worker_writes(self):
        scheduler, backend = Scheduler(), Backend()
        widget = QWidget(1, after=scheduler.after, backend=backend)
        worker = threading.Thread(target=lambda: widget.setEnabled(False))
        worker.start()
        worker.join()
        widget.delete()
        scheduler.flush()
        self.assertFalse(backend.writes)

    def test_nonowning_adapter_closes_queue_without_deleting_native_item(self):
        scheduler, backend = Scheduler(), Backend()
        widget = QRetainedItem(1, after=scheduler.after, backend=backend, owns_native=False)
        queue = widget._update_queue()
        widget.delete()
        self.assertTrue(backend.alive)
        self.assertFalse(queue.post('late', lambda: None))

    def test_layout_fallback_still_posts_and_compresses(self):
        scheduler, backend = Scheduler(), Backend()
        widget = QWidget(1, after=scheduler.after, backend=backend)
        received = []
        widget.changeEvent = lambda event: received.append(event.type())
        for _ in range(10):
            widget.updateGeometry()
        self.assertEqual(scheduler.wakes, 1)
        scheduler.flush()
        self.assertEqual(received, [QEvent.LayoutRequest])
        widget.delete()

    def test_fifo_bounded_batches_and_reentrant_posts(self):
        scheduler, received = Scheduler(), []
        queue = LatestCallQueue(scheduler.after, max_batch=2)
        def first(value):
            received.append(value)
            queue.post('fourth', received.append, 4)
        queue.post('first', first, 1)
        queue.post('second', received.append, 2)
        queue.post('second', received.append, 20)
        queue.post('third', received.append, 3)
        scheduler.turn()
        self.assertEqual(received, [1, 20])
        self.assertEqual(len(scheduler.callbacks), 1)
        scheduler.flush()
        self.assertEqual(received, [1, 20, 3, 4])

    def test_error_still_drains_ready_batch_and_schedules_tail(self):
        scheduler, received = Scheduler(), []
        queue = LatestCallQueue(scheduler.after, max_batch=2)
        def fail():
            raise ValueError('expected')
        queue.post(1, fail)
        queue.post(2, received.append, 2)
        queue.post(3, received.append, 3)
        with self.assertRaises(ValueError):
            scheduler.turn()
        scheduler.flush()
        self.assertEqual(received, [2, 3])

    def test_close_releases_payload_before_scheduled_turn(self):
        scheduler = Scheduler()
        queue = LatestCallQueue(scheduler.after)
        class Payload:
            def call(self):
                pass
        payload = Payload()
        reference = weakref.ref(payload)
        queue.post('payload', payload.call)
        del payload
        queue.close()
        gc.collect()
        self.assertIsNone(reference())
        scheduler.flush()


if __name__ == '__main__':
    unittest.main(verbosity=2)
