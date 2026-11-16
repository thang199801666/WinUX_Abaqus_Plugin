import gc
import time
import unittest
import weakref

from DearUIQt.core.dispatcher import QEventDispatcher
from DearUIQt.core.concurrent import QThreadPool
from DearUIQt.runtime import QGuiRuntime


class QtCoreM23Tests(unittest.TestCase):
    def test_dispatcher_reports_ready_to_delivery_queue_wait(self):
        now = [0.0]
        dispatcher = QEventDispatcher(clock=lambda: now[0])
        seen = []
        dispatcher.post(lambda: seen.append('done'))
        now[0] = 0.050
        self.assertEqual(dispatcher.processEvents(None, None), 1)
        self.assertEqual(seen, ['done'])
        snap = dispatcher.callbackDiagnosticsSnapshot()
        self.assertAlmostEqual(snap['queue_wait_ms_p50'], 50.0, places=5)
        self.assertAlmostEqual(snap['queue_wait_ms_p95'], 50.0, places=5)
        self.assertAlmostEqual(snap['last_callback']['queue_wait_ms'], 50.0, places=5)
        compact = dispatcher.compactDiagnosticsSnapshot()
        self.assertAlmostEqual(compact['queue_wait_p95_ms'], 50.0, places=5)

    def test_recent_dispatcher_window_excludes_old_samples(self):
        now = [0.0]
        dispatcher = QEventDispatcher(clock=lambda: now[0])
        dispatcher.post(lambda: None)
        now[0] = 0.100
        dispatcher.processEvents(None, None)
        now[0] = 10.0
        dispatcher.post(lambda: None)
        now[0] = 10.020
        dispatcher.processEvents(None, None)
        recent = dispatcher.recentDiagnosticsSnapshot(1.0)
        self.assertEqual(recent['callback_sample_count'], 1)
        self.assertEqual(recent['turn_sample_count'], 1)
        self.assertAlmostEqual(recent['queue_wait_ms_p95'], 20.0, places=5)

    def test_completed_future_not_retained_by_idle_worker_frame(self):
        pool = QThreadPool(maxThreadCount=1, name='m23-future-cleanup')
        future = pool.start(lambda: 123)
        self.assertTrue(future.waitForFinished(2.0))
        self.assertEqual(future.result(), 123)
        ref = weakref.ref(future)
        del future
        for _ in range(20):
            gc.collect()
            if ref() is None:
                break
            time.sleep(0.01)
        try:
            self.assertIsNone(ref(), 'completed QFuture retained by idle worker frame')
        finally:
            pool.close(wait=True)

    def test_runtime_performance_report_combines_frame_and_dispatcher(self):
        runtime = object.__new__(QGuiRuntime)
        runtime.framePerformanceSnapshot = lambda: {'idle_candidate': True}
        runtime.framePerformanceRegressionSnapshot = lambda: {'threshold_breached': False}
        dispatcher = QEventDispatcher()
        dispatcher.post(lambda: None)
        dispatcher.processEvents(None, None)
        report = QGuiRuntime.performanceReportSnapshot(runtime, dispatcher)
        self.assertTrue(report['frame']['idle_candidate'])
        self.assertIn('turn_p95_ms', report['dispatcher'])
        self.assertIn('queue_wait_ms_p95', report['dispatcher_recent'])


if __name__ == '__main__':
    unittest.main()
