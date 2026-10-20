"""Adaptive PBS/qstat polling orchestration for the Job Viewer."""
from __future__ import annotations

import threading
import time
import shlex

from ..diagnostics import log_exception
from ..preferences.performance import PerformancePreferences
from ..services.polling_budget import CostAwarePollingPolicy
from ..services.inactivity_polling import UserInactivityPolicy
from ..runtime.operation_context import OperationContext


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
        if not hasattr(app, "_inactivity_policy"):
            app._inactivity_policy = UserInactivityPolicy(
                settings=PerformancePreferences().load())

    @property
    def view(self):
        return self.app.view

    @property
    def server(self):
        return self.app.server

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

    def start(self):
        """Start one adaptive, cancellable JobViewer poller per connection."""
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

        def wait_delay(delay):
            # ``None`` means deep-idle suspension.  Wake periodically only to
            # reload local settings/observe shutdown; this performs no SSH/PBS
            # request. User activity and stop() both interrupt immediately.
            wakeup.wait(60.0 if delay is None else max(0.0, float(delay)))
            wakeup.clear()

        def poll():
            while not cancel.is_set() and not self.app._closing:
                # Settings are stored by the floating Settings process. Reload
                # the tiny local JSON document so changes apply to an already
                # connected session without reconnecting.
                current = PerformancePreferences().load()
                self.configure_policy(policy, current)
                inactivity = self.app._inactivity_policy
                inactivity.configure(current)
                forced = force_fast.is_set()
                if forced:
                    force_fast.clear()
                    policy.hold_fast(self.recovery_window(current))

                # After prolonged inactivity qstat can be suspended completely.
                # Known mutations/user-resume set force_fast, allowing exactly
                # one prompt snapshot before the inactivity policy applies again.
                if not forced:
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
                    # Keep the wait cancellable/coalesced. Repeated clicks do
                    # not buy new tokens, so they cannot bypass this budget.
                    wakeup.wait(budget_delay)
                    wakeup.clear()
                    continue

                query_started = time.monotonic()
                policy.record_query_start(query_started)
                try:
                    jobs = self.server.list_jobs()
                except Exception as exc:
                    policy.record_cost(time.monotonic() - query_started)
                    log_exception(
                        "PBS job polling failed",
                        (type(exc), exc, exc.__traceback__))
                    self.view.after(0, self.apply_error, cancel, str(exc))
                    if not self.server.connected:
                        self.app._connection_online.clear()
                        self.app._start_reconnect()
                    delay = policy.on_error()
                else:
                    policy.record_cost(time.monotonic() - query_started)
                    previous_changes = policy.change_count
                    delay = policy.observe(self.signature(jobs))
                    if policy.change_count != previous_changes:
                        # A server-side transition normally deserves a fast
                        # follow-up, but client inactivity still wins because no
                        # person is waiting for the repaint.
                        delay = policy.force_fast()
                    try:
                        self.view.after(0, self.app._apply_job_update, cancel, jobs)
                    except Exception:
                        return

                delay = inactivity.qstat_delay(delay)
                # Requests arriving during qstat need one subsequent snapshot:
                # the running query may predate a submit/cancel operation.
                # User activity sets wakeup+force_fast, so even a deep-idle
                # suspended poll resumes immediately without a second poller.
                wait_delay(delay)

        threading.Thread(
            target=poll, name="winux-job-poller", daemon=True).start()

    def stop(self):
        cancel = getattr(self.app, "_job_poll_cancel", None)
        wakeup = getattr(self.app, "_job_poll_wakeup", None)
        self.app._job_poll_cancel = None
        self.app._job_poll_policy = None
        self.app._job_poll_wakeup = None
        self.app._job_poll_force_fast = None
        if cancel is not None:
            cancel.set()
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
        def worker():
            if not context.current():
                return
            active = self.app._job_poll_cancel
            if active is not None and not active.is_set():
                # The normal poller may have started while this task waited.
                self.refresh_now()
                return
            try:
                jobs = self.server.list_jobs()
            except Exception as exc:
                callback = getattr(self.view, "display_job_poll_error", None)
                if callable(callback):
                    context.post(0, callback, str(exc))
                context.post(
                    0, self.view.show_error, "Refresh failed", str(exc))
                return
            active = self.app._job_poll_cancel
            if active is not None:
                context.post(0, self.app._apply_job_update, active, jobs)

        handle = self.app._submit_background(
            "job-refresh", worker, key=("job-refresh", context.connection), coalesce=True)
        context.report_rejection(handle, self.view.show_error, "Refresh failed")
