"""Bound visual updates to one queued callback per key."""
from __future__ import annotations

import threading


class LatestCallQueue:
    """Replace pending display state; preserve ordinary commands separately."""

    def __init__(self, after):
        self._after = after
        self._lock = threading.Lock()
        self._pending = {}
        self._closed = False

    def post(self, key, callback, *args, **kwargs):
        with self._lock:
            if self._closed:
                return False
            schedule = key not in self._pending
            self._pending[key] = callback, args, kwargs
        if schedule:
            try:
                self._after(0, self._deliver, key)
            except Exception:
                with self._lock:
                    self._pending.pop(key, None)
                raise
        return True

    def _deliver(self, key):
        with self._lock:
            work = self._pending.pop(key, None)
        if work is not None:
            callback, args, kwargs = work
            callback(*args, **kwargs)

    def close(self):
        with self._lock:
            self._closed = True
            self._pending.clear()

    def discard(self, key):
        """Invalidate payload while keeping its existing queue reservation."""
        with self._lock:
            if key in self._pending:
                self._pending[key] = None
