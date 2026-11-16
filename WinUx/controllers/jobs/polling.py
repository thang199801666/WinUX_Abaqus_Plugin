"""Adaptive PBS/qstat polling orchestration for the Job Viewer."""
from __future__ import annotations

import threading
import time
import shlex

from DearUIQt.core import QObject, QThread, Signal, Qt

from ...diagnostics import log_exception
from ...preferences.performance import PerformancePreferences
from ...services.polling_budget import CostAwarePollingPolicy
from ...services.inactivity_polling import UserInactivityPolicy
from ...runtime.operation_context import OperationContext


class _JobPollWorker(QObject):
    """Long-lived qstat worker owned by one QThread.

    The blocking waits remain native ``threading.Event`` waits because they are
    efficient cancellation primitives.  Thread ownership, interruption and
    teardown belong to QThread/QObject so the feature follows the same lifecycle
    contract as the rest of DearUIQt.
    """

    def __init__(self, controller, cancel, wakeup, force_fast, policy, thread):
        super().__init__()
        self.finished = Signal(self)
        self._controller = controller
        self._cancel = cancel
        self._wakeup = wakeup
        self._force_fast = force_fast
        self._policy = policy
        self._thread = thread

    def run(self):
        try:
            self._controller._poll_loop(
                self._cancel, self._wakeup, self._force_fast, self._policy,
                self._thread)
        finally:
            self.finished.emit()


