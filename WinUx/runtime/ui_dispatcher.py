"""Thread-safe dispatch of worker results onto the single GUI event loop."""

from __future__ import annotations

import heapq
import queue
import sys
import threading
import time


class UiDispatcher:
    """Qt-style GUI dispatcher with no timer/scheduler worker thread.

    ``after()`` stores delayed callbacks in a monotonic deadline heap.  The main
    WinUx render/event loop promotes due callbacks during ``drain()`` and then
    executes them on the GUI thread. Background workers may still enqueue UI
    completions safely, but UI scheduling itself owns no thread and no process.

    This intentionally mirrors Qt's architecture more closely than the previous
    implementation: one application event loop owns timers, posted callbacks,
    widget events and rendering; worker pools are reserved for non-UI work.
    """

    def __init__(self):
        # The GUI callback queue is intentionally unbounded: back-pressure is
        # provided by the per-frame drain budget, while producers must never
        # block a network/background worker waiting for UI capacity.  CPython's
        # SimpleQueue has a much smaller synchronization footprint than Queue
        # (no task tracking/condition variables) and is ideal for this MPSC ->
        # single-GUI-consumer path.
        self.queue = queue.SimpleQueue()
        self._lock = threading.RLock()
        # Heap entries carry only deadline/token. Callback payloads live in a
        # separate map so cancellation releases bound methods/dialog references
        # immediately instead of retaining them until the old deadline expires.
        self._scheduled = []
        self._scheduled_callbacks = {}
        self._sequence = 0
        self._closed = False
        self._owner_thread = threading.get_ident()

    def after(self, delay_ms, callback, *args):
        """Post ``callback`` to the GUI event loop now or after ``delay_ms``.

        No ``threading.Timer`` and no scheduler thread are created. Delayed work
        becomes runnable when the owning GUI loop next drains this dispatcher.
        """
        if not callable(callback):
            return None
        delay_ms = max(0.0, float(delay_ms or 0))
        with self._lock:
            if self._closed:
                return None
            if delay_ms <= 0:
                self.queue.put((callback, args))
                return None
            self._sequence += 1
            token = self._sequence
            self._scheduled_callbacks[token] = (callback, args)
            heapq.heappush(
                self._scheduled,
                (time.monotonic() + delay_ms / 1000.0, token),
            )
            return token

    def after_cancel(self, token):
        """Cancel one delayed callback and release its payload immediately."""
        if token is None:
            return False
        with self._lock:
            removed = self._scheduled_callbacks.pop(token, None) is not None
            if not removed:
                return False
            # Cancelled heap nodes contain only floats/ints and are harmless,
            # but compact opportunistically during timer-heavy dialog churn.
            live = len(self._scheduled_callbacks)
            if len(self._scheduled) > max(64, live * 2 + 32):
                self._scheduled[:] = [
                    item for item in self._scheduled
                    if item[1] in self._scheduled_callbacks
                ]
                heapq.heapify(self._scheduled)
            return True

    def _promote_due_callbacks(self, max_promotions=None):
        """Promote a bounded due-timer prefix into the immediate GUI FIFO.

        A delayed bulk refresh can make thousands of timers expire together.
        Promoting all of them before the per-frame callback budget previously
        caused an unbounded allocation and lock hold on the render thread. Leave
        the remaining heap nodes in deadline/sequence order for later frames.
        Cancelled tombstones do not count against the live promotion budget.
        """
        now = time.monotonic()
        due = []
        limit = None if max_promotions is None else max(0, int(max_promotions))
        if limit == 0:
            return 0
        with self._lock:
            if self._closed:
                return 0
            while self._scheduled and self._scheduled[0][0] <= now:
                _deadline, token = heapq.heappop(self._scheduled)
                payload = self._scheduled_callbacks.pop(token, None)
                if payload is not None:
                    due.append(payload)
                    if limit is not None and len(due) >= limit:
                        break
        for payload in due:
            self.queue.put(payload)
        return len(due)

    def drain(self, on_error=None, max_callbacks=None, time_budget_ms=None):
        """Execute one bounded GUI-event turn on the caller/UI thread."""
        # With a bounded GUI turn, admit at most as many expired timers as
        # callbacks we can execute. An explicitly unbounded drain preserves its
        # original drain-all semantics for non-render-loop consumers.
        if max_callbacks is None:
            self._promote_due_callbacks()
        elif int(max_callbacks) > 0:
            self._promote_due_callbacks(max_promotions=int(max_callbacks))
        processed = 0
        start = time.monotonic()
        budget = (
            None if time_budget_ms is None
            else max(0.0, float(time_budget_ms)) / 1000.0
        )
        while True:
            if max_callbacks is not None and processed >= int(max_callbacks):
                return processed
            if budget is not None and processed and time.monotonic() - start >= budget:
                return processed
            try:
                callback, args = self.queue.get_nowait()
            except queue.Empty:
                return processed
            try:
                callback(*args)
            except Exception:
                if on_error is None:
                    raise
                on_error(callback, sys.exc_info())
            processed += 1

    def next_deadline_ms(self):
        """Milliseconds until the next delayed UI callback, or ``None``."""
        with self._lock:
            if self._closed:
                return None
            while (self._scheduled and
                   self._scheduled[0][1] not in self._scheduled_callbacks):
                heapq.heappop(self._scheduled)
            if not self._scheduled:
                return None
            remaining = max(0.0, self._scheduled[0][0] - time.monotonic())
        return remaining * 1000.0

    def close(self):
        """Reject future work and release queued callback references."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._scheduled[:] = []
            self._scheduled_callbacks.clear()

        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break

    @property
    def closed(self):
        with self._lock:
            return self._closed

    def snapshot(self):
        with self._lock:
            scheduled = len(self._scheduled_callbacks)
            closed = self._closed
        try:
            queued = self.queue.qsize()
        except Exception:
            queued = -1
        return {
            "closed": closed,
            "queued_callbacks": queued,
            "scheduled_callbacks": scheduled,
            "owner_thread": self._owner_thread,
            # Compatibility fields retained for diagnostics/tests. UI scheduling
            # is now intentionally always threadless.
            "scheduler_alive": False,
            "scheduler_fallback": True,
            "scheduler_start_error": None,
            "single_event_loop": True,
        }
