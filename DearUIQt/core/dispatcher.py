"""Backend-neutral, UI-thread-owned event dispatcher without a timer thread."""
import heapq
import threading
import time


class QEventDispatcher:
    """Thread-safe posting/cancellation; callbacks execute only on the owner.

    Platform hosts combine ``nextDeadlineMs`` with their native event wait and
    install ``setWakeCallback`` to interrupt that wait for earlier worker work.
    This class never renders or blocks the GUI thread itself.
    """

    def __init__(self, *, clock=None):
        self._clock = time.monotonic if clock is None else clock
        self._owner_thread = threading.get_ident()
        self._lock = threading.Lock()
        self._deadlines = []
        self._callbacks = {}
        self._sequence = 0
        self._closed = False
        self._processing = False
        self._wake_callback = None
        self._wake_pending = False

    def _discard_cancelled_head(self):
        # Caller holds _lock. Cancellation releases payloads immediately.
        while self._deadlines and self._deadlines[0][1] not in self._callbacks:
            heapq.heappop(self._deadlines)

    def setWakeCallback(self, callback):
        if callback is not None and not callable(callback):
            raise TypeError('wake callback must be callable or None')
        with self._lock:
            if self._closed:
                return False
            previous = self._wake_callback
            self._wake_callback = callback
            self._wake_pending = False
        del previous
        return True

    def after(self, delay_ms, callback, *args):
        if not callable(callback):
            raise TypeError('callback must be callable')
        due = self._clock() + max(0, int(delay_ms or 0)) / 1000.0
        wake = None
        with self._lock:
            if self._closed:
                return None
            self._discard_cancelled_head()
            earlier = not self._deadlines or due < self._deadlines[0][0]
            self._sequence += 1
            token = self._sequence
            self._callbacks[token] = (callback, args)
            heapq.heappush(self._deadlines, (due, token))
            if (earlier and not self._wake_pending and self._wake_callback is not None
                    and threading.get_ident() != self._owner_thread):
                self._wake_pending = True
                wake = self._wake_callback
        # Never invoke user/platform code with the scheduler lock held.
        if wake is not None:
            try:
                wake()
            except Exception:
                with self._lock:
                    self._wake_pending = False
                raise
        return token

    def after_cancel(self, token):
        if token is None:
            return False
        with self._lock:
            payload = self._callbacks.pop(token, None)
            if payload is None:
                return False
            self._discard_cancelled_head()
            if len(self._deadlines) > max(64, len(self._callbacks) * 2 + 32):
                self._deadlines[:] = [entry for entry in self._deadlines
                                      if entry[1] in self._callbacks]
                heapq.heapify(self._deadlines)
        # Drop callback references outside the lock (finalizers may re-enter).
        return True

    def nextDeadlineMs(self):
        """Time to the next callback, zero for due work, or None when empty."""
        with self._lock:
            self._discard_cancelled_head()
            if self._closed or not self._deadlines:
                return None
            return max(0.0, self._deadlines[0][0] - self._clock()) * 1000.0

    def hasPendingEvents(self):
        """Whether a callback is due now, not merely scheduled for the future."""
        delay = self.nextDeadlineMs()
        return delay is not None and delay <= 0

    def pendingCount(self):
        with self._lock:
            return len(self._callbacks)

    def isClosed(self):
        with self._lock:
            return self._closed

    def processEvents(self, max_callbacks=256, time_budget_ms=8.0, *, on_error=None):
        """Deliver a bounded turn; reentrant/new posts wait for the next turn.

        Cancellation remains effective until callback delivery begins, including
        when an earlier callback cancels another due callback. Without an error
        handler, the first callback error is raised after other ready work.
        """
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError('event processing requires the owning thread')
        limit = None if max_callbacks is None else max(0, int(max_callbacks))
        budget = None if time_budget_ms is None else max(0, float(time_budget_ms)) / 1000.0
        started = self._clock()
        with self._lock:
            if self._closed or self._processing:
                return 0
            self._wake_pending = False
            self._processing = True
            sequence_limit = self._sequence
        processed, error = 0, None
        try:
            while limit is None or processed < limit:
                if budget is not None and processed and self._clock() - started >= budget:
                    break
                with self._lock:
                    self._discard_cancelled_head()
                    if self._closed or not self._deadlines:
                        break
                    due, token = self._deadlines[0]
                    if due > started or token > sequence_limit:
                        break
                    heapq.heappop(self._deadlines)
                    payload = self._callbacks.pop(token)
                callback, args = payload
                try:
                    callback(*args)
                except Exception as exc:
                    if on_error is None:
                        if error is None:
                            error = exc
                    else:
                        try:
                            on_error(callback, exc)
                        except Exception as handler_error:
                            if error is None:
                                error = handler_error
                processed += 1
        finally:
            with self._lock:
                self._processing = False
        if error is not None:
            raise error
        return processed

    def close(self):
        """Reject new posts and release payloads without waiting for deadlines."""
        with self._lock:
            self._closed = True
            callbacks, self._callbacks = self._callbacks, {}
            self._deadlines.clear()
            wake_callback = self._wake_callback
            self._wake_callback = None
            self._wake_pending = False
        callbacks.clear()
        del wake_callback


__all__ = ['QEventDispatcher']
