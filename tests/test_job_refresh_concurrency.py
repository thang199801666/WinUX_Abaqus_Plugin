import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from WinUx.controllers.job_polling import JobPollingController


def fixture():
    callbacks, workers = [], []
    app = SimpleNamespace(_closing=False, _connection_generation=1,
        server=SimpleNamespace(connected=True, list_jobs=Mock(return_value=[])),
        view=SimpleNamespace(after=lambda delay, cb, *args: callbacks.append((cb, args)),
            winfo_exists=lambda: True, show_error=Mock()),
        _apply_job_update=Mock())
    def submit(name, worker, **kwargs):
        workers.append(worker)
        return SimpleNamespace(state='queued')
    app._submit_background = Mock(side_effect=submit)
    return app, JobPollingController(app), callbacks, workers


def drain(callbacks):
    while callbacks:
        cb, args = callbacks.pop(0)
        cb(*args)


class JobRefreshConcurrencyTests(unittest.TestCase):
    def test_refresh_burst_during_query_becomes_one_immediate_follow_up(self):
        app, polling, callbacks, workers = fixture()
        entered, release, follow_up = threading.Event(), threading.Event(), threading.Event()
        threads = []
        real_thread = threading.Thread
        def thread(**kwargs):
            value = real_thread(**kwargs)
            threads.append(value)
            return value
        def query():
            if app.server.list_jobs.call_count == 1:
                entered.set()
                release.wait(2)
            else:
                follow_up.set()
            return []
        app.server.list_jobs.side_effect = query
        settings = dict(qstat_min_interval=5, qstat_max_interval=30,
            qstat_stable_samples_to_max=4, qstat_quiet_seconds_to_max=40)
        try:
            with patch('WinUx.controllers.job_polling.PerformancePreferences') as preferences, \
                 patch('WinUx.controllers.job_polling.threading.Thread', side_effect=thread):
                preferences.return_value.load.return_value = settings
                polling.start()
                self.assertTrue(entered.wait(2), 'first qstat did not start')
                for _ in range(1000):
                    polling.refresh_now()
                release.set()
                self.assertTrue(follow_up.wait(2), 'refresh was deferred to the normal 5-second timer')
        finally:
            release.set()
            polling.stop()
            for value in threads:
                value.join(2)
                self.assertFalse(value.is_alive())
        self.assertEqual(app.server.list_jobs.call_count, 2)
        self.assertEqual(workers, [])

    def test_queued_fallback_cannot_query_replacement_session(self):
        app, polling, callbacks, workers = fixture()
        polling.refresh_now()
        app._connection_generation += 1
        workers[0]()
        drain(callbacks)
        app.server.list_jobs.assert_not_called()
        app.view.show_error.assert_not_called()

    def test_queued_fallback_joins_poller_that_started_while_waiting(self):
        app, polling, callbacks, workers = fixture()
        polling.refresh_now()
        app._job_poll_cancel = threading.Event()
        app._job_poll_force_fast = threading.Event()
        app._job_poll_wakeup = threading.Event()
        workers[0]()
        app.server.list_jobs.assert_not_called()
        self.assertTrue(app._job_poll_force_fast.is_set())
        self.assertTrue(app._job_poll_wakeup.is_set())

    def test_rejected_fallback_reports_instead_of_silently_losing_refresh(self):
        app, polling, callbacks, workers = fixture()
        app._submit_background = Mock(return_value=SimpleNamespace(state='rejected'))
        polling.refresh_now()
        drain(callbacks)
        app.server.list_jobs.assert_not_called()
        self.assertIn('queue is full', app.view.show_error.call_args.args[-1])

    def test_fallback_coalescing_is_connection_scoped(self):
        app, polling, callbacks, workers = fixture()
        polling.refresh_now()
        self.assertEqual(app._submit_background.call_args.kwargs['key'], ('job-refresh', 1))
        app._connection_generation += 1
        polling.refresh_now()
        self.assertEqual(app._submit_background.call_args.kwargs['key'], ('job-refresh', 2))
        self.assertTrue(app._submit_background.call_args.kwargs['coalesce'])


if __name__ == '__main__':
    unittest.main()
