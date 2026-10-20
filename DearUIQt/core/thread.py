"""Qt-style event-loop thread for backend-neutral DearUIQt workers.

The QThread object itself belongs to the creating thread, matching Qt. Objects
moved to it use the worker event loop as their scheduler; queued signals,
QTimer and QMetaObject.invokeMethod therefore share one affinity mechanism
instead of every feature allocating a custom worker/callback bridge.
"""
from __future__ import annotations

import heapq
import itertools
import threading
import time

from .object import QObject, Signal


class QThread(QObject):
    """Small reusable event-loop thread with Qt-like lifecycle semantics."""

    _ids = itertools.count(1)

    def __init__(self, parent=None, *, name=None, daemon=True, after=None):
        super().__init__(parent, after=after)
        self.started = Signal(self)
        self.finished = Signal(self)
        self.exceptionRaised = Signal(self)
        self._name = str(name or "QThread-{}".format(next(self._ids)))
        self._daemon = bool(daemon)
        self._condition = threading.Condition()
        self._queue = []
        self._sequence = itertools.count()
        self._cancelled = set()
        self._thread = None
        self._worker_ident = None
        self._running = False
        self._quit_requested = False
        self._interruption_requested = False
        # Before start there is no OS thread id. A stable negative affinity id
        # still lets AutoConnection correctly recognize the object as foreign
        # to the creator thread and queue work until the event loop starts.
        self._affinity_id = -abs(id(self))

    @staticmethod
    def currentThreadId():
        return threading.get_ident()

    def affinityId(self):
        return self._affinity_id

    def workerThreadId(self):
        with self._condition:
            return self._worker_ident

    def isRunning(self):
        with self._condition:
            return bool(self._running)

    def isFinished(self):
        with self._condition:
            return self._thread is not None and not self._running

    def isInterruptionRequested(self):
        with self._condition:
            return bool(self._interruption_requested)

    def requestInterruption(self):
        with self._condition:
            self._interruption_requested = True
            self._condition.notify_all()

    def start(self):
        if self._deleted:
            raise RuntimeError("cannot start a deleted QThread")
        with self._condition:
            if self._running:
                return False
            if self._thread is not None and self._thread.is_alive():
                return False
            self._quit_requested = False
            self._interruption_requested = False
            thread = threading.Thread(target=self._bootstrap, name=self._name, daemon=self._daemon)
            self._thread = thread
            try:
                thread.start()
            except Exception:
                self._thread = None
                raise
            return True

    def _bootstrap(self):
        with self._condition:
            self._worker_ident = threading.get_ident()
            self._running = True
            self._condition.notify_all()
        try:
            self.started.emit()
            self.run()
        finally:
            with self._condition:
                self._running = False
                self._worker_ident = None
                self._queue.clear()
                self._cancelled.clear()
                self._condition.notify_all()
            self.finished.emit()

    def run(self):
        """Default QThread run implementation: execute the retained event loop."""
        self.exec()

    def exec(self):
        while True:
            callback = None
            args = ()
            with self._condition:
                while True:
                    if self._quit_requested:
                        return 0
                    now = time.monotonic()
                    while self._queue and self._queue[0][2] in self._cancelled:
                        _deadline, _seq, token, _callback, _args = heapq.heappop(self._queue)
                        self._cancelled.discard(token)
                    if not self._queue:
                        self._condition.wait()
                        continue
                    deadline, _seq, token, callback, args = self._queue[0]
                    delay = deadline - now
                    if delay > 0:
                        self._condition.wait(delay)
                        continue
                    heapq.heappop(self._queue)
                    if token in self._cancelled:
                        self._cancelled.discard(token)
                        callback = None
                        continue
                    break
            if callback is not None:
                try:
                    callback(*args)
                except Exception as exc:
                    # A worker callback exception must not tear down the entire
                    # affinity event loop. Expose it as a retained signal so a
                    # host may log/report the fault without one callback killing
                    # every other object sharing the worker event loop.
                    try:
                        self.exceptionRaised.emit(exc)
                    except Exception:
                        pass
                    continue

    def after(self, delay_ms, callback, *args):
        """Schedule a callback on the worker event loop, host-after style."""
        if not callable(callback):
            raise TypeError("QThread scheduler callback must be callable")
        delay_ms = max(0, int(delay_ms))
        token = next(self._sequence)
        deadline = time.monotonic() + (delay_ms / 1000.0)
        with self._condition:
            if self._deleted or self._quit_requested:
                raise RuntimeError("QThread event loop is not accepting work")
            heapq.heappush(self._queue, (deadline, token, token, callback, args))
            self._condition.notify_all()
        return token

    def after_cancel(self, token):
        with self._condition:
            self._cancelled.add(token)
            self._condition.notify_all()
        return True

    def post(self, callback, *args):
        return self.after(0, callback, *args)

    def quit(self):
        with self._condition:
            self._quit_requested = True
            self._condition.notify_all()

    exit = quit

    def wait(self, timeout=None):
        thread = self._thread
        if thread is None:
            return True
        if threading.get_ident() == thread.ident:
            raise RuntimeError("QThread cannot wait on itself")
        seconds = None if timeout is None else max(0.0, float(timeout) / 1000.0)
        thread.join(seconds)
        return not thread.is_alive()

    def delete(self):
        if self._deleted:
            return
        self.quit()
        # Never synchronously wait here: QObject deletion is commonly driven by
        # a UI close path and must remain non-blocking. The daemon worker exits
        # promptly after the condition wake-up.
        super().delete()


__all__ = ["QThread"]
