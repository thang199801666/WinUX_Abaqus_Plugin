"""Thread-safe dispatch of worker results onto the UI thread."""

from __future__ import annotations

import heapq
import queue
import sys
import threading
import time


class UiDispatcher:
    """Immediate UI queue plus one shared delayed-callback scheduler.

    Older builds created one ``threading.Timer`` thread for every delayed
    ``after()`` call.  A long WinUx session can issue thousands of those calls.
    This implementation keeps exactly one daemon scheduler thread regardless of
    delayed callback volume and supports bounded per-frame draining.
    """

    def __init__(self):
        self.queue = queue.Queue()
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._scheduled = []
        self._sequence = 0
        self._closed = False
        self._scheduler = threading.Thread(
            target=self._scheduler_loop,
            name="winux-ui-scheduler",
            daemon=True,
        )
        self._scheduler.start()

    def after(self, delay_ms, callback, *args):
        """Queue ``callback`` now or after ``delay_ms`` without a new thread."""
        if not callable(callback):
            return None
        delay_ms = max(0.0, float(delay_ms or 0))
        if delay_ms <= 0:
            with self._lock:
                if self._closed:
                    return None
                self.queue.put((callback, args))
            return None

        with self._condition:
            if self._closed:
                return None
            self._sequence += 1
            token = self._sequence
            heapq.heappush(
                self._scheduled,
                (time.monotonic() + delay_ms / 1000.0, token, callback, args),
            )
            self._condition.notify()
        return token

    def _scheduler_loop(self):
        while True:
            with self._condition:
                while not self._closed and not self._scheduled:
                    self._condition.wait()
                if self._closed:
                    return
                deadline, token, callback, args = self._scheduled[0]
                delay = deadline - time.monotonic()
                if delay > 0:
                    self._condition.wait(timeout=delay)
                    continue
                heapq.heappop(self._scheduled)
            # Do not hold the scheduler lock while touching the UI queue.
            with self._lock:
                if self._closed:
                    return
                self.queue.put((callback, args))

    def drain(
        self,
        on_error=None,
        max_callbacks=None,
        time_budget_ms=None,
    ):
        """Execute queued callbacks on the caller/UI thread.

        ``max_callbacks`` and ``time_budget_ms`` prevent a burst of worker
        completions from monopolizing one render frame.  Omitted limits keep
        the historical drain-all behaviour for tests and compatibility.
        """
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

    def close(self):
        """Reject future work and release scheduled callback references."""
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._scheduled[:] = []
            self._condition.notify_all()

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
            scheduled = len(self._scheduled)
            closed = self._closed
        try:
            queued = self.queue.qsize()
        except Exception:
            queued = -1
        return {
            "closed": closed,
            "queued_callbacks": queued,
            "scheduled_callbacks": scheduled,
            "scheduler_alive": self._scheduler.is_alive(),
        }
