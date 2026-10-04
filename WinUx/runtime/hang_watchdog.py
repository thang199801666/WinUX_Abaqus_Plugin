"""Low-overhead UI heartbeat watchdog for long-running WinUx sessions."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

from ..diagnostics import get_log_paths, log_event


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
        self._thread = threading.Thread(
            target=self._loop,
            name="winux-ui-watchdog",
            daemon=True,
        )
        self._thread.start()

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

    def close(self):
        self._closed.set()

    def _loop(self):
        while not self._closed.wait(self.check_interval_seconds):
            now = time.monotonic()
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
        try:
            if path.exists() and path.stat().st_size > 4 * 1024 * 1024:
                with path.open("rb") as handle:
                    handle.seek(max(0, path.stat().st_size - 1024 * 1024))
                    tail = handle.read()
                with path.open("wb") as handle:
                    handle.write(b"[WinUx hang log truncated; recent tail follows]\n")
                    handle.write(tail)
        except Exception:
            pass

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
