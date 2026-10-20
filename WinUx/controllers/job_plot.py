"""Realtime Job Viewer plot and job-ODB coordination.

This module owns the stateful ODB plot watchers that used to live directly in
``WinUXController``.  The application controller remains the public facade;
small compatibility methods delegate here so existing callbacks and tests can
keep using the historical method names while plot lifecycle/state has one
focused owner.
"""
from __future__ import annotations

import threading
import time

from ..preferences.abaqus_versions import AbaqusVersionPreferences
from ..diagnostics import log_exception
from ..preferences.performance import PerformancePreferences
from ..services.adaptive_polling import AdaptivePollingPolicy, EventIntervalLearner
from ..services.inactivity_polling import UserInactivityPolicy


class JobPlotController:
    """Own realtime plot watchers and Job Viewer ODB actions."""

    def __init__(self, app):
        self.app = app
        self._watchers = {}
        self._lock = threading.RLock()
        # Session-local model of how long submitted/running jobs usually take
        # before their ODB becomes visible.  Sharing it across plots lets later
        # jobs avoid hammering the server while still reacting quickly near the
        # historically likely appearance time.
        self._appearance_learner = EventIntervalLearner()
        self._adaptive_preferences_cache = None
        self._adaptive_preferences_loaded_at = 0.0
        if not hasattr(app, "_inactivity_policy"):
            app._inactivity_policy = UserInactivityPolicy(
                settings=PerformancePreferences().load())

    @property
    def view(self):
        return self.app.view

    @property
    def server(self):
        return self.app.server

    def selection_changed(self, job_id, items):
        key = str(job_id)
        with self._lock:
            state = self._watchers.get(key)
            if state is None:
                return
            state["selection"] = [dict(item) for item in (items or [])]

    def closed(self, job_id):
        key = str(job_id)
        with self._lock:
            state = self._watchers.pop(key, None)
        if state is not None:
            state["cancel"].set()
        windows = getattr(self.view, "job_plot_windows", None)
        if isinstance(windows, dict):
            windows.pop(key, None)

    def stop_all(self):
        """Cancel plot watchers without ever blocking the UI shutdown path."""
        acquired = False
        states = ()
        try:
            acquired = self._lock.acquire(False)
            if acquired:
                states = tuple(self._watchers.values())
                self._watchers.clear()
        except Exception:
            states = ()
        finally:
            if acquired:
                try:
                    self._lock.release()
                except Exception:
                    pass
        for state in states:
            try:
                state["cancel"].set()
            except Exception:
                pass

    def apply_payload(self, job_id, payload):
        if self.app._closing:
            return
        window = self.view.get_job_plots(job_id)
        if window is None:
            return
        payload_type = str((payload or {}).get("type") or "")
        if payload_type == "catalog":
            window.set_catalog(payload)
        elif payload_type == "frame":
            window.update_frame(payload)
        elif payload_type == "status":
            message = str(payload.get("message") or payload.get("state") or "")
            window.set_status(message or "Monitoring ODB...")
        elif payload_type == "fatal":
            # A remote helper may stop while Abaqus is still writing the ODB.
            # The watcher restarts it, so this is a transient retry state,
            # not a terminal red Error dialog/status.
            window.set_status("Plot retrying: {}".format(
                str(payload.get("error") or "ODB is temporarily unreadable")))

    def selection_snapshot(self, job_id):
        with self._lock:
            state = self._watchers.get(str(job_id))
            if state is None:
                return []
            return [dict(item) for item in state.get("selection") or []]

    @staticmethod
    def adaptive_settings():
        settings = PerformancePreferences().load()
        return {
            "min_interval": settings["odb_min_interval"],
            "max_interval": settings["odb_max_interval"],
            "stable_samples_to_max": settings["odb_stable_samples_to_max"],
            "quiet_seconds_to_max": settings["odb_quiet_seconds_to_max"],
            "history_alpha": settings["odb_history_alpha"],
            "prediction_fraction": settings["odb_prediction_fraction"],
            "history_confidence_samples": settings["odb_history_confidence_samples"],
            "catalog_changed_checks": settings["odb_catalog_changed_checks"],
        }

    def effective_adaptive_settings(self):
        """Apply app-inactivity backoff to the ordinary ODB policy.

        The remote monitor asks for effective settings several times per second
        so a resume can interrupt a long deep-idle wait immediately.  Cache the
        local JSON preference document for two seconds; activity stage remains
        live/in-memory and therefore does not inherit that cache delay.
        """
        now = time.monotonic()
        with self._lock:
            preferences = self._adaptive_preferences_cache
            loaded_at = self._adaptive_preferences_loaded_at
        if preferences is None or now - loaded_at >= 2.0:
            latest = PerformancePreferences().load()
            with self._lock:
                self._adaptive_preferences_cache = latest
                self._adaptive_preferences_loaded_at = now
                preferences = latest
        policy = self.app._inactivity_policy
        policy.configure(preferences)
        base = {
            "min_interval": preferences["odb_min_interval"],
            "max_interval": preferences["odb_max_interval"],
            "stable_samples_to_max": preferences["odb_stable_samples_to_max"],
            "quiet_seconds_to_max": preferences["odb_quiet_seconds_to_max"],
            "history_alpha": preferences["odb_history_alpha"],
            "prediction_fraction": preferences["odb_prediction_fraction"],
            "history_confidence_samples": preferences["odb_history_confidence_samples"],
            "catalog_changed_checks": preferences["odb_catalog_changed_checks"],
        }
        return policy.effective_odb_settings(base, now=now)

    def discovery_delay(self, policy, started_at, settings):
        """Blend ordinary backoff with learned ODB-appearance timing."""
        age = max(0.0, time.monotonic() - float(started_at))
        with self._lock:
            self._appearance_learner.configure(
                alpha=settings["history_alpha"],
                prediction_fraction=settings["prediction_fraction"],
                confidence_samples=settings["history_confidence_samples"],
            )
            return self._appearance_learner.recommend(
                age,
                policy.current_interval,
                settings["min_interval"],
                settings["max_interval"],
            )

    def remember_appearance_wait(self, seconds, settings):
        """Learn one genuine ODB-appearance wait for later jobs this session."""
        seconds = float(seconds)
        if seconds < float(settings["min_interval"]):
            return
        with self._lock:
            self._appearance_learner.configure(
                alpha=settings["history_alpha"],
                prediction_fraction=settings["prediction_fraction"],
                confidence_samples=settings["history_confidence_samples"],
            )
            self._appearance_learner.observe_interval(seconds)

    def watch_loop(self, job_id, job_name, cancel):
        """Wait for the job ODB, then keep a persistent Abaqus monitor live."""
        key = str(job_id)
        odb_path = None
        commands = AbaqusVersionPreferences().ordered_commands()
        initial_poll = self.effective_adaptive_settings()
        discovery_policy = AdaptivePollingPolicy(
            initial_poll["min_interval"],
            initial_poll["max_interval"],
            initial_poll["stable_samples_to_max"],
            initial_poll["quiet_seconds_to_max"],
        )
        discovery_started_at = time.monotonic()
        discovery_saw_missing = False
        monitor_retry_count = 0
        previous_monitor_error = None

        while not cancel.is_set() and not self.app._closing:
            latest_poll = self.effective_adaptive_settings()
            discovery_policy.configure(
                min_interval=latest_poll["min_interval"],
                max_interval=latest_poll["max_interval"],
                stable_samples_to_max=latest_poll["stable_samples_to_max"],
                quiet_seconds_to_max=latest_poll["quiet_seconds_to_max"],
            )
            if not self.server.connected:
                self.app._connection_online.clear()
                self.app._start_reconnect()
                self.view.after(
                    0,
                    self.apply_payload,
                    key,
                    {
                        "type": "status",
                        "state": "waiting",
                        "message": "Waiting for SSH connection...",
                    },
                )
                cancel.wait(discovery_policy.observe("disconnected"))
                continue

            if odb_path is None:
                try:
                    odb_path = self.server.find_job_output_file(
                        job_id, job_name, extension=".odb")
                except Exception:
                    discovery_saw_missing = True
                    if not self.server.connected:
                        self.app._connection_online.clear()
                        self.app._start_reconnect()
                    self.view.after(
                        0,
                        self.apply_payload,
                        key,
                        {
                            "type": "status",
                            "state": "waiting",
                            "message": "Waiting for job ODB to appear...",
                        },
                    )
                    discovery_policy.observe("missing")
                    cancel.wait(
                        self.discovery_delay(
                            discovery_policy, discovery_started_at, latest_poll
                        )
                    )
                    continue
                if discovery_saw_missing:
                    self.remember_appearance_wait(
                        time.monotonic() - discovery_started_at, latest_poll
                    )
                discovery_policy.force_fast()
                discovery_started_at = time.monotonic()
                discovery_saw_missing = False
                self.view.after(
                    0,
                    self.apply_payload,
                    key,
                    {
                        "type": "status",
                        "state": "opening",
                        "message": "Finding compatible Abaqus release for {}...".format(
                            odb_path.name
                        ),
                    },
                )

            try:
                self.server.stream_odb_history(
                    odb_path,
                    cancel,
                    lambda: self.selection_snapshot(key),
                    lambda payload: self.view.after(0, self.apply_payload, key, payload),
                    abaqus_commands=commands,
                    adaptive_settings=self.effective_adaptive_settings(),
                    adaptive_settings_provider=self.effective_adaptive_settings,
                )
                if cancel.is_set() or self.app._closing:
                    return
                monitor_retry_count = 0
                self.view.after(
                    0,
                    self.apply_payload,
                    key,
                    {
                        "type": "status",
                        "state": "waiting",
                        "message": "Realtime monitor stopped; reconnecting...",
                    },
                )
                cancel.wait(1.0)
            except Exception as exc:
                if cancel.is_set() or self.app._closing:
                    return
                monitor_retry_count += 1
                # Log the first failure or a changed error, rather than
                # generating thousands of identical stack traces for an ODB
                # still being written by Abaqus.
                error_text = str(exc)
                if error_text != previous_monitor_error:
                    log_exception(
                        "Realtime Job ODB plot failed (will retry)",
                        (type(exc), exc, exc.__traceback__),
                    )
                    previous_monitor_error = error_text
                retry_delay = min(30.0, max(1.0, float(
                    latest_poll["min_interval"])) *
                    (2 ** min(monitor_retry_count - 1, 5)))
                self.view.after(
                    0,
                    self.apply_payload,
                    key,
                    {
                        "type": "status",
                        "state": "retry",
                        "message": "ODB not ready; retry {} in {:.0f}s: {}".format(
                            monitor_retry_count, retry_delay, error_text[:160]),
                    },
                )
                # Keep the resolved path on ordinary failures (the ODB may
                # become readable without being renamed). Rediscover every
                # third failure in case the job rotated/renamed the file.
                if monitor_retry_count % 3 == 0:
                    odb_path = None
                    discovery_policy.force_fast()
                    discovery_started_at = time.monotonic()
                    discovery_saw_missing = False
                cancel.wait(retry_delay)

    def open(self, values):
        if self.app._closing or not values:
            return
        if not self.app._ensure_server_online():
            return
        job_id, job_name, owner = str(values[0]), str(values[1]), str(values[2])
        if owner.casefold() != self.server.username.casefold():
            return

        existing = self.view.get_job_plots(job_id)
        if existing is not None:
            existing.focus()
            return

        self.view.show_job_plots(job_id, job_name, self.selection_changed, self.closed)
        cancel = threading.Event()
        state = {
            "cancel": cancel,
            "selection": [],
            "job_name": job_name,
            "thread": None,
        }
        thread = threading.Thread(
            target=self.watch_loop,
            args=(job_id, job_name, cancel),
            name="winux-job-plot-{}".format(job_id),
            daemon=True,
        )
        state["thread"] = thread
        with self._lock:
            self._watchers[job_id] = state
        thread.start()

    def odb_failed(self, title, message):
        if self.app._closing:
            return
        try:
            self.view.right.status.set("Job ODB check failed")
        except Exception:
            pass
        self.view.show_error(title, message)

    def odb_resolved(self, action, job_id, job_name, path):
        """Continue a Job Viewer ODB action after resolving its remote file."""
        if self.app._closing or not self.server.connected:
            return
        path = self.server.normalize(path)
        if action == "job_check_odb":
            self.app.check_odb(self.view.right, [path])
        elif action == "job_extract_odb":
            self.app.extract_odb(self.view.right, [path])

    def odb_command(self, action, values):
        """Resolve the selected job's .odb from scratch, then run ODB tools."""
        if self.app._closing or not values:
            return
        if not self.app._ensure_server_online():
            return

        job_id = str(values[0])
        job_name = str(values[1])
        owner = str(values[2])
        if owner.casefold() != self.server.username.casefold():
            return

        try:
            self.view.right.status.set("Locating ODB for job {}...".format(job_id))
        except Exception:
            pass

        def worker():
            try:
                path = self.server.find_job_output_file(
                    job_id, job_name, extension=".odb"
                )
            except Exception as exc:
                message = (
                    "No usable ODB file was found for job {} ({}) yet.\n\n{}".format(
                        job_id, job_name or "unnamed job", exc
                    )
                )
                self.view.after(0, self.odb_failed, "Check ODB", message)
                return
            self.view.after(0, self.odb_resolved, action, job_id, job_name, path)

        self.app._submit_background(
            "job-odb-resolve:{}".format(job_id),
            worker,
            key=("job-odb-resolve", action, job_id),
            coalesce=True,
        )
