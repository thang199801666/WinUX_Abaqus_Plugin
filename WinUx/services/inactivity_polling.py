"""User-inactivity-aware remote polling policy.

The ordinary adaptive pollers react to server-side stability.  This policy adds
an orthogonal client-side signal: when nobody is interacting with WinUx, remote
queries can back off much further because fresh UI state has little value.

No worker thread is created here.  Callers feed user activity into the policy
and existing polling/reconnect workers consult the current stage.
"""
from __future__ import annotations

import threading
import time


class UserInactivityPolicy:
    """Track application input and provide safe remote-load backoff stages."""

    ACTIVE = "active"
    IDLE = "idle"
    AWAY = "away"
    DEEP_IDLE = "deep_idle"

    def __init__(self, *, clock=None, settings=None):
        self._clock = clock or time.monotonic
        self._condition = threading.Condition()
        self._last_activity_at = self._clock()
        self._resume_generation = 0
        self._idle_seconds = 120.0
        self._away_seconds = 600.0
        self._deep_idle_seconds = 1800.0
        self._idle_qstat_interval = 60.0
        self._away_qstat_interval = 180.0
        self._deep_qstat_interval = 0.0
        self._deep_odb_interval = 600.0
        if settings:
            self.configure(settings)

    def configure(self, settings):
        values = dict(settings or {})
        with self._condition:
            idle = max(5.0, float(values.get(
                "inactivity_idle_seconds", self._idle_seconds)))
            away = max(idle, float(values.get(
                "inactivity_away_seconds", self._away_seconds)))
            deep = max(away, float(values.get(
                "inactivity_deep_idle_seconds", self._deep_idle_seconds)))
            self._idle_seconds = idle
            self._away_seconds = away
            self._deep_idle_seconds = deep
            self._idle_qstat_interval = max(1.0, float(values.get(
                "inactivity_idle_qstat_interval", self._idle_qstat_interval)))
            self._away_qstat_interval = max(
                self._idle_qstat_interval,
                float(values.get(
                    "inactivity_away_qstat_interval", self._away_qstat_interval)),
            )
            self._deep_qstat_interval = max(0.0, float(values.get(
                "inactivity_deep_qstat_interval", self._deep_qstat_interval)))
            self._deep_odb_interval = max(30.0, float(values.get(
                "inactivity_deep_odb_interval", self._deep_odb_interval)))
        return self.snapshot()

    def _stage_locked(self, now):
        age = max(0.0, float(now) - self._last_activity_at)
        if age >= self._deep_idle_seconds:
            return self.DEEP_IDLE
        if age >= self._away_seconds:
            return self.AWAY
        if age >= self._idle_seconds:
            return self.IDLE
        return self.ACTIVE

    def stage(self, now=None):
        now = self._clock() if now is None else float(now)
        with self._condition:
            return self._stage_locked(now)

    def idle_seconds(self, now=None):
        now = self._clock() if now is None else float(now)
        with self._condition:
            return max(0.0, now - self._last_activity_at)

    def note_activity(self, now=None):
        """Record one app interaction and wake deep-idle waiters on resume.

        Returns the stage that existed immediately before the interaction.  The
        resume generation changes only when WinUx was actually backed off, so a
        high-frequency mouse-move stream does not wake sleeping workers over and
        over while the app is already active.
        """
        now = self._clock() if now is None else float(now)
        with self._condition:
            previous = self._stage_locked(now)
            self._last_activity_at = now
            if previous != self.ACTIVE:
                self._resume_generation += 1
                self._condition.notify_all()
            return previous

    @property
    def resume_generation(self):
        with self._condition:
            return self._resume_generation

    def wait_for_resume(self, generation, timeout=None):
        """Wait until a backed-off session receives new application input."""
        with self._condition:
            if self._resume_generation != generation:
                return self._resume_generation
            self._condition.wait(timeout)
            return self._resume_generation

    def qstat_delay(self, baseline, now=None):
        """Return effective qstat delay, or ``None`` for deep-idle suspension."""
        baseline = max(0.0, float(baseline))
        now = self._clock() if now is None else float(now)
        with self._condition:
            stage = self._stage_locked(now)
            if stage == self.DEEP_IDLE:
                if self._deep_qstat_interval <= 0.0:
                    return None
                return max(baseline, self._deep_qstat_interval)
            if stage == self.AWAY:
                return max(baseline, self._away_qstat_interval)
            if stage == self.IDLE:
                return max(baseline, self._idle_qstat_interval)
            return baseline

    def effective_odb_settings(self, settings, now=None):
        """Stretch ODB polling while idle without killing a live monitor.

        The remote helper waits on stdin with ``select()``, so when activity
        resumes the normal config message interrupts even a long deep-idle wait
        and the next file stat happens immediately.
        """
        values = dict(settings or {})
        now = self._clock() if now is None else float(now)
        with self._condition:
            stage = self._stage_locked(now)
            deep_interval = self._deep_odb_interval

        minimum = max(0.25, float(values.get("min_interval", 1.0)))
        maximum = max(minimum, float(values.get("max_interval", minimum)))
        if stage == self.IDLE:
            values["min_interval"] = max(minimum, 5.0)
            values["max_interval"] = max(maximum, 120.0)
            values["quiet_seconds_to_max"] = min(
                float(values.get("quiet_seconds_to_max", 180.0)), 60.0)
        elif stage == self.AWAY:
            values["min_interval"] = max(minimum, 20.0)
            values["max_interval"] = max(maximum, 300.0)
            values["quiet_seconds_to_max"] = min(
                float(values.get("quiet_seconds_to_max", 180.0)), 60.0)
        elif stage == self.DEEP_IDLE:
            # Keep a very sparse heartbeat instead of abandoning an already
            # open Abaqus monitor process on the server.
            values["min_interval"] = max(minimum, min(60.0, deep_interval))
            values["max_interval"] = max(values["min_interval"], deep_interval)
            values["quiet_seconds_to_max"] = 30.0
        values["inactivity_stage"] = stage
        return values

    def snapshot(self, now=None):
        now = self._clock() if now is None else float(now)
        with self._condition:
            return {
                "stage": self._stage_locked(now),
                "idle_seconds": max(0.0, now - self._last_activity_at),
                "idle_after_seconds": self._idle_seconds,
                "away_after_seconds": self._away_seconds,
                "deep_idle_after_seconds": self._deep_idle_seconds,
                "idle_qstat_interval": self._idle_qstat_interval,
                "away_qstat_interval": self._away_qstat_interval,
                "deep_qstat_interval": self._deep_qstat_interval,
                "deep_odb_interval": self._deep_odb_interval,
                "resume_generation": self._resume_generation,
            }
