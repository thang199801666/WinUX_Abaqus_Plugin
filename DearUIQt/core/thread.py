"""Qt-style event-loop thread for backend-neutral DearUIQt workers.

The QThread object itself belongs to the creating thread, matching Qt. Objects
moved to it use one QEventDispatcher owned by the worker thread; queued signals,
QTimer and QMetaObject.invokeMethod therefore share the same scheduler contract
as the GUI/core dispatcher instead of maintaining a second deadline heap.
"""
from __future__ import annotations

import itertools
import threading
import time

from .dispatcher import QEventDispatcher
from .object import QObject, Signal


class QThread(QObject):
    """Small reusable event-loop thread with Qt-like lifecycle semantics."""

    _ids = itertools.count(1)

    def __init__(self, parent=None, *, name=None, daemon=True, after=None):
        if after is None and parent is None:
            try:
                from .application import QCoreApplication
                application = QCoreApplication.instance()
                if application is not None and application.threadId() == threading.get_ident():
                    after = getattr(application, "_after", None)
            except Exception:
                pass
        super().__init__(parent, after=after)
        self.started = Signal(self)
        self.finished = Signal(self)
        self.exceptionRaised = Signal(self)
        self._name = str(name or "QThread-{}".format(next(self._ids)))
        self._daemon = bool(daemon)
        self._condition = threading.Condition()
        self._thread = None
        self._worker_ident = None
        self._running = False
        self._quit_requested = False
        self._exit_code = 0
        self._interruption_requested = False
        self._deferred_deletes = []
        self._deferred_delete_wake_pending = False
        self._dispatcher = None
        # Calls may be queued before start(), exactly like the historical
        # QThread scheduler. Keep absolute due times so a delayed call that has
        # already expired is ready immediately when the worker starts.
        self._prestart_calls = []
        self._external_tokens = itertools.count(1)
        self._token_map = {}
        self._cancelled_prestart = set()
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
            self._exit_code = 0
            self._interruption_requested = False
            self._deferred_deletes.clear()
            self._deferred_delete_wake_pending = False
            thread = threading.Thread(target=self._bootstrap, name=self._name, daemon=self._daemon)
            self._thread = thread
            try:
                thread.start()
            except Exception:
                self._thread = None
                raise
            return True

    def _wake_worker(self):
        with self._condition:
            self._condition.notify_all()

    def _bootstrap(self):
        dispatcher = QEventDispatcher()
        dispatcher.setWakeCallback(self._wake_worker)
        with self._condition:
            self._worker_ident = threading.get_ident()
            self._running = True
            self._dispatcher = dispatcher
            pending = self._prestart_calls
            self._prestart_calls = []
            cancelled = set(self._cancelled_prestart)
            self._cancelled_prestart.clear()
            self._condition.notify_all()
        now = time.monotonic()
        for external, due, callback, args, priority in pending:
            if external in cancelled:
                self._token_map.pop(external, None)
                continue
            remaining_ms = max(0.0, due - now) * 1000.0
            internal = dispatcher.after(
                remaining_ms, self._deliver_scheduled, external, callback, args,
                priority=priority)
            with self._condition:
                if external in self._token_map:
                    self._token_map[external] = internal
        try:
            self.started.emit()
            self.run()
        finally:
            try:
                self.finished.emit()
            finally:
                self._drain_deferred_deletes(final=True)
                dispatcher.close()
                with self._condition:
                    self._running = False
                    self._worker_ident = None
                    self._dispatcher = None
                    self._token_map.clear()
                    self._cancelled_prestart.clear()
                    self._deferred_deletes.clear()
                    self._deferred_delete_wake_pending = False
                    self._condition.notify_all()

    def run(self):
        """Default QThread run implementation: execute the retained event loop."""
        self.exec()

    def _callback_error(self, callback, exc):
        try:
            self.exceptionRaised.emit(exc)
        except Exception:
            pass

    def exec(self):
        while True:
            with self._condition:
                if self._quit_requested:
                    return int(self._exit_code)
                dispatcher = self._dispatcher
            if dispatcher is None:
                return int(self._exit_code)
            dispatcher.processEvents(on_error=self._callback_error)
            with self._condition:
                if self._quit_requested:
                    return int(self._exit_code)
                delay_ms = dispatcher.nextDeadlineMs()
                if delay_ms is None:
                    self._condition.wait()
                elif delay_ms > 0:
                    self._condition.wait(delay_ms / 1000.0)
                # due work loops immediately without sleeping

    def _deliver_scheduled(self, external, callback, args):
        with self._condition:
            self._token_map.pop(external, None)
        callback(*args)

    def after(self, delay_ms, callback, *args, priority=0):
        """Schedule a callback on the worker's canonical QEventDispatcher."""
        if not callable(callback):
            raise TypeError("QThread scheduler callback must be callable")
        delay_ms = max(0, int(delay_ms))
        priority = int(priority or 0)
        external = next(self._external_tokens)
        due = time.monotonic() + delay_ms / 1000.0
        with self._condition:
            if self._deleted or self._quit_requested:
                raise RuntimeError("QThread event loop is not accepting work")
            dispatcher = self._dispatcher
            if dispatcher is None:
                self._prestart_calls.append((external, due, callback, args, priority))
                self._token_map[external] = None
                return external
        internal = dispatcher.after(
            delay_ms, self._deliver_scheduled, external, callback, args,
            priority=priority)
        if internal is None:
            raise RuntimeError("QThread event loop is not accepting work")
        with self._condition:
            self._token_map[external] = internal
            self._condition.notify_all()
        return external

    def after_cancel(self, token):
        if token is None:
            return False
        with self._condition:
            if token not in self._token_map:
                return False
            internal = self._token_map.pop(token)
            dispatcher = self._dispatcher
            if internal is None:
                self._cancelled_prestart.add(token)
                self._condition.notify_all()
                return True
        cancelled = bool(dispatcher is not None and dispatcher.after_cancel(internal))
        with self._condition:
            self._condition.notify_all()
        return cancelled

    def post(self, callback, *args, priority=0):
        return self.after(0, callback, *args, priority=priority)

    def nextDeadlineMs(self):
        """Expose the same deadline contract as QEventDispatcher."""
        with self._condition:
            dispatcher = self._dispatcher
            prestart = [entry for entry in self._prestart_calls
                        if entry[0] in self._token_map]
        if dispatcher is not None:
            return dispatcher.nextDeadlineMs()
        if not prestart:
            return None
        now = time.monotonic()
        earliest = min(entry[1] for entry in prestart)
        return max(0.0, earliest - now) * 1000.0

    def diagnosticsSnapshot(self):
        """Return side-effect-free worker scheduler/lifecycle diagnostics."""
        with self._condition:
            dispatcher = self._dispatcher
            prestart = [entry for entry in self._prestart_calls
                        if entry[0] in self._token_map]
            pending_prestart = len(prestart)
            priorities = [entry[4] for entry in prestart]
            running = bool(self._running)
            finished = self._thread is not None and not self._running
            worker_ident = self._worker_ident
            quit_requested = bool(self._quit_requested)
            interrupted = bool(self._interruption_requested)
            deferred_count = len(self._deferred_deletes)
        if dispatcher is not None:
            sched = dispatcher.diagnosticsSnapshot()
            pending = sched["pending_count"]
            next_ms = sched["next_deadline_ms"]
            high = sched["highest_priority"]
        else:
            pending = pending_prestart
            next_ms = self.nextDeadlineMs()
            high = max(priorities) if priorities else None
        return {
            "name": self._name,
            "running": running,
            "finished": finished,
            "worker_thread_id": worker_ident,
            "affinity_id": self._affinity_id,
            "quit_requested": quit_requested,
            "interruption_requested": interrupted,
            "pending_count": pending,
            "prestart_pending_count": pending_prestart,
            "deferred_delete_count": deferred_count,
            "next_deadline_ms": next_ms,
            "highest_priority": high,
            "uses_qeventdispatcher": dispatcher is not None,
        }

    def deferDelete(self, callback, *args):
        if not callable(callback):
            raise TypeError("deferred delete callback must be callable")
        schedule_wake = False
        with self._condition:
            if self._deleted:
                return False
            self._deferred_deletes.append((callback, args))
            if not self._quit_requested and not self._deferred_delete_wake_pending:
                self._deferred_delete_wake_pending = True
                schedule_wake = True
        if schedule_wake:
            try:
                self.after(0, self._drain_deferred_deletes)
            except RuntimeError:
                pass
        return True

    def _drain_deferred_deletes(self, final=False):
        while True:
            with self._condition:
                self._deferred_delete_wake_pending = False
                if not self._deferred_deletes:
                    return
                pending = self._deferred_deletes
                self._deferred_deletes = []
            for callback, args in pending:
                try:
                    callback(*args)
                except Exception as exc:
                    try:
                        self.exceptionRaised.emit(exc)
                    except Exception:
                        pass
            if not final:
                return

    def exit(self, return_code=0):
        with self._condition:
            self._exit_code = int(return_code)
            self._quit_requested = True
            self._condition.notify_all()
        return True

    def quit(self):
        return self.exit(0)

    def isCurrentThread(self):
        ident = self.workerThreadId()
        return ident is not None and ident == threading.get_ident()

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
        super().delete()


__all__ = ["QThread"]
