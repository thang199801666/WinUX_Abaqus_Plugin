"""Qt-like background execution primitives backed by a bounded thread pool.

The UI framework deliberately exposes a small subset of Qt's concurrency model:
``QRunnable`` describes work, ``QThreadPool`` owns reusable daemon threads and
``QFuture`` exposes cancellation/result state plus signals.  Widgets/dialogs
should submit work here instead of creating ad-hoc ``threading.Thread`` objects.

The implementation is toolkit-independent and safe to export with the reusable
UI framework.  Signal delivery follows :mod:`.core`: connect a future signal to
an owning ``QObject`` and cross-thread delivery is marshalled through that
receiver's UI scheduler.
"""
from __future__ import annotations

from concurrent.futures import CancelledError, TimeoutError
import itertools
import os
import queue
import threading

from .object import QObject, Signal


class QRunnable:
    """Unit of work submitted to :class:`QThreadPool`.

    Subclasses normally override :meth:`run`.  A plain callable can also be
    passed directly to ``QThreadPool.start`` for lightweight host code.
    """

    def __init__(self):
        self._auto_delete = True

    def run(self):  # pragma: no cover - abstract compatibility method
        raise NotImplementedError

    def autoDelete(self):
        return self._auto_delete

    def setAutoDelete(self, enabled):
        self._auto_delete = bool(enabled)


class _CallableRunnable(QRunnable):
    def __init__(self, callback, args, kwargs):
        super().__init__()
        self.callback = callback
        self.args = args
        self.kwargs = kwargs

    def run(self):
        return self.callback(*self.args, **self.kwargs)


class QFuture(QObject):
    """Observable result handle for one thread-pool submission."""

    def __init__(self, parent=None, *, after=None):
        super().__init__(parent, after=after)
        self.started = Signal(self)
        self.resultReady = Signal(self)
        self.failed = Signal(self)
        self.cancelled = Signal(self)
        self.finished = Signal(self)
        self._lock = threading.RLock()
        self._done = threading.Event()
        self._cancel_requested = threading.Event()
        self._running = False
        self._result = None
        self._exception = None
        self._done_callbacks = []

    def cancel(self):
        """Request cancellation.

        Like Qt/Python futures, running Python code cannot be forcibly stopped.
        ``isCancellationRequested`` lets cooperative runnables terminate early;
        queued work is skipped by the pool before execution.
        """
        if self._done.is_set():
            return False
        self._cancel_requested.set()
        return True

    def isCancellationRequested(self):
        return self._cancel_requested.is_set()

    def isCancelled(self):
        return self._done.is_set() and self._cancel_requested.is_set() and self._exception is None

    def isRunning(self):
        with self._lock:
            return self._running and not self._done.is_set()

    def isFinished(self):
        return self._done.is_set()

    def waitForFinished(self, timeout=None):
        return self._done.wait(timeout)

    def result(self, timeout=None):
        if not self._done.wait(timeout):
            raise TimeoutError()
        if self.isCancelled():
            raise CancelledError()
        if self._exception is not None:
            raise self._exception
        return self._result

    def exception(self, timeout=None):
        if not self._done.wait(timeout):
            raise TimeoutError()
        return self._exception

    def add_done_callback(self, callback):
        """Register a completion callback using ``concurrent.futures`` semantics.

        The callback receives this ``QFuture`` and runs on the thread that
        completes the work.  UI code should normally prefer ``QFutureWatcher``;
        this compatibility hook lets toolkit-independent application services
        accept either a Python executor future or DearUIQt's shared QFuture.
        """
        if not callable(callback):
            raise TypeError("future callback must be callable")
        call_now = False
        with self._lock:
            if self._done.is_set():
                call_now = True
            else:
                self._done_callbacks.append(callback)
        if call_now:
            callback(self)
        return callback

    def _begin(self):
        with self._lock:
            if self._done.is_set() or self._cancel_requested.is_set():
                return False
            self._running = True
        self.started.emit()
        return True

    def _complete(self, result=None, exception=None):
        with self._lock:
            if self._done.is_set():
                return
            self._running = False
            self._result = result
            self._exception = exception
            callbacks = tuple(self._done_callbacks)
            self._done_callbacks = []
            self._done.set()
        if exception is not None:
            self.failed.emit(exception)
        elif self._cancel_requested.is_set():
            self.cancelled.emit()
        else:
            self.resultReady.emit(result)
        self.finished.emit()
        for callback in callbacks:
            try:
                callback(self)
            except Exception:
                # Match concurrent.futures: callback failures never change the
                # already-completed future state or kill a pool worker.
                pass

    def _complete_cancelled(self):
        self._cancel_requested.set()
        self._complete()


