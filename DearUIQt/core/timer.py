"""QObject-owned timers driven by the host UI scheduler, not worker threads."""
import threading

from .object import QObject, Signal


class _TimerTick:
    """One consumable scheduler callback whose timer reference is detachable."""

    __slots__ = ('_timer', '_generation')

    def __init__(self, timer, generation):
        self._timer = timer
        self._generation = generation

    def cancel(self):
        self._timer = None

    def __call__(self):
        timer = self._timer
        if timer is None:
            return
        # Reject a broken scheduler before consuming the live delivery.
        timer._require_thread()
        self._timer = None
        timer._tick(self._generation)


class QTimer(QObject):
    def __init__(self, parent=None, *, after=None):
        super().__init__(parent, after=after)
        self.timeout = Signal(self)
        self._interval = 0
        self._single_shot = False
        self._active = False
        self._generation = 0
        self._scheduled_handle = None
        self._scheduled_tick = None

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

    @staticmethod
    def singleShot(milliseconds, callback, *, context=None, after=None):
        """Queue a one-off callback and return its cancellable timer handle.

        An explicit QObject context (or an inferred bound-method receiver) owns
        the timer: deleting it cancels delivery and releases callback references.
        With no supplied scheduler, use the context or current QApplication.
        The helper deletes itself after delivery, including when the slot raises.
        Call ``delete()`` on the returned handle to cancel and release it early.
        """
        milliseconds = QTimer._milliseconds(milliseconds)
        if not callable(callback):
            raise TypeError('singleShot callback must be callable')
        receiver = getattr(callback, '__self__', None)
        if isinstance(receiver, QObject) and receiver.threadId() != threading.get_ident():
            raise RuntimeError('singleShot requires the callback receiver thread')
        if context is None and isinstance(receiver, QObject):
            context = receiver
        if context is not None:
            if not isinstance(context, QObject):
                raise TypeError('singleShot context must be a QObject')
            if context._deleted:
                raise RuntimeError('cannot schedule for a deleted context')
            if context.threadId() != threading.get_ident():
                raise RuntimeError('singleShot requires the context thread')
        scheduler = after if after is not None else getattr(context, '_after', None)
        if scheduler is None:
            from .application import QApplication
            application = QApplication.instance()
            if application is not None:
                if application.threadId() != threading.get_ident():
                    raise RuntimeError('singleShot requires the application thread')
                scheduler = application._after
        if not callable(scheduler):
            raise RuntimeError('singleShot requires a UI scheduler')
        timer = QTimer(context, after=scheduler)
        timer._dispose_after_timeout = True
        try:
            timer.setSingleShot(True)
            timer.timeout.connect(callback)
            timer.start(milliseconds)
        except Exception:
            timer.delete()
            raise
        return timer

    def _cancel_scheduled_tick(self):
        """Cancel the host callback when its scheduler exposes ``after_cancel``.

        Detach the timer even when host cancellation is unavailable or fails;
        the pending callback then owns only an inert tick shell. Generation
        checks remain the stale-delivery fallback, while cancel-capable hosts
        can also remove that shell from their queues immediately.
        """
        tick = self._scheduled_tick
        self._scheduled_tick = None
        if tick is not None:
            tick.cancel()
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
        # A repeating zero timer needs a lower bound on legacy drain-all hosts.
        # One-off zero timers are safe to queue immediately, never inline.
        tick = _TimerTick(self, generation)
        self._scheduled_tick = tick
        try:
            self._scheduled_handle = self._after(
                max(0 if self._single_shot else 1, self._interval), tick)
        except Exception:
            # A host may retain the callback even when scheduling raises.
            tick.cancel()
            if self._scheduled_tick is tick:
                self._scheduled_tick = None
            raise

    def _tick(self, generation):
        self._require_thread()
        if generation == self._generation:
            self._scheduled_handle = None
            self._scheduled_tick = None
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
            if getattr(self, '_dispose_after_timeout', False) and not self.isActive():
                self.delete()

    def delete(self):
        if self._deleted:
            return
        self.stop()
        super().delete()


__all__ = ["QTimer"]
