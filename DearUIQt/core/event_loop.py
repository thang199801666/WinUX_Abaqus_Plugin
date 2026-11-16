"""Qt-style nested event loop built on the process-global QApplication turn.

DearUIQt keeps one renderer/native host loop.  QEventLoop therefore does not
create another renderer or worker thread: it repeatedly drains QApplication's
posted-event/native-update transaction and optionally lets the owning native
host pump one input/render turn.  This mirrors Qt's nested event-loop contract
without reintroducing per-dialog workers.
"""
from __future__ import annotations

import threading
import time

from .object import QObject


class QEventLoop(QObject):
    """A small Qt-compatible nested event loop.

    ``pump`` is a DearUIQt host bridge, not part of Qt's public API.  It is used
    by QDialog.exec() so the existing native/DearPyGui host can process one
    platform turn while QApplication remains the sole logical event dispatcher.
    Library code should normally omit it and use QApplication's host integration.
    """

    def __init__(self, parent=None, *, application=None, pump=None):
        super().__init__(parent=parent, after=getattr(application, "_after", None))
        self._application = application
        # ``pump`` remains a compatibility escape hatch for tests/legacy hosts.
        # Production code should register one QApplication.setHostTurn() instead.
        self._pump = pump
        self._running = False
        self._exit_code = 0
        self._owner_thread = threading.get_ident()

    def isRunning(self):
        return bool(self._running)

    def processEvents(self, max_events=None):
        app = self._application
        if app is None:
            from .application import QCoreApplication
            app = QCoreApplication.instance()
        if app is None:
            return 0
        if threading.get_ident() != app.threadId():
            raise RuntimeError("QEventLoop.processEvents requires QCoreApplication thread")
        return app.processEvents(max_events=max_events)

    def exec(self):
        if self._deleted:
            raise RuntimeError("cannot exec a deleted QEventLoop")
        if self._running:
            raise RuntimeError("QEventLoop is already running")
        app = self._application
        if app is None:
            from .application import QCoreApplication
            app = QCoreApplication.instance()
            self._application = app
        if app is None:
            raise RuntimeError("QEventLoop.exec requires a QCoreApplication")
        if threading.get_ident() != app.threadId():
            raise RuntimeError("QEventLoop.exec requires QCoreApplication thread")

        self._running = True
        self._exit_code = 0
        idle_turns = 0
        # Nested dialog loops must continue pumping the one renderer/native host,
        # but a non-blocking host pump should not make an otherwise idle dialog
        # spin at ~1000 turns/sec.  Back off toward one 120 Hz frame while idle
        # and reset immediately when Qt work appears.  The short first steps
        # preserve first-input responsiveness; the 8 ms ceiling avoids visible
        # throttling on high-refresh displays.
        idle_backoff = (0.001, 0.002, 0.004, 0.008)
        try:
            while self._running and not self._deleted and not getattr(app, "_quitting", False):
                processed = app.processEvents()
                if not self._running:
                    break
                pump = self._pump
                if callable(pump):
                    pump()
                else:
                    app.processHostTurn()
                # A native host callback may synchronously close the dialog.
                # Do not add an unnecessary idle sleep after the nested loop has
                # already been asked to exit.
                if not self._running:
                    break
                if processed == 0:
                    delay = idle_backoff[min(idle_turns, len(idle_backoff) - 1)]
                    idle_turns += 1
                    time.sleep(delay)
                else:
                    idle_turns = 0
            return int(self._exit_code)
        finally:
            self._running = False

    exec_ = exec

    def exit(self, returnCode=0):
        self._exit_code = int(returnCode)
        self._running = False

    def quit(self):
        self.exit(0)

    def delete(self):
        # Qt permits an event loop object to be destroyed only after callers
        # have unwound from exec().  Stop first so a parent teardown cannot
        # leave a nested pump alive on a dead QObject subtree.
        self._running = False
        return super().delete()


__all__ = ["QEventLoop"]
