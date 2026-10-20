"""Bound visual updates to one queued callback per UI turn."""
from __future__ import annotations

import threading


class LatestCallQueue:
    """Replace pending display state and batch delivery per event-loop turn.

    Qt compresses many posted UI events before control returns to the event loop.
    The retained wrappers use the same idea: all independent latest-value keys
    share one scheduler wake-up, while each key still preserves only its newest
    payload. Re-entrant posts are intentionally delivered on the *next* turn so
    one callback cannot monopolize the GUI thread.
    """

    def __init__(self, after, max_batch=128):
        self._after = after
        self._lock = threading.Lock()
        self._pending = {}
        self._closed = False
        self._scheduled = False
        self._max_batch = max(1, int(max_batch))

    def post(self, key, callback, *args, **kwargs):
        with self._lock:
            if self._closed:
                return False
            self._pending[key] = callback, args, kwargs
            schedule = not self._scheduled
            if schedule:
                self._scheduled = True
        if schedule:
            try:
                self._after(0, self._deliver_batch)
            except Exception:
                with self._lock:
                    self._scheduled = False
                    # Keep no callback references when scheduling itself failed.
                    self._pending.clear()
                raise
        return True

    def _deliver_batch(self):
        # Drain only the ready prefix. Keeping the unprocessed tail in the
        # insertion-ordered dict avoids copying/rebuilding the whole queue for a
        # bounded UI turn. ``_scheduled`` stays True while callbacks execute so
        # re-entrant posts join the existing next-turn reservation rather than
        # allocating an extra scheduler wake-up.
        with self._lock:
            if self._closed:
                self._scheduled = False
                self._pending.clear()
                return
            limit = min(self._max_batch, len(self._pending))
            ready = []
            for _ in range(limit):
                key = next(iter(self._pending))
                ready.append((key, self._pending.pop(key)))
        error = None
        for _key, payload in ready:
            if payload is None:
                continue
            callback, args, kwargs = payload
            try:
                callback(*args, **kwargs)
            except Exception as exc:
                if error is None:
                    error = exc
        schedule = False
        with self._lock:
            if self._closed:
                self._pending.clear()
                self._scheduled = False
            elif self._pending:
                # This callback consumed the current scheduler reservation; the
                # retained tail (plus any re-entrant posts) needs exactly one
                # reservation for the following UI turn.
                self._scheduled = True
                schedule = True
            else:
                self._scheduled = False
        if schedule:
            try:
                self._after(0, self._deliver_batch)
            except Exception:
                with self._lock:
                    self._scheduled = False
                    self._pending.clear()
                raise
        if error is not None:
            raise error

    def close(self):
        with self._lock:
            self._closed = True
            self._pending.clear()
            # A scheduled empty delivery may still run, but it holds no user
            # callback references and exits immediately.

    def discard(self, key):
        """Invalidate payload while keeping its existing queue reservation."""
        with self._lock:
            if key in self._pending:
                self._pending[key] = None
