"""Generic Qt-style property edit transactions with undo integration.

``QPropertyEditController`` bridges interactive editors to ``QEditTransaction``
and ``QUndoStack`` without teaching individual widgets about snapshot/history
mechanics.  It supports both preview-only and live updates, Escape/cancel
rollback and one committed undo command per edit transaction.
"""
from __future__ import annotations

import copy
import time

from ..core.object import QObject, Signal
from .edit_transaction import QEditTransaction
from .undo import QUndoCommand


def _clone(value):
    try:
        return copy.deepcopy(value)
    except Exception:
        return value


class QPropertyEditCommand(QUndoCommand):
    """Undo command for one retained property change.

    Adjacent compatible commands may merge when the same ``merge_key`` is used,
    the state is continuous and they fall inside ``merge_window`` seconds.
    """

    MergeCommandId = 0x51504544  # 'QPED'

    def __init__(self, setter, before, after, text="Edit", *, merge_key=None,
                 merge_window=0.65, timestamp=None):
        super().__init__(text)
        if not callable(setter):
            raise TypeError("setter must be callable")
        self._setter = setter
        self._before = _clone(before)
        self._after = _clone(after)
        self._merge_key = _clone(merge_key)
        self._merge_window = max(0.0, float(merge_window))
        self._timestamp = float(time.monotonic() if timestamp is None else timestamp)
        # Property commands are recorded after the UI already reached ``after``.
        self._skip_first_redo = True

    def before(self):
        return _clone(self._before)

    def after(self):
        return _clone(self._after)

    def mergeKey(self):
        return _clone(self._merge_key)

    def id(self):
        return self.MergeCommandId if self._merge_key is not None else -1

    def redo(self):
        if self._skip_first_redo:
            self._skip_first_redo = False
            return
        self._setter(_clone(self._after))

    def undo(self):
        self._setter(_clone(self._before))

    def mergeWith(self, other):
        if not isinstance(other, QPropertyEditCommand):
            return False
        if self._merge_key is None or other._merge_key != self._merge_key:
            return False
        if self._after != other._before:
            return False
        if other._timestamp - self._timestamp > max(self._merge_window, other._merge_window):
            return False
        self._after = _clone(other._after)
        self._timestamp = other._timestamp
        self.setText(other.text() or self.text())
        return True


class QPropertyEditController(QObject):
    """Reusable begin/update/commit/cancel controller for one property editor."""

    def __init__(self, getter=None, setter=None, *, undo_stack=None,
                 label="Edit", merge_key=None, merge_window=0.65, parent=None):
        super().__init__(parent=parent)
        self.started = Signal(self)
        self.updated = Signal(self)
        self.committed = Signal(self)
        self.canceled = Signal(self)
        self.failed = Signal(self)
        self.activeChanged = Signal(self)
        self._getter = getter if callable(getter) else None
        self._setter = setter if callable(setter) else None
        self._undo_stack = undo_stack
        self._label = str(label or "Edit")
        self._merge_key = merge_key
        self._merge_window = float(merge_window)
        self._before = None
        self._value = None
        self._transaction = QEditTransaction(parent=self)
        self._transaction.started.connect(self._tx_started, receiver=self)
        self._transaction.updated.connect(self._tx_updated, receiver=self)
        self._transaction.committed.connect(self._tx_committed, receiver=self)
        self._transaction.canceled.connect(self._tx_canceled, receiver=self)
        self._transaction.failed.connect(self.failed.emit, receiver=self)
        self._transaction.activeChanged.connect(self.activeChanged.emit, receiver=self)

    def transaction(self):
        return self._transaction

    def isActive(self):
        return self._transaction.isActive()

    def undoStack(self):
        return self._undo_stack

    def setUndoStack(self, stack):
        self._undo_stack = stack
        return True

    def label(self):
        return self._label

    def setLabel(self, label):
        self._label = str(label or "Edit")

    def setMergeKey(self, key):
        self._merge_key = key

    def mergeKey(self):
        return _clone(self._merge_key)

    def _read(self):
        if self._getter is None:
            return _clone(self._value)
        return _clone(self._getter())

    def _write(self, value):
        if self._setter is None:
            self._value = _clone(value)
            return value
        return self._setter(_clone(value))

    def begin(self, *, value=None, context=None, label=None):
        before = self._read() if value is None else _clone(value)
        self._before = _clone(before)
        self._value = _clone(before)
        return self._transaction.begin(
            label or self._label, context=context, value=before,
            snapshot=before, restore=self._write)

    def update(self, value, *, live=True):
        if not self.isActive():
            self.begin()
        self._value = _clone(value)
        return self._transaction.update(value, apply=self._write if live else None)

    def commit(self, value=None, *, apply=False, record=True):
        if not self.isActive():
            return False
        if value is not None:
            self._value = _clone(value)
            if apply:
                self._write(value)
        before = _clone(self._before)
        after = self._read() if value is None or apply else _clone(value)
        if value is None and self._setter is None:
            after = _clone(self._value)
        changed = before != after
        self._value = _clone(after)
        result = self._transaction.commit(value=after)
        if result and changed and record:
            stack = self._undo_stack
            push = getattr(stack, "push", None)
            if callable(push):
                command = QPropertyEditCommand(
                    self._write, before, after, self._label,
                    merge_key=self._merge_key, merge_window=self._merge_window)
                push(command)
        self._before = None
        return bool(result)

    def cancel(self):
        result = self._transaction.cancel()
        if result:
            self._before = None
            self._value = self._read()
        return bool(result)

    def edit(self, value, *, label=None, context=None, merge_key=None):
        """Perform one immediate property edit and optionally record it."""
        old_key = self._merge_key
        if merge_key is not None:
            self._merge_key = merge_key
        try:
            self.begin(context=context, label=label)
            self.update(value, live=True)
            return self.commit()
        finally:
            self._merge_key = old_key

    def _tx_started(self, _label, context):
        self.started.emit(self._label, context)

    def _tx_updated(self, value, context):
        self.updated.emit(value, context)

    def _tx_committed(self, value, context, result):
        self.committed.emit(value, context, result)

    def _tx_canceled(self, context):
        self.canceled.emit(context)


__all__ = ["QPropertyEditCommand", "QPropertyEditController"]