class JobPollingController:
    """Own the one long-lived adaptive qstat poller per SSH connection."""

    def __init__(self, app, adopt_existing=False):
        self.app = app
        if not adopt_existing or not hasattr(app, "_job_poll_cancel"):
            app._job_poll_cancel = None
        if not adopt_existing or not hasattr(app, "_job_poll_policy"):
            app._job_poll_policy = None
        if not adopt_existing or not hasattr(app, "_job_poll_wakeup"):
            app._job_poll_wakeup = None
        if not adopt_existing or not hasattr(app, "_job_poll_force_fast"):
            app._job_poll_force_fast = None
        if not adopt_existing or not hasattr(app, "_job_poll_thread"):
            app._job_poll_thread = None
        if not adopt_existing or not hasattr(app, "_job_poll_worker"):
            app._job_poll_worker = None
        if not hasattr(app, "_inactivity_policy"):
            app._inactivity_policy = UserInactivityPolicy(
                settings=PerformancePreferences().load())

    @property
    def view(self):
        return self.app.view

    @property
    def server(self):
        return self.app.server

    def _post_ui(self, callback, *args, key=None):
        """Marshal one poller completion into the shared UI dispatcher.

        The long-lived qstat thread never talks to the retained view scheduler
        directly.  ``UiDispatcher.post`` wakes the one QApplication host turn
        and can coalesce replaceable refresh/error deliveries by key.
        """
        getter = getattr(self.view, "eventDispatcher", None)
        dispatcher = getter() if callable(getter) else None
        post = getattr(dispatcher, "post", None)
        if callable(post):
            return post(callback, *args, key=key)
        self.view.after(0, callback, *args)
        return True

    @staticmethod
    def signature(jobs):
        """Return scheduler state that matters for adaptive refresh.

        Elapsed time is intentionally excluded: it changes continuously for a
        running job and would pin the policy at its minimum interval forever.
        Add/remove/state/resource changes still collapse the interval to the
        configured minimum immediately.
        """
        return tuple(sorted(
            (str(job.job_id), str(job.name), str(job.user),
             str(job.tokens), str(job.status))
            for job in (jobs or [])
        ))

    @staticmethod
    def configure_policy(policy, settings):
        return policy.configure(
            min_interval=settings["qstat_min_interval"],
            max_interval=settings["qstat_max_interval"],
            stable_samples_to_max=settings["qstat_stable_samples_to_max"],
            quiet_seconds_to_max=settings["qstat_quiet_seconds_to_max"],
        )

    @staticmethod
    def recovery_window(settings):
        # PBS can acknowledge qsub/qdel before qstat reflects the change. Keep
        # at least three minimum-interval opportunities to see it, for >=30s.
        return max(30.0, 3.0 * float(settings["qstat_min_interval"]))

    def runtime_delete_watch_active(self):
        """Return True while a delete schedule depends on PBS elapsed runtime.

        Runtime-limit deletion must keep receiving qstat snapshots even when
        ordinary UI inactivity would suspend polling completely; otherwise a
        30-minute run limit could be missed until the user returns hours later.
        """
        lock = getattr(self.app, "_job_delete_lock", None)
        tasks = getattr(self.app, "_job_delete_tasks", None)
        if lock is None or tasks is None:
            return False
        try:
            with lock:
                return any(
                    task.get("runtime_limit_seconds") is not None
                    and (task.get("cancel") is None or not task["cancel"].is_set())
                    and not task.get("delete_requested")
                    for task in tasks.values())
        except Exception:
            return False

    @staticmethod
    def console_may_change_jobs(command):
        """Skip obvious read-only commands; unknown scripts remain conservative."""
        command = str(command or "").strip()
        if not command:
            return False
        if any(char in command for char in ";|&\n\r`$<>()"):
            return True
        try:
            words = shlex.split(command)
        except ValueError:
            return True
        if not words:
            return False
        executable = words[0].rsplit("/", 1)[-1]
        return executable not in {
            "ls", "pwd", "cd", "cat", "head", "tail", "echo", "clear", "date",
            "whoami", "hostname", "uname", "df", "du", "free", "uptime", "history",
            "qstat", "pbsnodes", "which", "type", "less", "more",
        }

    def _poll_loop(self, cancel, wakeup, force_fast, policy, thread):
        """Run the adaptive qstat loop inside the worker QThread."""
        def wait_delay(delay):
            # ``None`` means deep-idle suspension. Wake periodically only to
            # reload local settings/observe shutdown; this performs no SSH/PBS
            # request. User activity and stop() both interrupt immediately.
            wakeup.wait(60.0 if delay is None else max(0.0, float(delay)))
            wakeup.clear()

        while (not cancel.is_set() and not self.app._closing and
               not thread.isInterruptionRequested()):
            current = PerformancePreferences().load()
            self.configure_policy(policy, current)
            inactivity = self.app._inactivity_policy
            inactivity.configure(current)
            forced = force_fast.is_set()
            if forced:
                force_fast.clear()
                policy.hold_fast(self.recovery_window(current))
            runtime_watch = self.runtime_delete_watch_active()

            if not forced and not runtime_watch:
                idle_delay = inactivity.qstat_delay(policy.current_interval)
                if idle_delay is None:
                    wait_delay(None)
                    continue

            if not self.server.connected:
                self.app._connection_online.clear()
                self.app._start_reconnect()
                delay = inactivity.qstat_delay(policy.on_error())
                wait_delay(delay)
                continue

            budget_delay = policy.next_query_delay()
            if budget_delay > 0:
                wakeup.wait(budget_delay)
                wakeup.clear()
                continue

            query_started = time.monotonic()
            policy.record_query_start(query_started)
            try:
                jobs = server.list_jobs()
            except Exception as exc:
                policy.record_cost(time.monotonic() - query_started)
                log_exception(
                    "PBS job polling failed",
                    (type(exc), exc, exc.__traceback__))
                self._post_ui(
                    self.apply_error, cancel, str(exc),
                    key=("job-poll-error", id(cancel)))
                if not self.server.connected:
                    self.app._connection_online.clear()
                    self.app._start_reconnect()
                delay = policy.on_error()
            else:
                policy.record_cost(time.monotonic() - query_started)
                previous_changes = policy.change_count
                delay = policy.observe(self.signature(jobs))
                if policy.change_count != previous_changes:
                    delay = policy.force_fast()
                try:
                    self._post_ui(
                        self.app._apply_job_update, cancel, jobs,
                        key=("job-poll-update", id(cancel)))
                except Exception:
                    return

            if self.runtime_delete_watch_active():
                delay = min(float(delay), float(current["qstat_min_interval"]))
            else:
                delay = inactivity.qstat_delay(delay)
            wait_delay(delay)

    def start(self):
        """Start one adaptive QObject/QThread qstat worker per connection."""
        self.stop()
        cancel = threading.Event()
        wakeup = threading.Event()
        force_fast = threading.Event()
        self.app._job_poll_cancel = cancel
        self.app._job_poll_wakeup = wakeup
        self.app._job_poll_force_fast = force_fast

        settings = PerformancePreferences().load()
        policy = CostAwarePollingPolicy(
            settings["qstat_min_interval"],
            settings["qstat_max_interval"],
            settings["qstat_stable_samples_to_max"],
            settings["qstat_quiet_seconds_to_max"],
        )
        self.app._job_poll_policy = policy

        thread = QThread(name="winux-job-poller", daemon=True)
        worker = _JobPollWorker(
            self, cancel, wakeup, force_fast, policy, thread)
        worker.moveToThread(thread)
        thread.started.connect(worker.run, receiver=worker)
        worker.finished.connect(
            thread.quit, connection_type=Qt.DirectConnection)
        thread.finished.connect(worker.deleteLater, receiver=worker)
        thread.finished.connect(thread.deleteLater)
        self.app._job_poll_thread = thread
        self.app._job_poll_worker = worker
        thread.start()

    def stop(self):
        cancel = getattr(self.app, "_job_poll_cancel", None)
        wakeup = getattr(self.app, "_job_poll_wakeup", None)
        thread = getattr(self.app, "_job_poll_thread", None)
        self.app._job_poll_cancel = None
        self.app._job_poll_policy = None
        self.app._job_poll_wakeup = None
        self.app._job_poll_force_fast = None
        self.app._job_poll_thread = None
        self.app._job_poll_worker = None
        if cancel is not None:
            cancel.set()
        if thread is not None:
            thread.requestInterruption()
        if wakeup is not None:
            wakeup.set()

    def apply_update(self, cancel, jobs):
        # Ignore callbacks queued by a superseded connection.
        if (cancel is not self.app._job_poll_cancel or cancel.is_set() or
                self.app._closing or not self.view.winfo_exists()):
            return
        self.app._reconcile_job_deletions(jobs)
        self.view.display_jobs(jobs)

    def apply_error(self, cancel, error):
        """Publish qstat failure to a waiting manager on the UI thread."""
        if (cancel is not self.app._job_poll_cancel or cancel.is_set()
                or self.app._closing or not self.view.winfo_exists()):
            return
        callback = getattr(self.view, "display_job_poll_error", None)
        if callable(callback):
            callback(error)

    def refresh_now(self):
        if not self.server.connected or self.app._closing:
            return

        # Prefer the single long-lived poller so a manual/job-triggered refresh
        # cannot race a second qstat -f against it. The policy is collapsed to
        # its minimum interval and the current wait is interrupted.
        cancel = self.app._job_poll_cancel
        force_fast = self.app._job_poll_force_fast
        wakeup = self.app._job_poll_wakeup
        if (cancel is not None and not cancel.is_set() and
                force_fast is not None and wakeup is not None):
            force_fast.set()
            wakeup.set()
            return

        # Fallback for the narrow window before the connection poller exists.
        context = OperationContext(self.app, remote=True)
        server = context.server

        def worker():
            context.check()
            active = self.app._job_poll_cancel
            if active is not None and not active.is_set():
                # The normal poller may have started while this task waited.
                return ("poller-active", None)
            try:
                jobs = server.list_jobs()
            except Exception as exc:
                return ("error", str(exc))
            return ("jobs", jobs)

        def completed(handle):
            if not context.current():
                return
            if handle.state in {"failed", "rejected"}:
                message = str(handle.exception or "Background queue is full; try again")
                callback = getattr(self.view, "display_job_poll_error", None)
                if callable(callback):
                    callback(message)
                self.view.show_error("Refresh failed", message)
                return
            result = handle.result
            if not isinstance(result, tuple) or not result:
                return
            status, payload = result
            if status == "poller-active":
                self.refresh_now()
            elif status == "error":
                callback = getattr(self.view, "display_job_poll_error", None)
                if callable(callback):
                    callback(str(payload))
                self.view.show_error("Refresh failed", str(payload))
            elif status == "jobs":
                active = self.app._job_poll_cancel
                if active is not None:
                    self.app._apply_job_update(active, payload)

        context.submit_background(
            "job-refresh", worker, key=("job-refresh", context.connection),
            coalesce=True, on_done=completed)
