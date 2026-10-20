"""QObject-owned timers driven by the host UI scheduler, not worker threads."""
import threading

from .object import QObject, Signal


class QTimer(QObject):
    def __init__(self, parent=None, *, after=None):
        super().__init__(parent, after=after)
        self.timeout = Signal(self)
        self._interval = 0
        self._single_shot = False
        self._active = False
        self._generation = 0
        self._scheduled_handle = None

    def _require_thread(self):
        if threading.get_ident() != self.threadId():
            raise RuntimeError("timer operations require the owning thread")

    @staticmethod
    def _milliseconds(value):
        if type(value) is not int or value < 0:
            raise ValueError("timer interval must be a non-negative integer")
        return value

    def interval(self):
        return self._interval

    def setInterval(self, milliseconds):
        self._require_thread()
        value = self._milliseconds(milliseconds)
        if self._deleted:
            raise RuntimeError("cannot configure a deleted timer")
        self._interval = value
        if self._active:
            self.start()

    def setSingleShot(self, single_shot):
        self._require_thread()
        if self._deleted:
            raise RuntimeError("cannot configure a deleted timer")
        self._single_shot = bool(single_shot)

    def isSingleShot(self):
        return self._single_shot

    def isActive(self):
        return self._active and not self._deleted

    def _cancel_scheduled_tick(self):
        """Cancel the host callback when its scheduler exposes ``after_cancel``.

        Generation checks remain the correctness fallback for simple schedulers,
        but cancel-capable UI hosts can release the bound callback immediately.
        This mirrors Qt's timer lifecycle and prevents stopped long-interval
        timers from retaining a dialog until their obsolete due time arrives.
        """
        handle = self._scheduled_handle
        self._scheduled_handle = None
        if handle is None or self._after is None:
            return False
        owner = getattr(self._after, "__self__", None)
        cancel = getattr(owner, "after_cancel", None)
        if not callable(cancel):
            return False
        try:
            cancel(handle)
            return True
        except Exception:
            # Stale/foreign scheduler handles are harmless because generation
            # validation still suppresses the obsolete callback if it runs.
            return False

    def start(self, milliseconds=None):
        self._require_thread()
        if self._deleted:
            raise RuntimeError("cannot start a deleted timer")
        value = self._interval if milliseconds is None else self._milliseconds(milliseconds)
        if self._after is None:
            raise RuntimeError("timer requires a UI scheduler")
        self._cancel_scheduled_tick()
        self._interval = value
        self._generation += 1
        self._active = True
        try:
            self._schedule(self._generation)
        except Exception:
            self._active = False
            self._generation += 1
            self._scheduled_handle = None
            raise

    def stop(self):
        self._require_thread()
        self._active = False
        self._generation += 1
        self._cancel_scheduled_tick()

    def _schedule(self, generation):
        # Host schedulers drain multiple due callbacks per pass. A 1 ms lower
        # bound prevents a zero timer from spinning within that same pass.
        self._scheduled_handle = self._after(
            max(1, self._interval), self._tick, generation)

    def _tick(self, generation):
        self._require_thread()
        if generation == self._generation:
            self._scheduled_handle = None
        if not self.isActive() or generation != self._generation:
            return
        if self._single_shot:
            self._active = False
        try:
            self.timeout.emit()
        finally:
            if self.isActive() and generation == self._generation:
                try:
                    self._schedule(generation)
                except Exception:
                    self._active = False
                    self._generation += 1
                    raise

    def delete(self):
        if self._deleted:
            return
        self.stop()
        super().delete()


__all__ = ["QTimer"]
