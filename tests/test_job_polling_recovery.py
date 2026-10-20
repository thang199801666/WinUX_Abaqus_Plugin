"""Recover Job Viewer polling after scheduler mutations and delayed qstat."""
from datetime import datetime
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock, patch

from WinUx.controller import WinUXController
from WinUx.controllers.job_polling import JobPollingController
from WinUx.controllers.job_schedule import JobScheduleController
from WinUx.controllers.job_submission import JobSubmissionController


def fixture():
    callbacks, workers = [], []
    app = SimpleNamespace(
        _closing=False, _connection_generation=1, _job_edit_settings={},
        server=SimpleNamespace(connected=True, username="owner", cancel_job=Mock(),
                               submit_abaqus_job=Mock(return_value="123.server"), list_jobs=Mock()),
        view=SimpleNamespace(after=lambda delay, callback, *args: callbacks.append((callback, args)),
                             winfo_exists=lambda: True, show_error=Mock(),
                             right=SimpleNamespace(status=SimpleNamespace(set=Mock()))),
        _refresh_jobs_now=Mock(), _apply_job_update=Mock(),
        _remove_shared_schedule=Mock(), _save_shared_schedule=Mock())
    app._submit_background = Mock(side_effect=lambda name, worker, **kwargs:
                                  workers.append(worker) or SimpleNamespace(state="queued"))
    return app, callbacks, workers


def drain(callbacks):
    while callbacks:
        callback, args = callbacks.pop(0)
        callback(*args)


