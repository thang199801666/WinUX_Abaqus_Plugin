"""Semantic dock command bus for :class:`QMainWindow`.

The bus keeps public QMainWindow docking APIs source-compatible while routing
all mutations through one observable command boundary.  DockManager remains the
canonical topology engine; this object only owns command ordering, diagnostics
and signals.
"""
from __future__ import annotations

from ..core.object import QObject, Signal
from .command import QDockCommand


class QMainWindowDockCommandBus(QObject):
    """Serialize semantic dock commands for one main window.

    String commands remain supported for compatibility.  Internally every
    execution is represented by :class:`QDockCommand`, giving programmatic,
    gesture and native transition paths the same diagnostics contract.
    """

    def __init__(self, executor, parent=None):
        if not callable(executor):
            raise TypeError("dock command executor must be callable")
        super().__init__(parent=parent)
        self._executor = executor
        self._executing = False
        self._sequence = 0
        self._current = None
        self._last = None
        self._history = None
        self.commandRequested = Signal(self)
        self.commandStarted = Signal(self)
        self.commandFinished = Signal(self)
        self.commandFailed = Signal(self)
        self.commandObjectRequested = Signal(self)
        self.commandObjectStarted = Signal(self)
        self.commandObjectFinished = Signal(self)
        self.commandObjectFailed = Signal(self)


    def setHistory(self, history):
        self._history = history
        return history

    def history(self):
        return self._history

    def isExecuting(self):
        return bool(self._executing)

    def currentCommandObject(self):
        return self._current

    def lastCommandObject(self):
        return self._last

    def currentCommand(self):
        return None if self._current is None else self._current.snapshot()

    def lastCommand(self):
        return None if self._last is None else self._last.snapshot()

    def execute(self, command, **payload):
        if self._executing:
            raise RuntimeError("nested QMainWindow dock command is not allowed")
        item = QDockCommand.coerce(command, payload, source="qmainwindow")
        self._sequence += 1
        item._assign_sequence(self._sequence)._requested()
        self._current = item
        name = item.command()
        args = item.payload()
        self.commandRequested.emit(name, dict(args), self._sequence)
        self.commandObjectRequested.emit(item)
        self._executing = True
        item._running()
        self.commandStarted.emit(name, dict(args), self._sequence)
        self.commandObjectStarted.emit(item)
        history = self._history
        before = None
        if history is not None and not history.isRestoring():
            before = history.capture()
        try:
            result = self._executor(name, dict(args))
            item._finished(result)
            if history is not None and before is not None and not history.isRestoring():
                after = history.capture()
                history.record(item, before, after)
            self.commandFinished.emit(name, dict(args), result, self._sequence)
            self.commandObjectFinished.emit(item)
            return result
        except Exception as exc:
            item._failed(exc)
            self.commandFailed.emit(name, dict(args), exc, self._sequence)
            self.commandObjectFailed.emit(item)
            raise
        finally:
            self._executing = False
            self._last = item
            self._current = None

    executeCommand = execute