class QFutureWatcher(QObject):
    """QObject bridge that re-emits one :class:`QFuture` on its UI thread.

    Terminal state is published from one idempotent snapshot callback.  That
    matters for very short jobs: a future can finish in the tiny interval
    between connecting ``finished`` and checking ``isFinished``.  In that race
    both paths may schedule publication, but only the first one is allowed to
    emit result/error/cancel + ``finished``.
    """

    def __init__(self, parent=None, *, after=None):
        super().__init__(parent, after=after)
        self.started = Signal(self)
        self.resultReady = Signal(self)
        self.failed = Signal(self)
        self.cancelled = Signal(self)
        self.finished = Signal(self)
        self._future = None
        self._future_connections = []
        self._terminal_emitted = False

    def _publish_terminal(self, future):
        if self._deleted or self._future is not future or self._terminal_emitted:
            return
        if not future.isFinished():
            return
        self._terminal_emitted = True
        if future.isCancelled():
            self.cancelled.emit()
        else:
            error = future.exception()
            if error is not None:
                self.failed.emit(error)
            else:
                self.resultReady.emit(future.result())
        self.finished.emit()

    def setFuture(self, future):
        if not isinstance(future, QFuture):
            raise TypeError("QFutureWatcher requires a QFuture")
        if self._deleted:
            raise RuntimeError("cannot configure a deleted future watcher")
        for connection in tuple(self._future_connections):
            connection.disconnect()
        self._future_connections = []
        self._future = future
        self._terminal_emitted = False
        self._future_connections.append(
            future.started.connect(self.started.emit, receiver=self))
        self._future_connections.append(
            future.finished.connect(lambda: self._publish_terminal(future), receiver=self))
        # If the future completed before the watcher was attached, publish the
        # snapshot on the watcher scheduler. If ``finished`` was also queued in
        # the attachment race, ``_terminal_emitted`` suppresses the duplicate.
        if future.isFinished():
            if self._after is not None:
                self._after(0, self._publish_terminal, future)
            else:
                self._publish_terminal(future)

    def future(self):
        return self._future

    def isFinished(self):
        return bool(self._future is not None and self._future.isFinished())

    def cancel(self):
        return bool(self._future is not None and self._future.cancel())

    def result(self, timeout=None):
        if self._future is None:
            raise RuntimeError("future watcher has no future")
        return self._future.result(timeout)

    def delete(self):
        for connection in tuple(self._future_connections):
            connection.disconnect()
        self._future_connections = []
        self._future = None
        super().delete()


