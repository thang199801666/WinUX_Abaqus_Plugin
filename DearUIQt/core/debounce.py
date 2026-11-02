"""QObject-owned trailing-edge debounce for search, validation and previews."""
import threading

from .object import QObject
from .timer import QTimer


class QDebouncer(QObject):
    """DearUIQt extension: reuse one timer and keep only the newest arguments.

    Calls must be made on the owner/context thread. Worker bursts can first use
    LatestCallQueue or a queued signal. Cancellation drops pending arguments;
    deletion also releases the reusable callback and its captured state.
    """

    def __init__(self, callback, interval=150, parent=None, *, after=None):
        if not callable(callback):
            raise TypeError('debounce callback must be callable')
        interval = QTimer._milliseconds(interval)
        receiver = getattr(callback, '__self__', None)
        if isinstance(receiver, QObject):
            if receiver._deleted:
                raise RuntimeError('cannot debounce a deleted callback receiver')
            if receiver.threadId() != threading.get_ident():
                raise RuntimeError('debouncer requires the callback receiver thread')
            if parent is None:
                parent = receiver
        if parent is not None:
            if not isinstance(parent, QObject):
                raise TypeError('debouncer parent must be a QObject')
            if parent._deleted or parent.threadId() != threading.get_ident():
                raise RuntimeError('debouncer requires a live parent on its owning thread')
        scheduler = after if after is not None else getattr(parent, '_after', None)
        if scheduler is None:
            from .application import QApplication
            application = QApplication.instance()
            if application is not None:
                if application.threadId() != threading.get_ident():
                    raise RuntimeError('debouncer requires the application thread')
                scheduler = application._after
        if not callable(scheduler):
            raise RuntimeError('debouncer requires a UI scheduler')
        super().__init__(parent=parent, after=scheduler)
        self._callback = callback
        self._pending = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(interval)
        self._timer.timeout.connect(self._deliver)
        if isinstance(receiver, QObject):
            receiver.destroyed.connect(self._receiver_destroyed)

    def _receiver_destroyed(self, *_args):
        self.delete()

    def _require_thread(self):
        if threading.get_ident() != self.threadId():
            raise RuntimeError('debouncer operations require the owning thread')

    def trigger(self, *args, **kwargs):
        """Replace pending arguments and restart the quiet-period deadline."""
        self._require_thread()
        if self._deleted:
            raise RuntimeError('cannot trigger a deleted debouncer')
        previous = self._pending
        self._pending = (args, kwargs)
        try:
            self._timer.start()
        except Exception:
            self._pending = None
            raise
        finally:
            del previous

    def isPending(self):
        return not self._deleted and self._pending is not None

    def interval(self):
        return self._timer.interval()

    def setInterval(self, milliseconds):
        self._require_thread()
        if self._deleted:
            raise RuntimeError('cannot configure a deleted debouncer')
        self._timer.setInterval(milliseconds)

    def cancel(self):
        """Stop pending delivery, retaining the callback for later triggers."""
        self._require_thread()
        if self._deleted:
            return False
        pending, self._pending = self._pending, None
        self._timer.stop()
        return pending is not None

    def flush(self):
        """Run pending work now on the owner thread, at most once."""
        self._require_thread()
        if not self.isPending():
            return False
        self._timer.stop()
        self._deliver()
        return True

    def _deliver(self):
        if not self.isPending():
            return
        pending, self._pending = self._pending, None
        args, kwargs = pending
        receiver = getattr(self._callback, '__self__', None)
        if isinstance(receiver, QObject) and receiver._deleted:
            self.delete()
            return
        self._callback(*args, **kwargs)

    def delete(self):
        self._require_thread()
        if self._deleted:
            return
        self.cancel()
        self._callback = None
        super().delete()


__all__ = ['QDebouncer']
