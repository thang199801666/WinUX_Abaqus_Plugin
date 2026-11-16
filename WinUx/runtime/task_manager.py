"""Qt-owned bounded background task lanes for WinUx.

WinUx feature controllers submit filesystem, SSH and analysis work through
``BackgroundTaskManager``.  The manager preserves the application's observable
handle/coalescing API, but worker ownership belongs to DearUIQt's
:class:`QThreadPool` rather than a second application-specific queue and a set
of ad-hoc ``threading.Thread`` objects.

Each manager owns one bounded QThreadPool lane.  Threads are created lazily,
reused, and never synchronously joined from a UI close path.  Completion
callbacks are still marshalled through the application's UI dispatcher.
"""

from __future__ import annotations

import sys
import threading
import time
import uuid

from DearUIQt.core import QThreadPool

from ..diagnostics import log_event, log_exception


class BackgroundTaskHandle:
    """Small observable handle for one submitted background task."""

    TERMINAL_STATES = frozenset(("completed", "failed", "cancelled", "rejected"))

    def __init__(self, name, key=None, cancel_event=None, on_done=None, scope=None):
        self.id = uuid.uuid4().hex
        self.name = str(name or "background-task")
        self.key = key
        self.scope = scope
        self.cancel_event = cancel_event or threading.Event()
        self.created_at = time.monotonic()
        self.started_at = None
        self.finished_at = None
        self.state = "queued"
        self.result = None
        self.exception = None
        self._lock = threading.RLock()
        self._done = threading.Event()
        self._on_done = on_done
        self._future = None

    def cancel(self):
        self.cancel_event.set()
        future = None
        with self._lock:
            future = self._future
            if self.state == "queued":
                self.state = "cancelled"
        if future is not None:
            try:
                future.cancel()
            except Exception:
                pass
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
                "scope": self.scope,
                "state": self.state,
                "age_s": round(max(0.0, time.monotonic() - self.created_at), 3),
                "running_s": (
                    round(max(0.0, time.monotonic() - self.started_at), 3)
                    if self.started_at is not None and self.finished_at is None
                    else None
                ),
            }