class QThreadPool:
    """Reusable daemon workers with a Qt-compatible submission surface.

    Threads are created lazily and reused across all submitted jobs.  The queue
    is bounded so a saturated UI cannot allocate unbounded closures/tasks.
    """

    _global_instance = None
    _global_lock = threading.Lock()

    def __init__(self, maxThreadCount=None, *, maxPending=256, name="qt-worker"):
        if maxThreadCount is None:
            maxThreadCount = min(32, max(4, (os.cpu_count() or 4)))
        self._max_threads = max(1, int(maxThreadCount))
        self._max_pending = max(self._max_threads, int(maxPending))
        self._name = str(name or "qt-worker")
        self._queue = queue.PriorityQueue(maxsize=self._max_pending)
        self._lock = threading.RLock()
        self._workers = []
        self._active = 0
        self._closed = False
        self._sequence = itertools.count()

    @classmethod
    def globalInstance(cls):
        with cls._global_lock:
            if cls._global_instance is None or cls._global_instance._closed:
                cls._global_instance = cls(name="qt-global")
            return cls._global_instance

    def maxThreadCount(self):
        with self._lock:
            return self._max_threads

    def setMaxThreadCount(self, count):
        value = max(1, int(count))
        with self._lock:
            if self._closed:
                raise RuntimeError("thread pool is closed")
            self._max_threads = value
        self._ensure_workers()

    def activeThreadCount(self):
        with self._lock:
            return self._active

    def queuedTaskCount(self):
        return self._queue.qsize()

    def _ensure_workers(self):
        error = None
        with self._lock:
            if self._closed:
                return None
            # Grow lazily with demand, then reuse the same threads.  This keeps
            # a large logical pool (useful for blocking IPC readers) without
            # eagerly creating every worker on the first dialog.
            # ``active + qsize`` has a dequeue race: a worker can remove a
            # long-lived task from the queue just before it increments
            # ``_active``.  A second submission in that tiny window would see
            # neither the claimed task nor an active worker and could remain
            # queued forever behind the blocking first task.  ``unfinished_tasks``
            # is incremented by Queue.put() and is not decremented until
            # task_done(), so it counts queued *and already-dequeued* work and
            # closes that gap.  This is important for paired IPC reader/writer
            # jobs used by floating dialog hosts.
            with self._queue.all_tasks_done:
                demand = max(1, int(self._queue.unfinished_tasks))
            target = min(self._max_threads, demand)
            while len(self._workers) < target:
                index = len(self._workers) + 1
                worker = threading.Thread(
                    target=self._worker_loop,
                    name="{}-{}".format(self._name, index),
                    daemon=True,
                )
                try:
                    worker.start()
                except Exception as exc:
                    # OS thread quota/resource exhaustion must not crash the UI
                    # caller or leave an unstarted Thread object counted as a
                    # live worker forever. Existing workers can still drain the
                    # queue; with no workers the submitting future is failed by
                    # start()/tryStart() below.
                    error = exc
                    break
                self._workers.append(worker)
        return error

    def _discard_queued_item(self, item):
        """Remove one not-yet-claimed PriorityQueue item after spawn failure."""
        with self._queue.mutex:
            try:
                self._queue.queue.remove(item)
            except ValueError:
                return False
            import heapq
            heapq.heapify(self._queue.queue)
            self._queue.unfinished_tasks = max(0, self._queue.unfinished_tasks - 1)
            if self._queue.unfinished_tasks == 0:
                self._queue.all_tasks_done.notify_all()
            self._queue.not_full.notify()
            return True

    @staticmethod
    def _coerce_runnable(runnable, args, kwargs):
        if isinstance(runnable, QRunnable):
            if args or kwargs:
                raise TypeError("QRunnable submissions do not accept call arguments")
            return runnable
        if not callable(runnable):
            raise TypeError("thread-pool work must be callable or QRunnable")
        return _CallableRunnable(runnable, args, kwargs)

    def start(self, runnable, *args, priority=0, after=None, **kwargs):
        """Queue work and return a :class:`QFuture` immediately."""
        work = self._coerce_runnable(runnable, args, kwargs)
        future = QFuture(after=after)
        with self._lock:
            if self._closed:
                raise RuntimeError("thread pool is closed")
        item = (-int(priority), next(self._sequence), work, future)
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            future._complete(exception=RuntimeError("thread pool queue is full"))
            return future
        error = self._ensure_workers()
        if error is not None:
            with self._lock:
                no_workers = not self._workers
            if no_workers and self._discard_queued_item(item):
                future._complete(exception=RuntimeError("unable to start thread-pool worker: {}".format(error)))
        return future

    def tryStart(self, runnable, *args, priority=0, after=None, **kwargs):
        work = self._coerce_runnable(runnable, args, kwargs)
        future = QFuture(after=after)
        with self._lock:
            if self._closed:
                return None
        item = (-int(priority), next(self._sequence), work, future)
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            return None
        error = self._ensure_workers()
        if error is not None:
            with self._lock:
                no_workers = not self._workers
            if no_workers and self._discard_queued_item(item):
                return None
        return future

    def _worker_loop(self):
        while True:
            try:
                _priority, _sequence, runnable, future = self._queue.get(timeout=.2)
            except queue.Empty:
                with self._lock:
                    if self._closed:
                        return
                continue
            except Exception:
                return
            try:
                if future.isCancellationRequested() or not future._begin():
                    future._complete_cancelled()
                    continue
                with self._lock:
                    self._active += 1
                try:
                    result = runnable.run()
                except Exception as exc:
                    future._complete(exception=exc)
                else:
                    future._complete(result=result)
                finally:
                    with self._lock:
                        self._active = max(0, self._active - 1)
            finally:
                try:
                    self._queue.task_done()
                except Exception:
                    pass

    def clear(self):
        """Cancel pending work without interrupting already-running callbacks."""
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                item[3]._complete_cancelled()
            finally:
                try:
                    self._queue.task_done()
                except Exception:
                    pass

    def waitForDone(self, timeout=None):
        """Wait until queued/running work completes; primarily for tests/tools."""
        if timeout is None:
            self._queue.join()
            return True
        deadline = threading.Event()
        # ``Queue.join`` has no timeout; poll bounded observable state instead.
        import time
        end = time.monotonic() + max(0.0, float(timeout))
        while time.monotonic() < end:
            if self._queue.unfinished_tasks == 0 and self.activeThreadCount() == 0:
                return True
            deadline.wait(min(.01, max(0.0, end - time.monotonic())))
        return self._queue.unfinished_tasks == 0 and self.activeThreadCount() == 0

    def close(self, *, wait=False, cancelPending=True):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            workers = tuple(self._workers)
        if cancelPending:
            self.clear()
        # Workers use a short timed queue wait, so closing never has to inject
        # sentinel jobs into a potentially full priority queue. With
        # cancelPending=False they naturally drain queued jobs before exiting.
        if wait:
            for worker in workers:
                worker.join()


class QtConcurrent:
    """Namespace mirroring ``QtConcurrent.run`` for simple callables."""

    @staticmethod
    def run(callback, *args, pool=None, after=None, **kwargs):
        return (pool or QThreadPool.globalInstance()).start(
            callback, *args, after=after, **kwargs)


__all__ = ["QRunnable", "QFuture", "QFutureWatcher", "QThreadPool", "QtConcurrent"]
