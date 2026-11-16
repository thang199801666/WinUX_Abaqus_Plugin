"""Guarded queued calls and QObject-owned, auto-disposing one-shot timers."""
import gc
from pathlib import Path
import sys
import threading
import unittest
import weakref

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt.core import QObject, QMetaObject, QTimer, Qt, QEventDispatcher
from DearUIQt.widgets import QApplication
from DearUIQt.runtime import StandaloneUiHost


class Target(QObject):
    def __init__(self, after):
        super().__init__(after=after)
        self.calls = []

    def record(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class QueuedLifetimeTests(unittest.TestCase):
    def test_named_and_bound_invocations_do_not_retain_deleted_target(self):
        for bound in (False, True):
            with self.subTest(bound=bound):
                host = StandaloneUiHost(backend=object())
                target = Target(host.after)
                reference = weakref.ref(target)
                self.assertTrue(QMetaObject.invokeMethod(
                    target, target.record if bound else 'record', Qt.QueuedConnection, 12, text='value'))
                target.delete()
                del target
                gc.collect()
                self.assertIsNone(reference())
                self.assertEqual(host.dispatcher.pendingCount(), 1)
                self.assertEqual(host.pump(), 1)
                host.close()

    def test_invocations_without_deleted_target_still_deliver_arguments(self):
        host = StandaloneUiHost(backend=object())
        target = Target(host.after)
        for method in ('record', target.record):
            self.assertTrue(QMetaObject.invokeMethod(target, method, Qt.QueuedConnection, 7, key='x'))
        self.assertFalse(target.calls)
        host.pump()
        self.assertEqual(target.calls, [((7,), {'key': 'x'})] * 2)
        target.delete()
        host.close()

    def test_named_lookup_occurs_at_delivery(self):
        host = StandaloneUiHost(backend=object())
        target = Target(host.after)
        QMetaObject.invokeMethod(target, 'record', Qt.QueuedConnection)
        received = []
        target.record = lambda: received.append('replacement')
        host.pump()
        self.assertEqual(received, ['replacement'])
        target.delete()
        host.close()

    def test_free_function_and_direct_calls_remain_supported(self):
        host = StandaloneUiHost(backend=object())
        target = Target(host.after)
        received = []
        QMetaObject.invokeMethod(target, lambda: received.append('queued'), Qt.QueuedConnection)
        QMetaObject.invokeMethod(target, target.record, Qt.DirectConnection, 'direct')
        self.assertEqual(target.calls, [(('direct',), {})])
        host.pump()
        self.assertEqual(received, ['queued'])
        target.delete()
        host.close()

    def test_worker_posts_but_does_not_execute_on_worker(self):
        host = StandaloneUiHost(backend=object())
        target = Target(host.after)
        thread = threading.Thread(target=lambda: QMetaObject.invokeMethod(
            target, 'record', Qt.QueuedConnection, 'worker request'))
        thread.start()
        thread.join()
        self.assertFalse(target.calls)
        host.pump()
        self.assertEqual(target.calls, [(('worker request',), {})])
        target.delete()
        host.close()


class SingleShotTests(unittest.TestCase):
    def setUp(self):
        self.now = [10.0]
        self.host = StandaloneUiHost(backend=object())
        self.host.dispatcher = QEventDispatcher(clock=lambda: self.now[0])

    def tearDown(self):
        self.host.close()

    def test_zero_shot_is_queued_once_and_deletes_itself(self):
        received = []
        timer = QTimer.singleShot(0, lambda: received.append('once'), after=self.host.after)
        self.assertTrue(timer.isActive())
        self.assertFalse(received)
        self.host.pump()
        self.assertEqual(received, ['once'])
        self.assertTrue(timer._deleted)
        self.assertFalse(timer.isActive())
        self.host.pump()
        self.assertEqual(received, ['once'])

    def test_delayed_shot_and_context_auto_cleanup(self):
        context, received = Target(self.host.after), []
        timer = QTimer.singleShot(50, lambda: received.append('due'), context=context)
        self.assertIn(timer, context.children())
        self.assertEqual(self.host.pump(), 0)
        self.now[0] += .06
        self.host.pump()
        self.assertEqual(received, ['due'])
        self.assertFalse(context.children())
        context.delete()

    def test_bound_method_infers_owner_and_cancels_when_owner_deleted(self):
        target = Target(self.host.after)
        ref = weakref.ref(target)
        timer = QTimer.singleShot(60000, target.record)
        self.assertIs(timer.parent, target)
        target.delete()
        del target
        gc.collect()
        self.assertIsNone(ref())
        self.assertTrue(timer._deleted)
        self.assertEqual(self.host.dispatcher.pendingCount(), 0)

    def test_delete_handle_releases_captured_payload_immediately(self):
        class Payload:
            pass
        payload = Payload()
        ref = weakref.ref(payload)
        callback = lambda captured=payload: captured
        timer = QTimer.singleShot(60000, callback, after=self.host.after)
        del callback, payload
        timer.delete()
        gc.collect()
        self.assertIsNone(ref())
        self.assertEqual(self.host.dispatcher.pendingCount(), 0)

    def test_helper_disposes_even_when_callback_raises(self):
        context = Target(self.host.after)
        errors = []
        self.host.on_callback_error = lambda callback, error: errors.append(error)
        def fail():
            raise ValueError('expected')
        timer = QTimer.singleShot(0, fail, context=context)
        self.host.pump()
        self.assertEqual(len(errors), 1)
        self.assertTrue(timer._deleted)
        self.assertFalse(context.children())
        context.delete()

    def test_no_cancel_scheduler_still_suppresses_deleted_context(self):
        pending = []
        def after(delay, callback, *args):
            pending.append((callback, args))
        target = Target(after)
        ref = weakref.ref(target)
        timer = QTimer.singleShot(60000, target.record)
        target.delete()
        del target
        gc.collect()
        self.assertIsNone(ref())
        callback, args = pending.pop()
        callback(*args)
        self.assertTrue(timer._deleted)

    def test_application_scheduler_fallback(self):
        application = QApplication(after=self.host.after)
        received = []
        try:
            timer = QTimer.singleShot(0, lambda: received.append('app'))
            self.host.pump()
            self.assertEqual(received, ['app'])
            self.assertTrue(timer._deleted)
        finally:
            application.delete()

    def test_schedule_failure_leaves_no_orphan_context_child(self):
        def after(*args):
            raise RuntimeError('schedule failed')
        context = Target(after)
        with self.assertRaisesRegex(RuntimeError, 'schedule failed'):
            QTimer.singleShot(1, lambda: None, context=context)
        self.assertFalse(context.children())
        context.delete()

    def test_validates_interval_callback_context_and_scheduler(self):
        for delay in (-1, 1.5, True):
            with self.assertRaises(ValueError):
                QTimer.singleShot(delay, lambda: None, after=self.host.after)
        with self.assertRaises(TypeError):
            QTimer.singleShot(1, None, after=self.host.after)
        with self.assertRaises(TypeError):
            QTimer.singleShot(1, lambda: None, context=object())
        with self.assertRaises(RuntimeError):
            QTimer.singleShot(1, lambda: None)
        context = Target(self.host.after)
        context.delete()
        with self.assertRaises(RuntimeError):
            QTimer.singleShot(1, lambda: None, context=context)

    def test_context_thread_requirement(self):
        context = Target(self.host.after)
        errors = []
        def worker():
            try:
                QTimer.singleShot(1, lambda: None, context=context)
            except RuntimeError as error:
                errors.append(error)
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertEqual(len(errors), 1)
        self.assertFalse(context.children())
        context.delete()


if __name__ == '__main__':
    unittest.main(verbosity=2)