class BackgroundTaskManager:
    """Bounded Qt thread-pool lane with cancellation and coalescing.

    ``submit`` remains non-blocking.  ``key`` + ``coalesce``/``replace`` keeps
    the existing WinUx request semantics, while DearUIQt owns native worker
    creation, reuse and shutdown.
    """

    def __init__(self, max_workers=6, max_pending=128, name="winux-bg",
                 completion_dispatcher=None):
        self.max_workers = max(1, int(max_workers))
        self.max_pending = max(self.max_workers, int(max_pending))
        self.name = str(name or "winux-bg")
        self._lock = threading.RLock()
        self._closed = False
        self._handles = {}
        self._keys = {}
        self._completion_dispatcher = completion_dispatcher
        self._worker_start_error = None
        self._pool = QThreadPool.taskLane(
            self.name,
            maxThreadCount=self.max_workers,
            maxPending=self.max_pending,
            category="winux.background",
            owner=self,
        )

    def set_completion_dispatcher(self, dispatcher):
        """Route task completion callbacks through one UI dispatcher."""
        with self._lock:
            self._completion_dispatcher = dispatcher

    def completion_dispatcher(self):
        with self._lock:
            return self._completion_dispatcher

    def _post_completion(self, handle, callback):
        if not callable(callback):
            return False
        with self._lock:
            dispatcher = self._completion_dispatcher
        post = getattr(dispatcher, "post", None) if dispatcher is not None else None
        if callable(post):
            try:
                return bool(post(
                    callback, handle,
                    key=("background-task-completion", handle.id),
                ))
            except Exception:
                log_exception(
                    "Background task completion could not be posted: {}".format(
                        handle.name),
                    sys.exc_info(), fatal=False)
        return False

    def submit(
        self,
        name,
        callback,
        *args,
        key=None,
        coalesce=False,
        replace=False,
        cancel_event=None,
        on_done=None,
        scope=None,
        **kwargs
    ):
        if not callable(callback):
            raise TypeError("background callback must be callable")

        with self._lock:
            if self._closed:
                handle = BackgroundTaskHandle(name, key, cancel_event, on_done, scope)
                self._reject(handle, RuntimeError("background task manager is closed"))
                return handle
            if key is not None:
                existing_id = self._keys.get(key)
                existing = self._handles.get(existing_id)
                if existing is not None and not existing.done:
                    if coalesce:
                        return existing
                    if replace:
                        existing.cancel()

            handle = BackgroundTaskHandle(name, key, cancel_event, on_done, scope)
            self._handles[handle.id] = handle
            if key is not None:
                self._keys[key] = handle.id

        def run():
            return self._run_handle(handle, callback, args, kwargs)

        try:
            future = self._pool.tryStart(run)
        except Exception as exc:
            self._worker_start_error = exc
            future = None
        if future is None:
            error = self._worker_start_error or RuntimeError(
                "background queue is full or no Qt worker is available")
            self._reject(handle, RuntimeError(
                "background worker pool unavailable: {}".format(error)))
            log_event(
                "Background task rejected because the Qt worker lane is saturated: {}".format(
                    handle.name))
            return handle

        with handle._lock:
            handle._future = future
        future.add_done_callback(lambda completed: self._future_finished(handle, completed))
        return handle

    def _run_handle(self, handle, callback, args, kwargs):
        # QFuture may have been cancellation-requested after the pool claimed
        # the runnable but before application work starts. Preserve the WinUx
        # cooperative cancel_event contract as the authoritative feature flag.
        if handle.cancel_event.is_set():
            self._complete_cancelled(handle)
            return None

        with handle._lock:
            if handle._done.is_set():
                return handle.result
            handle.state = "running"
            handle.started_at = time.monotonic()
        try:
            result = callback(*args, **kwargs)
        except Exception as exc:
            with handle._lock:
                if not handle._done.is_set():
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
                if not handle._done.is_set():
                    handle.result = result
                    handle.state = (
                        "cancelled" if handle.cancel_event.is_set() else "completed")
                    handle.finished_at = time.monotonic()
        finally:
            self._finish_handle(handle)
        return result if 'result' in locals() else None

    def _future_finished(self, handle, future):
        """Finalize work cancelled while still queued in QThreadPool."""
        if handle.done:
            return
        try:
            cancelled = future.isCancelled()
            error = future.exception() if not cancelled else None
        except Exception as exc:
            cancelled, error = False, exc
        if cancelled or handle.cancel_event.is_set():
            self._complete_cancelled(handle)
            return
        if error is not None:
            with handle._lock:
                if handle._done.is_set():
                    return
                handle.state = "failed"
                handle.exception = error
                handle.finished_at = time.monotonic()
            self._finish_handle(handle)

    def _complete_cancelled(self, handle):
        with handle._lock:
            if handle._done.is_set():
                return
            handle.cancel_event.set()
            handle.state = "cancelled"
            handle.finished_at = time.monotonic()
        self._finish_handle(handle)

    def _finish_handle(self, handle):
        with handle._lock:
            if handle._done.is_set():
                return
            handle._done.set()
        self._post_completion(handle, handle._on_done)
        self._finalize_handle(handle)

    def _reject(self, handle, error):
        with handle._lock:
            if handle._done.is_set():
                return
            handle.state = "rejected"
            handle.exception = error
            handle.finished_at = time.monotonic()
            handle._done.set()
        self._post_completion(handle, handle._on_done)
        self._finalize_handle(handle)

    def _finalize_handle(self, handle):
        with self._lock:
            self._handles.pop(handle.id, None)
            if handle.key is not None and self._keys.get(handle.key) == handle.id:
                self._keys.pop(handle.key, None)

    def cancel_scope(self, scope):
        """Cancel queued/running tasks owned by one logical application scope.

        Running callbacks remain cooperatively cancellable: their cancel_event
        is set immediately while generation/session guards prevent stale UI
        delivery. Queued QThreadPool work is cancelled before it starts.
        """
        if scope is None:
            return 0
        with self._lock:
            handles = tuple(
                handle for handle in self._handles.values()
                if handle.scope == scope and not handle.done)
        for handle in handles:
            try:
                handle.cancel()
            except Exception:
                pass
        return len(handles)

    def scope_count(self, scope):
        if scope is None:
            return 0
        with self._lock:
            return sum(
                1 for handle in self._handles.values()
                if handle.scope == scope and not handle.done)

    def cancel_all(self):
        with self._lock:
            handles = tuple(self._handles.values())
        for handle in handles:
            try:
                handle.cancel()
            except Exception:
                pass

    def close(self, cancel_pending=True):
        """Stop accepting work without waiting for blocking callbacks."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            handles = tuple(self._handles.values())
        if cancel_pending:
            for handle in handles:
                try:
                    handle.cancel()
                except Exception:
                    pass
            # QThreadPool.clear() completes queued futures as cancelled; their
            # done callback above releases WinUx handles and posts completion.
        self._pool.close(wait=False, cancelPending=bool(cancel_pending))

    @property
    def closed(self):
        with self._lock:
            return self._closed

    def snapshot(self):
        with self._lock:
            handles = tuple(self._handles.values())
            closed = self._closed
        scope_counts = {}
        for handle in handles:
            if handle.done or handle.scope is None:
                continue
            scope_counts[str(handle.scope)] = scope_counts.get(str(handle.scope), 0) + 1
        return {
            "closed": closed,
            "workers": self._pool.threadCount(),
            "configured_workers": self.max_workers,
            "worker_start_error": (
                str(self._worker_start_error)
                if self._worker_start_error is not None else None
            ),
            "queue_size": self._pool.queuedTaskCount(),
            "queue_capacity": self.max_pending,
            "scope_counts": scope_counts,
            "active": [handle.snapshot() for handle in handles],
        }
