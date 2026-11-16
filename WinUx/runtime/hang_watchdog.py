"""Low-overhead UI heartbeat watchdog for long-running WinUx sessions."""

from __future__ import annotations
from winux_runtime.logging_policy import trim_log_tail

import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

from DearUIQt.core import QObject, QThread, Signal, Qt

from ..diagnostics import get_log_paths, log_event


class _UIHangWatchdogWorker(QObject):
    """QObject worker that owns the watchdog loop on a QThread."""

    def __init__(self, watchdog, thread):
        super().__init__()
        self.finished = Signal(self)
        self._watchdog = watchdog
        self._thread = thread

    def run(self):
        try:
            self._watchdog._loop(self._thread)
        finally:
            self.finished.emit()


class UIHangWatchdog:
    """Write an all-thread stack snapshot when the render loop stops beating."""

    def __init__(
        self,
        name="WinUx UI",
        threshold_seconds=4.0,
        repeat_seconds=15.0,
        check_interval_seconds=0.5,
    ):
        self.name = str(name)
        self.threshold_seconds = max(1.0, float(threshold_seconds))
        self.repeat_seconds = max(self.threshold_seconds, float(repeat_seconds))
        self.check_interval_seconds = max(0.2, float(check_interval_seconds))
        self._lock = threading.RLock()
        self._last_beat = time.monotonic()
        self._beat_count = 0
        self._last_report = 0.0
        self._closed = threading.Event()
        self._providers = {}
        self._health_providers = {}
        self._health_last_report = {}
        self._health_state = {}
        thread = QThread(name="winux-ui-watchdog", daemon=True)
        worker = _UIHangWatchdogWorker(self, thread)
        worker.moveToThread(thread)
        thread.started.connect(worker.run, receiver=worker)
        worker.finished.connect(thread.quit, connection_type=Qt.DirectConnection)
        thread.finished.connect(worker.deleteLater, receiver=worker)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        thread.start()

    def beat(self):
        with self._lock:
            self._last_beat = time.monotonic()
            self._beat_count += 1

    def add_snapshot_provider(self, name, callback):
        if callable(callback):
            with self._lock:
                self._providers[str(name)] = callback

    def remove_snapshot_provider(self, name):
        with self._lock:
            self._providers.pop(str(name), None)

    def add_health_provider(self, name, callback, repeat_seconds=60.0,
                            breach_checks=2, recovery_checks=2):
        """Register a read-only health snapshot checked by the watchdog thread.

        Providers may return ``threshold_breached`` or
        ``idle_render_threshold_breached``.  Breaches are rate-limited and only
        logged; checking them never pumps UI events or forces a render.
        """
        if callable(callback):
            with self._lock:
                if not hasattr(self, "_health_state"):
                    self._health_state = {}
                key = str(name)
                self._health_providers[key] = (
                    callback, max(5.0, float(repeat_seconds)),
                    max(1, int(breach_checks)), max(1, int(recovery_checks)))
                self._health_state[key] = {
                    "bad": 0, "good": 0, "latched": False,
                }

    def remove_health_provider(self, name):
        with self._lock:
            key = str(name)
            self._health_providers.pop(key, None)
            self._health_last_report.pop(key, None)
            self._health_state.pop(key, None)

    @staticmethod
    def _health_breached(value):
        if not isinstance(value, dict):
            return False
        if "threshold_breached" in value:
            return bool(value.get("threshold_breached"))
        if "idle_render_threshold_breached" in value:
            return bool(value.get("idle_render_threshold_breached"))
        if "within_threshold" in value:
            return not bool(value.get("within_threshold"))
        return False

    def _check_health_providers(self, now):
        with self._lock:
            providers = tuple(self._health_providers.items())
            last_reports = dict(self._health_last_report)
            state_store = getattr(self, "_health_state", {})
            health_state = {key: dict(value) for key, value in state_store.items()}
        for name, (provider, repeat_seconds, breach_checks, recovery_checks) in providers:
            try:
                value = provider()
            except Exception:
                continue
            breached = self._health_breached(value)
            state = health_state.get(name, {"bad": 0, "good": 0, "latched": False})
            if breached:
                state["bad"] = int(state.get("bad", 0)) + 1
                state["good"] = 0
                if state["bad"] >= breach_checks:
                    state["latched"] = True
            else:
                state["good"] = int(state.get("good", 0)) + 1
                state["bad"] = 0
                if state["good"] >= recovery_checks:
                    state["latched"] = False
            with self._lock:
                self._health_state[name] = dict(state)
            if not state.get("latched"):
                continue
            if now - float(last_reports.get(name, 0.0) or 0.0) < repeat_seconds:
                continue
            with self._lock:
                self._health_last_report[name] = now
            try:
                payload = dict(value) if isinstance(value, dict) else {"value": value}
                payload["watchdog_hysteresis"] = {
                    "bad_checks": int(state.get("bad", 0)),
                    "good_checks": int(state.get("good", 0)),
                    "breach_checks": int(breach_checks),
                    "recovery_checks": int(recovery_checks),
                    "latched": True,
                }
                rendered = json.dumps(payload, default=str, sort_keys=True)
            except Exception:
                rendered = repr(value)
            log_event("UI watchdog health threshold breached [{}]: {}".format(
                name, rendered))

    def close(self):
        self._closed.set()
        thread = self._thread
        if thread is not None:
            thread.requestInterruption()

    def _loop(self, thread):
        while (not thread.isInterruptionRequested() and
               not self._closed.wait(self.check_interval_seconds)):
            now = time.monotonic()
            self._check_health_providers(now)
            with self._lock:
                stalled_for = now - self._last_beat
                last_report = self._last_report
            if stalled_for < self.threshold_seconds:
                continue
            if now - last_report < self.repeat_seconds:
                continue
            with self._lock:
                self._last_report = now
            try:
                self._write_snapshot(stalled_for)
            except Exception:
                pass

    def _write_snapshot(self, stalled_for):
        paths = get_log_paths()
        directory = Path(paths.get("directory") or Path(os.getenv("TEMP", ".")) / "WinUx" / "logs")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "winux_hang.log"

        # Cap the diagnostic file without rotating from the potentially hung UI
        # thread. Keep the newest 1 MiB when the file grows beyond 4 MiB.
        trim_log_tail(
            str(path),
            max_bytes=1024 * 1024,
            keep_bytes=256 * 1024,
            marker=b"[WinUx hang log truncated; recent tail follows]\n",
        )

        thread_names = {
            thread.ident: thread.name
            for thread in threading.enumerate()
            if thread.ident is not None
        }
        frames = sys._current_frames()
        with self._lock:
            providers = tuple(self._providers.items())
            beat_count = self._beat_count

        lines = [
            "\n=== WinUx UI HANG SNAPSHOT ===",
            "time={}".format(time.strftime("%Y-%m-%d %H:%M:%S")),
            "ui_stalled_seconds={:.3f}".format(stalled_for),
            "heartbeat_count={}".format(beat_count),
        ]
        for name, provider in providers:
            try:
                value = provider()
            except Exception as exc:
                value = {"snapshot_error": str(exc)}
            try:
                rendered = json.dumps(value, default=str, sort_keys=True)
            except Exception:
                rendered = repr(value)
            lines.append("snapshot.{}={}".format(name, rendered))

        for ident, frame in sorted(frames.items(), key=lambda item: thread_names.get(item[0], "")):
            lines.append(
                "\n--- thread {} ({}) ---".format(
                    thread_names.get(ident, "unknown"), ident)
            )
            lines.extend(line.rstrip("\n") for line in traceback.format_stack(frame))

        text = "\n".join(lines) + "\n"
        with path.open("a", encoding="utf-8", errors="replace") as handle:
            handle.write(text)
            handle.flush()
        log_event(
            "UI watchdog captured a {:.1f}s stall: {}".format(
                stalled_for, path)
        )
