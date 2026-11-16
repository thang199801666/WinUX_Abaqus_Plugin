"""Qt-style socket readiness notifier driven by the QApplication scheduler.

The notifier intentionally owns no worker thread.  It performs a non-blocking
readiness probe on a QTimer tick, so delivery stays ordered with the same
QApplication event queue used by dialogs, timers, queued signals and deferred
deletes.  This is the portable fallback used until a backend supplies a native
FD/handle notifier.
"""
from __future__ import annotations

import select
import threading

from .object import QObject, Signal
from .timer import QTimer


class QSocketNotifier(QObject):
    Read = 0
    Write = 1
    Exception = 2

    def __init__(self, socket, type=Read, parent=None, *, after=None,
                 enabled=True, interval=20):
        super().__init__(parent, after=after)
        if type not in (self.Read, self.Write, self.Exception):
            raise ValueError("invalid socket notifier type")
        self.activated = Signal(self)
        self._socket = socket
        self._type = int(type)
        self._enabled = False
        self._interval = self._validate_interval(interval)
        self._timer = None
        if enabled:
            self.setEnabled(True)

    @staticmethod
    def _validate_interval(value):
        if type(value) is not int or value <= 0:
            raise ValueError("socket notifier interval must be a positive integer")
        return value

    def _require_thread(self):
        if threading.get_ident() != self.threadId():
            raise RuntimeError("socket notifier operations require the owning thread")

    def socket(self):
        return self._socket

    def type(self):
        return self._type

    def isEnabled(self):
        return self._enabled and not self._deleted

    def checkInterval(self):
        return self._interval

    def setCheckInterval(self, milliseconds):
        self._require_thread()
        self._interval = self._validate_interval(milliseconds)
        if self._timer is not None and self._timer.isActive():
            self._timer.setInterval(self._interval)

    def _scheduler(self):
        if callable(self._after):
            return self._after
        try:
            from .application import QCoreApplication
            application = QCoreApplication.instance()
        except Exception:
            application = None
        if application is None or application.threadId() != self.threadId():
            return None
        scheduler = getattr(application, "_after", None)
        return scheduler if callable(scheduler) else None

    def setEnabled(self, enabled):
        self._require_thread()
        if self._deleted:
            raise RuntimeError("cannot configure a deleted socket notifier")
        enabled = bool(enabled)
        if enabled == self._enabled:
            return
        if not enabled:
            self._enabled = False
            if self._timer is not None:
                self._timer.stop()
            return
        scheduler = self._scheduler()
        if scheduler is None:
            raise RuntimeError("socket notifier requires a QCoreApplication/UI scheduler")
        timer = self._timer
        if timer is None or timer._deleted:
            timer = QTimer(self, after=scheduler)
            timer.timeout.connect(self._probe)
            self._timer = timer
        self._enabled = True
        timer.start(self._interval)

    def _probe(self):
        if not self.isEnabled():
            return
        target = self._socket
        try:
            if self._type == self.Read:
                ready = bool(select.select([target], [], [], 0)[0])
            elif self._type == self.Write:
                ready = bool(select.select([], [target], [], 0)[1])
            else:
                ready = bool(select.select([], [], [target], 0)[2])
        except (OSError, ValueError, TypeError):
            # Invalid/closed descriptors behave like Qt notifiers whose backing
            # socket disappeared: disable delivery rather than spin forever.
            self.setEnabled(False)
            return
        if ready:
            descriptor = target
            fileno = getattr(target, "fileno", None)
            if callable(fileno):
                try:
                    descriptor = fileno()
                except Exception:
                    descriptor = target
            self.activated.emit(descriptor)

    def delete(self):
        if self._deleted:
            return
        if self._timer is not None and not self._timer._deleted:
            self._timer.stop()
        self._enabled = False
        super().delete()


__all__ = ["QSocketNotifier"]
