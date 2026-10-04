"""Ownership and explicit signal connections independent of GUI libraries."""
from __future__ import annotations


class SignalConnection:
    def __init__(self, signal, slot, receiver, queued):
        self.signal, self.slot, self.receiver, self.queued = signal, slot, receiver, queued
        self.active = True

    def disconnect(self):
        if not self.active:
            return
        self.active = False
        self.signal._slots.remove(self)
        if self.receiver is not None:
            self.receiver._connections.discard(self)
        self.slot = self.receiver = None

    def deliver(self, args):
        if self.active and (self.receiver is None or not self.receiver._deleted):
            self.slot(*args)


class Signal:
    def __init__(self, owner=None):
        self._slots = []
        self.owner = owner

    def connect(self, slot, *, receiver=None, queued=False):
        if not callable(slot):
            raise TypeError("signal slot must be callable")
        if receiver is None and isinstance(getattr(slot, "__self__", None), QObject):
            receiver = slot.__self__
        if receiver is not None and receiver._deleted:
            raise RuntimeError("cannot connect a deleted receiver")
        if queued and (receiver is None or getattr(receiver, "_after", None) is None):
            raise ValueError("queued connections require a receiver with a UI scheduler")
        for connection in self._slots:
            if connection.slot == slot and connection.receiver is receiver and connection.queued == queued:
                return connection
        connection = SignalConnection(self, slot, receiver, queued)
        self._slots.append(connection)
        if receiver is not None:
            receiver._connections.add(connection)
        return connection

    def disconnect(self, slot=None):
        if slot is None:
            for connection in tuple(self._slots):
                connection.disconnect()
        else:
            for connection in tuple(self._slots):
                if connection is slot or connection.slot == slot:
                    connection.disconnect()

    def emit(self, *args):
        if self.owner is not None and (self.owner._signals_blocked or self.owner._deleted):
            return
        for connection in tuple(self._slots):
            if not connection.active:
                continue
            if connection.queued:
                connection.receiver._after(0, connection.deliver, args)
            else:
                connection.deliver(args)


class QObject:
    """UI-thread-owned object tree with explicit, idempotent disposal."""

    def __init__(self, parent=None, *, after=None):
        self.parent = None
        self._children = []
        self._deleted = False
        self._connections = set()
        self._signals_blocked = False
        self._after = after if after is not None else getattr(parent, "_after", None)
        self.destroyed = Signal()
        self.setParent(parent)

    def setParent(self, parent):
        if self._deleted:
            raise RuntimeError("cannot reparent a deleted object")
        if parent is not None:
            if parent._deleted:
                raise RuntimeError("cannot attach to a deleted parent")
            ancestor = parent
            while ancestor is not None:
                if ancestor is self:
                    raise ValueError("object ownership cannot contain a cycle")
                ancestor = ancestor.parent
        if self.parent is parent:
            return
        if self.parent is not None:
            self.parent._children.remove(self)
        self.parent = parent
        if parent is not None:
            parent._children.append(self)

    def blockSignals(self, blocked):
        previous = self._signals_blocked
        self._signals_blocked = bool(blocked)
        return previous

    def delete(self):
        if self._deleted:
            return
        self._deleted = True
        for connection in tuple(self._connections):
            connection.disconnect()
        error = None
        for child in tuple(self._children):
            try:
                child.delete()
            except Exception as exc:
                if error is None:
                    error = exc
        self._children.clear()
        if self.parent is not None:
            self.parent._children.remove(self)
            self.parent = None
        try:
            self.destroyed.emit(self)
        except Exception as exc:
            if error is None:
                error = exc
        finally:
            for value in vars(self).values():
                if isinstance(value, Signal):
                    value.disconnect()
        if error is not None:
            raise error


class QSignalBlocker:
    """Temporarily suppress change signals while synchronizing form state."""
    def __init__(self, obj):
        self.obj = obj

    def __enter__(self):
        self.previous = self.obj.blockSignals(True)
        return self

    def __exit__(self, *_args):
        self.obj.blockSignals(self.previous)
