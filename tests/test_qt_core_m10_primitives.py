import threading
import time
import unittest

from DearUIQt.core import QCoreApplication, QDeadlineTimer, QElapsedTimer, QEventDispatcher, QEvent, QObject, QTimer
from DearUIQt.runtime import StandaloneUiHost


class QtCoreM10PrimitiveTests(unittest.TestCase):
    def test_elapsed_timer_uses_monotonic_clock_and_restart(self):
        now = [10.0]
        timer = QElapsedTimer(clock=lambda: now[0])
        self.assertFalse(timer.isValid())
        self.assertEqual(timer.elapsed(), 0)
        timer.start()
        now[0] += 0.125
        self.assertEqual(timer.elapsed(), 125)
        self.assertTrue(timer.hasExpired(100))
        self.assertEqual(timer.restart(), 125)
        self.assertEqual(timer.elapsed(), 0)
        timer.invalidate()
        self.assertFalse(timer.isValid())

    def test_deadline_timer_supports_finite_and_forever(self):
        now = [5.0]
        timer = QDeadlineTimer(250, clock=lambda: now[0])
        self.assertFalse(timer.isForever())
        self.assertEqual(timer.remainingTime(), 250)
        now[0] += 0.1
        self.assertEqual(timer.remainingTime(), 150)
        self.assertFalse(timer.hasExpired())
        now[0] += 0.2
        self.assertEqual(timer.remainingTime(), 0)
        self.assertTrue(timer.hasExpired())
        timer.setRemainingTime(QDeadlineTimer.Forever)
        self.assertTrue(timer.isForever())
        self.assertEqual(timer.remainingTime(), QDeadlineTimer.Forever)

    def test_dispatcher_introspection_is_side_effect_free(self):
        now = [1.0]
        dispatcher = QEventDispatcher(clock=lambda: now[0])
        token = dispatcher.after(50, lambda: None)
        snap = dispatcher.diagnosticsSnapshot()
        self.assertEqual(snap['pending_count'], 1)
        self.assertEqual(snap['due_count'], 0)
        self.assertAlmostEqual(snap['next_deadline_ms'], 50.0)
        self.assertEqual(dispatcher.pendingCount(), 1)
        self.assertAlmostEqual(dispatcher.remainingTime(token), 50.0)
        self.assertTrue(dispatcher.isOwnerThread())
        self.assertEqual(dispatcher.ownerThreadId(), threading.get_ident())
        now[0] += 0.1
        self.assertEqual(dispatcher.diagnosticsSnapshot()['due_count'], 1)
        self.assertEqual(dispatcher.remainingTime(token), 0.0)
        self.assertEqual(dispatcher.processEvents(), 1)
        self.assertEqual(dispatcher.remainingTime(token), -1)

    def test_dispatcher_post_never_delivers_inline(self):
        dispatcher = QEventDispatcher()
        seen = []
        dispatcher.post(seen.append, 1)
        self.assertEqual(seen, [])
        dispatcher.processEvents()
        self.assertEqual(seen, [1])

    def test_application_diagnostics_do_not_drain_posted_work(self):
        queue = []
        def after(_delay, callback, *args):
            queue.append((callback, args))
            return len(queue)
        app = QCoreApplication(after=after)
        target = QObject(parent=app)
        app.postEvent(target, QEvent(QEvent.User))
        snapshot = app.diagnosticsSnapshot()
        self.assertEqual(snapshot['posted_event_count'], 1)
        self.assertTrue(snapshot['posted_turn_scheduled'])
        self.assertEqual(len(queue), 1)
        self.assertEqual(app.diagnosticsSnapshot()['posted_event_count'], 1)
        app.delete()

    def test_standalone_host_exposes_canonical_scheduler_diagnostics(self):
        host = StandaloneUiHost(backend=object())
        host.after(1000, lambda: None)
        snapshot = host.scheduler_diagnostics()
        self.assertEqual(snapshot['pending_count'], 1)
        self.assertEqual(snapshot['owner_thread_id'], host.dispatcher.ownerThreadId())
        host.close()

    def test_qtimer_remaining_time_tracks_active_state(self):
        callbacks = []
        def after(delay, callback, *args):
            callbacks.append((delay, callback, args))
            return len(callbacks)
        timer = QTimer(after=after)
        self.assertEqual(timer.remainingTime(), -1)
        timer.start(80)
        remaining = timer.remainingTime()
        self.assertGreaterEqual(remaining, 0)
        self.assertLessEqual(remaining, 80)
        timer.stop()
        self.assertEqual(timer.remainingTime(), -1)
        timer.delete()


if __name__ == '__main__':
    unittest.main(verbosity=2)
