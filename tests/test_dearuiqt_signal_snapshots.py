"""Immutable signal connection snapshots: dispatch, lifetime and worker emits."""
import gc
from pathlib import Path
import sys
import threading
import unittest
import weakref

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.core import QObject, Signal, Qt


class SignalSnapshotTests(unittest.TestCase):
    def test_empty_storage_is_shared_and_stable_emit_reuses_snapshot(self):
        signal, other = Signal(), Signal()
        empty = signal._slots
        self.assertIs(empty, other._slots)
        values = []
        connection = signal.connect(values.append)
        self.assertIs(signal.connect(values.append), connection)
        snapshot = signal._slots
        signal.emit(1)
        signal.emit(2)
        self.assertIs(signal._slots, snapshot)
        self.assertEqual(values, [1, 2])
        connection.disconnect()
        connection.disconnect()
        self.assertIs(signal._slots, empty)

    def test_new_connection_waits_for_next_emit(self):
        signal, calls = Signal(), []
        def third(): calls.append('third')
        def first():
            calls.append('first')
            signal.connect(third)
        signal.connect(first)
        signal.connect(lambda: calls.append('second'))
        signal.emit()
        self.assertEqual(calls, ['first', 'second'])
        calls.clear()
        signal.emit()
        self.assertEqual(calls, ['first', 'second', 'third'])

    def test_disconnecting_next_and_self_during_emit(self):
        signal, calls = Signal(), []
        def first():
            calls.append('first')
            second.disconnect()
            first_connection.disconnect()
        first_connection = signal.connect(first)
        second = signal.connect(lambda: calls.append('second'))
        signal.connect(lambda: calls.append('third'))
        signal.emit()
        signal.emit()
        self.assertEqual(calls, ['first', 'third', 'third'])

    def test_nested_emit_observes_new_snapshot(self):
        signal, calls = Signal(), []
        def late(value): calls.append(('late', value))
        def first(value):
            calls.append(('first', value))
            if value == 'outer':
                signal.connect(late)
                signal.emit('inner')
        signal.connect(first)
        signal.emit('outer')
        self.assertEqual(calls, [('first', 'outer'), ('first', 'inner'), ('late', 'inner')])

    def test_worker_auto_queue_and_disconnected_pending_delivery(self):
        pending, values = [], []
        receiver = QObject(after=lambda delay, callback, *args: pending.append((callback, args)))
        self.addCleanup(receiver.delete)
        signal = Signal()
        connection = signal.connect(lambda value: values.append((value, threading.get_ident())), receiver=receiver)
        worker = threading.Thread(target=lambda: signal.emit(4))
        worker.start()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertFalse(values)
        self.assertEqual(len(pending), 1)
        callback, args = pending.pop()
        callback(*args)
        self.assertEqual(values, [(4, threading.get_ident())])
        worker = threading.Thread(target=lambda: signal.emit(5))
        worker.start()
        worker.join(2)
        connection.disconnect()
        callback, args = pending.pop()
        callback(*args)
        self.assertEqual(len(values), 1)

    def test_worker_emit_snapshot_survives_ui_connection_mutation(self):
        signal, calls = Signal(), []
        entered, resume = threading.Event(), threading.Event()
        def first():
            entered.set()
            if not resume.wait(2):
                raise RuntimeError('test did not resume emitter')
        signal.connect(first)
        second = signal.connect(lambda: calls.append('old'))
        errors = []
        def emit():
            try:
                signal.emit()
            except Exception as error:
                errors.append(error)
        worker = threading.Thread(target=emit)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            second.disconnect()
            signal.connect(lambda: calls.append('new'))
        finally:
            resume.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertFalse(errors)
        self.assertFalse(calls)
        signal.emit()
        self.assertEqual(calls, ['new'])

    def test_owner_blocking_deletion_and_slot_failure_are_preserved(self):
        owner, calls = QObject(), []
        self.addCleanup(owner.delete)
        owner.changed = Signal(owner)
        owner.changed.connect(lambda: calls.append(True))
        owner.blockSignals(True)
        owner.changed.emit()
        self.assertFalse(calls)
        owner.blockSignals(False)
        owner.changed.emit()
        self.assertEqual(calls, [True])
        owner.delete()
        owner.changed.emit()
        self.assertEqual(calls, [True])
        signal = Signal()
        def fail(): raise ValueError('slot failed')
        signal.connect(fail)
        signal.connect(lambda: calls.append(False))
        with self.assertRaisesRegex(ValueError, 'slot failed'):
            signal.emit()
        self.assertEqual(calls, [True])

    def test_disconnect_releases_callable_even_if_connection_is_retained(self):
        class Callable:
            def __call__(self): pass
        signal = Signal()
        slot = Callable()
        reference = weakref.ref(slot)
        connection = signal.connect(slot)
        snapshot = signal._slots
        del slot
        connection.disconnect()
        gc.collect()
        self.assertIsNone(reference())
        self.assertFalse(snapshot[0].active)
        self.assertIsNone(connection.slot)

    def test_bulk_disconnect_preserves_connections_added_by_slot_finalizers(self):
        signal, calls = Signal(), []
        def new_slot(): calls.append('new')
        class Slot:
            def __call__(self): calls.append('old')
            def __del__(self): signal.connect(new_slot)
        first = signal.connect(Slot())
        second = signal.connect(lambda: calls.append('second'))
        signal.disconnect()
        self.assertFalse(first.active)
        self.assertFalse(second.active)
        signal.emit()
        self.assertEqual(calls, ['new'])

    def test_concurrent_connection_publication_and_removal_do_not_lose_slots(self):
        signal, calls, connections, errors = Signal(), [], [], []
        barrier = threading.Barrier(8)
        def connect_batch(worker):
            try:
                barrier.wait(2)
                for index in range(40):
                    key = worker * 40 + index
                    connections.append(signal.connect(lambda key=key: calls.append(key)))
            except Exception as error:
                errors.append(error)
        workers = [threading.Thread(target=connect_batch, args=(i,)) for i in range(8)]
        for worker in workers: worker.start()
        for worker in workers: worker.join(5)
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertFalse(errors)
        self.assertEqual(len(signal._slots), 320)
        signal.emit()
        self.assertEqual(sorted(calls), list(range(320)))
        def disconnect_batch(batch):
            for connection in batch:
                connection.disconnect()
        workers = [threading.Thread(target=disconnect_batch, args=(connections[i::8],)) for i in range(8)]
        for worker in workers: worker.start()
        for worker in workers: worker.join(5)
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertFalse(signal._slots)
        self.assertTrue(all(not connection.active for connection in connections))


if __name__ == '__main__':
    unittest.main(verbosity=2)
