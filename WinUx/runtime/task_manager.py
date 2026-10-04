"""Bounded daemon worker pool for WinUx background operations.

The application used to create a new ``threading.Thread`` for almost every
filesystem, SSH and job action.  That is simple but makes a long-running
embedded SMAPython process accumulate many short-lived thread objects and
makes shutdown/race behaviour hard to reason about.

``BackgroundTaskManager`` owns a small, fixed set of daemon workers and a
bounded queue.  Callers keep the same closure-based worker code; only task
scheduling is centralized.  It deliberately never waits during ``close()`` so
closing WinUx cannot be held hostage by a blocked network call.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid

from ..diagnostics import log_event, log_exception


class BackgroundTaskHandle:
    """Small observable handle for one submitted background task."""

    TERMINAL_STATES = frozenset(("completed", "failed", "cancelled", "rejected"))

    def __init__(self, name, key=None, cancel_event=None):
        self.id = uuid.uuid4().hex
        self.name = str(name or "background-task")
        self.key = key
        self.cancel_event = cancel_event or threading.Event()
        self.created_at = time.monotonic()
        self.started_at = None
        self.finished_at = None
        self.state = "queued"
        self.result = None
        self.exception = None
        self._lock = threading.RLock()
        self._done = threading.Event()

    def cancel(self):
        self.cancel_event.set()
        with self._lock:
            if self.state == "queued":
                self.state = "cancelled"
        return True

    @property
    def done(self):
        return self._done.is_set()

    def wait(self, timeout=None):
        return self._done.wait(timeout)

    def snapshot(self):
        with self._lock:
            return {
                "id": self.id,
                "name": self.name,
                "key": self.key,
                "state": self.state,
                "age_s": round(max(0.0, time.monotonic() - self.created_at), 3),
                "running_s": (
                    round(max(0.0, time.monotonic() - self.started_at), 3)
                    if self.started_at is not None and self.finished_at is None
                    else None
                ),
            }


class BackgroundTaskManager:
    """Fixed-size daemon pool with bounded pending work and cancellation.

    ``submit`` is non-blocking.  If the queue is saturated the task is rejected
    instead of freezing Dear PyGui's render thread while waiting for capacity.
    A ``key`` can be used with ``coalesce=True`` to reuse an already-active
    task, which is useful for repeated refresh requests.
    """

    def __init__(self, max_workers=6, max_pending=128, name="winux-bg"):
        self.max_workers = max(1, int(max_workers))
        self.max_pending = max(self.max_workers, int(max_pending))
        self.name = str(name or "winux-bg")
        self._queue = queue.Queue(maxsize=self.max_pending)
        self._lock = threading.RLock()
        self._closed = False
        self._handles = {}
        self._keys = {}
        self._workers = []
        self._sentinel = object()
        for index in range(self.max_workers):
            worker = threading.Thread(
                target=self._worker_loop,
                name="{}-{}".format(self.name, index + 1),
                daemon=True,
            )
            worker.start()
            self._workers.append(worker)

    def submit(
        self,
        name,
        callback,
        *args,
        key=None,
        coalesce=False,
        replace=False,
        cancel_event=None,
        **kwargs
    ):
        if not callable(callback):
            raise TypeError("background callback must be callable")

        with self._lock:
            if self._closed:
                handle = BackgroundTaskHandle(name, key, cancel_event)
                self._reject(handle, RuntimeError("background task manager is closed"))
                return handle
            if key is not None:
                existing_id = self._keys.get(key)
                existing = self._handles.get(existing_id)
                if existing is not None and not existing.done:
                    if coalesce:
                        return existing
                    if replace:
                        # A queued task will be skipped by the worker. A task
                        # already running receives its cancellation signal and
                        # may finish naturally; the new task is still queued.
                        existing.cancel()

            handle = BackgroundTaskHandle(name, key, cancel_event)
            self._handles[handle.id] = handle
            if key is not None:
                self._keys[key] = handle.id

        item = (handle, callback, args, kwargs)
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            self._reject(
                handle,
                RuntimeError(
                    "background queue is full ({} pending)".format(
                        self.max_pending)),
            )
            log_event(
                "Background task rejected because the queue is full: {}".format(
                    handle.name)
            )
        return handle

    def _reject(self, handle, error):
        with handle._lock:
            handle.state = "rejected"
            handle.exception = error
            handle.finished_at = time.monotonic()
            handle._done.set()
        self._finalize_handle(handle)

    def _worker_loop(self):
        while True:
            try:
                item = self._queue.get()
            except Exception:
                return
            if item is self._sentinel:
                return
            handle, callback, args, kwargs = item
            try:
                if handle.cancel_event.is_set():
                    with handle._lock:
                        handle.state = "cancelled"
                        handle.finished_at = time.monotonic()
                    continue
                with handle._lock:
                    handle.state = "running"
                    handle.started_at = time.monotonic()
                try:
                    result = callback(*args, **kwargs)
                except Exception as exc:
                    with handle._lock:
                        handle.state = "failed"
                        handle.exception = exc
                        handle.finished_at = time.monotonic()
                    log_exception(
                        "Background task failed: {}".format(handle.name),
                        (type(exc), exc, exc.__traceback__),
                        fatal=False,
                    )
                else:
                    with handle._lock:
                        handle.result = result
                        handle.state = (
                            "cancelled"
                            if handle.cancel_event.is_set()
                            else "completed"
                        )
                        handle.finished_at = time.monotonic()
            finally:
                handle._done.set()
                self._finalize_handle(handle)
                try:
                    self._queue.task_done()
                except Exception:
                    pass

    def _finalize_handle(self, handle):
        with self._lock:
            # Keep only active tasks in the registry; diagnostics need current
            # pressure, not an ever-growing history of completed closures.
            self._handles.pop(handle.id, None)
            if handle.key is not None and self._keys.get(handle.key) == handle.id:
                self._keys.pop(handle.key, None)

    def cancel_all(self):
        with self._lock:
            handles = tuple(self._handles.values())
        for handle in handles:
            try:
                handle.cancel()
            except Exception:
                pass

    def close(self, cancel_pending=True):
        """Stop accepting work without waiting for blocked worker threads."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        if cancel_pending:
            self.cancel_all()
        # Workers are daemon threads.  Wake idle workers where queue capacity
        # permits, but never block the caller trying to enqueue sentinels.
        for _worker in self._workers:
            try:
                self._queue.put_nowait(self._sentinel)
            except queue.Full:
                break

    @property
    def closed(self):
        with self._lock:
            return self._closed

    def snapshot(self):
        with self._lock:
            handles = tuple(self._handles.values())
            closed = self._closed
        return {
            "closed": closed,
            "workers": self.max_workers,
            "queue_size": self._queue.qsize(),
            "queue_capacity": self.max_pending,
            "active": [handle.snapshot() for handle in handles],
        }
