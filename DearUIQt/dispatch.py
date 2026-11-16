"""Bound visual updates to one queued callback per UI turn."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from itertools import islice


class LatestCallQueue:
    """Replace pending display state and batch delivery per event-loop turn.

    Qt compresses many posted UI events before control returns to the event loop.
    The retained wrappers use the same idea: all independent latest-value keys
    share one scheduler wake-up, while each key still preserves only its newest
    payload. Re-entrant posts are intentionally delivered on the *next* turn so
    one callback cannot monopolize the GUI thread. Optional ``time_budget_ms``
    bounds work between callbacks; it cannot preempt one long callback.
    """

    def __init__(self, after, max_batch=128, *, time_budget_ms=None):
        self._after = after
        self._lock = threading.Lock()
        self._pending = OrderedDict()
        self._closed = False
        self._scheduled = False
        self._max_batch = max(1, int(max_batch))
        self._time_budget = (None if time_budget_ms is None
                             else max(0.0, float(time_budget_ms)) / 1000.0)

    def _schedule_failed(self):
        with self._lock:
            self._scheduled = False
            pending, self._pending = self._pending, OrderedDict()
        # Payload finalizers may post again; never release them under _lock.
        pending.clear()

    def post(self, key, callback, *args, **kwargs):
        with self._lock:
            if self._closed:
                return False
            previous = self._pending.get(key)
            self._pending[key] = object(), callback, args, kwargs
            schedule = not self._scheduled
            if schedule:
                self._scheduled = True
        del previous
        if schedule:
            try:
                self._after(0, self._deliver_batch)
            except Exception:
                self._schedule_failed()
                raise
        return True

    def _deliver_batch(self):
        # Snapshot only keys/tokens, not callback payloads. Until each delivery
        # begins, discard/close/newer posts must still invalidate its old value.
        # Keeping tokens alive also prevents identity reuse after replacement.
        with self._lock:
            if self._closed:
                self._scheduled = False
                return
            ready = [(key, None if payload is None else payload[0])
                     for key, payload in islice(self._pending.items(), self._max_batch)]
        error = None
        started, processed = time.perf_counter(), 0
        for key, token in ready:
            if (self._time_budget is not None and processed
                    and time.perf_counter() - started >= self._time_budget):
                break
            with self._lock:
                if self._closed:
                    break
                payload = self._pending.get(key)
                if payload is None:
                    self._pending.pop(key, None)
                elif payload[0] is token:
                    self._pending.pop(key)
                else:
                    # A replacement posted during this turn belongs to the next
                    # turn. Do not deliver either the obsolete or new value now.
                    payload = None
            if payload is None:
                continue
            _token, callback, args, kwargs = payload
            try:
                callback(*args, **kwargs)
            except Exception as exc:
                if error is None:
                    error = exc
            processed += 1
        schedule = False
        with self._lock:
            if self._closed:
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
                self._schedule_failed()
                raise
        if error is not None:
            raise error

    def close(self):
        with self._lock:
            self._closed = True
            pending, self._pending = self._pending, OrderedDict()
            # A scheduled empty delivery may still run, but it holds no user
            # callback references and exits immediately.
        pending.clear()

    def discard(self, key):
        """Invalidate payload while keeping its existing queue reservation."""
        with self._lock:
            previous = None
            if key in self._pending:
                previous = self._pending[key]
                self._pending[key] = None
        del previous
