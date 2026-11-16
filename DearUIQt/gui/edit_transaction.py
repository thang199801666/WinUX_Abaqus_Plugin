"""Qt-style explicit edit transaction for pointer/gesture driven editors.

The transaction is intentionally renderer-neutral.  A client begins a gesture,
updates preview state zero or more times, then either commits one mutation or
cancels the gesture.  Optional snapshot/restore callbacks make live-edit clients
rollback-safe without forcing them to create an undo command per frame.
"""
from __future__ import annotations

import copy

from ..core.object import QObject, Signal


class QEditTransaction(QObject):
    """Explicit begin/update/commit/cancel lifecycle for one interactive edit."""

    Idle = "idle"
    Active = "active"
    Committed = "committed"
    Canceled = "canceled"
    Failed = "failed"

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.started = Signal(self)
        self.updated = Signal(self)
        self.committed = Signal(self)
        self.canceled = Signal(self)
        self.failed = Signal(self)
        self.activeChanged = Signal(self)
        self._state = self.Idle
        self._label = ""
        self._context = None
        self._value = None
        self._snapshot = None
        self._restore = None

    def state(self):
        return self._state

    def isActive(self):
        return self._state == self.Active

    def label(self):
        return self._label

    def context(self):
        return copy.deepcopy(self._context)

    def value(self):
        return copy.deepcopy(self._value)

    def snapshot(self):
        return copy.deepcopy(self._snapshot)

    def begin(self, label="Edit", *, context=None, value=None, snapshot=None,
              capture=None, restore=None):
        if self.isActive():
            self.cancel()
        if callable(capture):
            snapshot = capture()
        self._label = str(label or "Edit")
        self._context = copy.deepcopy(context)
        self._value = copy.deepcopy(value)
        self._snapshot = copy.deepcopy(snapshot)
        self._restore = restore if callable(restore) else None
        self._state = self.Active
        self.activeChanged.emit(True)
        self.started.emit(self._label, self.context())
        return True

    def update(self, value=None, *, apply=None):
        if not self.isActive():
            return False
        try:
            if callable(apply):
                apply(value)
            self._value = copy.deepcopy(value)
            self.updated.emit(self.value(), self.context())
            return True
        except Exception as exc:
            self._state = self.Failed
            self.failed.emit(exc, self.context())
            self.activeChanged.emit(False)
            raise

    def commit(self, *, value=None, apply=None):
        if not self.isActive():
            return False
        if value is not None:
            self._value = copy.deepcopy(value)
        try:
            result = apply(self.value()) if callable(apply) else None
        except Exception as exc:
            try:
                self._rollback()
            finally:
                self._state = self.Failed
                self.failed.emit(exc, self.context())
                self.activeChanged.emit(False)
            raise
        context = self.context()
        final_value = self.value()
        self._state = self.Committed
        self._restore = None
        self.committed.emit(final_value, context, result)
        self.activeChanged.emit(False)
        return True

    def _rollback(self):
        if self._restore is not None:
            self._restore(copy.deepcopy(self._snapshot))

    def cancel(self):
        if not self.isActive():
            return False
        context = self.context()
        try:
            self._rollback()
        finally:
            self._state = self.Canceled
            self._restore = None
            self.canceled.emit(context)
            self.activeChanged.emit(False)
        return True


__all__ = ["QEditTransaction"]