class JobPollingRecoveryTests(unittest.TestCase):
    def test_refresh_and_observed_job_removal_keep_follow_up_polls_fast(self):
        app, _, _ = fixture()
        polling = JobPollingController(app)
        now, delays = [0.0], []
        cancel, force = threading.Event(), threading.Event()
        wakeup = Mock()
        wakeup.is_set.return_value = False

        def wait(delay):
            delays.append(delay)
            if len(delays) == 1:
                # An operation wakes a poller that had been idle for a while.
                now[0] += 60
                polling.refresh_now()
            else:
                now[0] += delay
            if len(delays) == 12:
                cancel.set()

        wakeup.wait.side_effect = wait
        running = SimpleNamespace(job_id="123", name="Job", user="owner", tokens="4", status="R")

        def list_jobs():
            now[0] += 2  # Normally enough query cost to impose an 18s delay.
            return [running] if app.server.list_jobs.call_count < 4 else []

        app.server.list_jobs.side_effect = list_jobs
        settings = dict(qstat_min_interval=5, qstat_max_interval=30,
                        qstat_stable_samples_to_max=4, qstat_quiet_seconds_to_max=40)
        with patch("WinUx.controllers.job_polling.PerformancePreferences") as preferences, \
                patch("WinUx.controllers.job_polling.threading.Event", side_effect=[cancel, wakeup, force]), \
                patch("WinUx.controllers.job_polling.threading.Thread") as thread, \
                patch("WinUx.controllers.job_polling.time.monotonic", side_effect=lambda: now[0]):
            preferences.return_value.load.return_value = settings
            thread.side_effect = lambda **kwargs: SimpleNamespace(start=kwargs["target"])
            polling.start()
        self.assertEqual(delays[1:5], [5] * 4)
        self.assertGreater(delays[5], 5, "Observed removal must not restart the whole recovery window")
        self.assertGreater(delays[-1], 5, "Quiet polling must recover its server-load budget")
        app._submit_background.assert_not_called()

    def test_recovery_window_allows_at_least_three_minimum_interval_checks(self):
        self.assertEqual(JobPollingController.recovery_window({"qstat_min_interval": 5}), 30)
        self.assertEqual(JobPollingController.recovery_window({"qstat_min_interval": 20}), 60)

    def test_scheduled_run_refreshes_viewer_as_soon_as_submit_returns(self):
        app, callbacks, _ = fixture()
        scheduler = JobScheduleController(app)
        task = dict(key="run", job={"path": "/job.inp"}, mode="Run At",
                    target=datetime.now(), job_name="Job", cancel=threading.Event())
        scheduler.run_tasks[task["key"]] = task
        scheduler.execute_run(task)
        drain(callbacks)
        app.server.submit_abaqus_job.assert_called_once_with(path="/job.inp")
        app._refresh_jobs_now.assert_called_once_with()
        self.assertFalse(scheduler.run_tasks)

    def test_scheduled_cancel_uses_shared_poller_until_job_disappears(self):
        app, callbacks, _ = fixture()
        scheduler = JobScheduleController(app)
        task = dict(job_id="123", job_name="Job", mode="Delete At Time",
                    target=datetime.now(), cancel=threading.Event())
        scheduler.delete_tasks["123"] = task
        scheduler.execute_delete(task)
        drain(callbacks)
        app.server.cancel_job.assert_called_once_with("123")
        app._refresh_jobs_now.assert_called_once_with()
        scheduler.execute_delete(task)
        drain(callbacks)
        app.server.cancel_job.assert_called_once_with("123")
        app.server.list_jobs.assert_not_called()
        self.assertEqual(app._refresh_jobs_now.call_count, 1)
        scheduler.reconcile_deletions([])
        self.assertNotIn("123", scheduler.delete_tasks)
        self.assertTrue(task["cancel"].is_set())

    def test_submission_batch_refreshes_already_submitted_jobs_before_last_job(self):
        app, callbacks, workers = fixture()
        scheduler = SimpleNamespace(schedule_run=Mock(return_value=False))
        app._schedule_execution_controller = lambda: scheduler

        def submit(**kwargs):
            if app.server.submit_abaqus_job.call_count == 2:
                drain(callbacks)
                app._refresh_jobs_now.assert_called_once_with()
            return "123.server"

        app.server.submit_abaqus_job.side_effect = submit
        dialog = Mock()
        JobSubmissionController(app)._submit_jobs(dialog, [{"path": "/one.inp"}, {"path": "/two.inp"}])
        workers[0]()
        drain(callbacks)
        self.assertEqual(app._refresh_jobs_now.call_count, 3)
        dialog.submission_finished.assert_called_once_with(2, 0)

    def test_console_commands_and_interrupt_refresh_job_viewer(self):
        app, _, _ = fixture()
        app._ensure_server_online = lambda: True
        app.server.invalidate_shell_directory = Mock()
        app.server.send_shell_command = Mock()
        app.server.interrupt_shell = Mock()
        self.assertTrue(WinUXController.console_command(app, "./submit-script.sh"))
        app._refresh_jobs_now.assert_called_once_with()
        self.assertTrue(WinUXController.console_interrupt(app))
        self.assertEqual(app._refresh_jobs_now.call_count, 2)

    def test_failed_console_command_does_not_trigger_recovery(self):
        app, _, _ = fixture()
        app._ensure_server_online = lambda: True
        app.server.invalidate_shell_directory = Mock()
        app.server.send_shell_command = Mock(side_effect=RuntimeError("Connection lost"))
        self.assertFalse(WinUXController.console_command(app, "qdel 123"))
        app._refresh_jobs_now.assert_not_called()

    def test_read_only_console_commands_do_not_reset_job_polling(self):
        app, _, _ = fixture()
        app._ensure_server_online = lambda: True
        app.server.invalidate_shell_directory = Mock()
        app.server.send_shell_command = Mock()
        for command in ("ls -la", "pwd", "cd /scratch", "qstat -u owner", "tail -n 20 job.log"):
            self.assertTrue(WinUXController.console_command(app, command))
        app._refresh_jobs_now.assert_not_called()

    def test_unknown_scripts_and_compound_console_commands_still_recover(self):
        for command in ("qdel 123", "qsub run.pbs", "qalter -N renamed 123",
                        "./submit-script.sh", "python change_jobs.py",
                        "ls; qdel 123", "echo $(qsub run.pbs)", "echo x > run.pbs"):
            with self.subTest(command=command):
                self.assertTrue(JobPollingController.console_may_change_jobs(command))


if __name__ == "__main__":
    unittest.main()
