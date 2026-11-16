"""Signal-driven semantic dock-drop execution controller.

The controller listens to :class:`QDockWindowLifecycle.moveFinished` and turns
its retained result into one of three semantic dispositions: ``dock``,
``float`` or ``cancel``.  Application code supplies small adapters for the
actual reparent/native-host handshake; gesture loops do not execute drops.
"""
from __future__ import annotations

from ..core.object import Signal


class QDockDropController:
    """Execute one dock lifecycle's completed move through signal-slot hooks."""

    Dock = "dock"
    Float = "float"
    Cancel = "cancel"

    def __init__(self, on_dock=None, on_float=None, on_cancel=None):
        self.dropResolved = Signal()
        self.dockRequested = Signal()
        self.floatRequested = Signal()
        self.cancelRequested = Signal()
        self._on_dock = on_dock
        self._on_float = on_float
        self._on_cancel = on_cancel
        self._binding = None
        self._last_result = None

    @staticmethod
    def _copy_result(result):
        value = dict(result or {})
        target = value.get("target")
        value["target"] = dict(target) if isinstance(target, dict) else target
        return value

    @classmethod
    def dispositionFor(cls, result):
        result = result or {}
        if bool(result.get("canceled")):
            return cls.Cancel
        if bool(result.get("docked")) or result.get("target") is not None:
            return cls.Dock
        return cls.Float

    def bindLifecycle(self, lifecycle):
        if lifecycle is None:
            raise TypeError("lifecycle is required")
        self.unbindLifecycle()
        connection = lifecycle.moveFinished.connect(self._move_finished)
        self._binding = (lifecycle, connection)
        return lifecycle

    def unbindLifecycle(self):
        binding = self._binding
        self._binding = None
        if binding is None:
            return False
        try:
            binding[1].disconnect()
        except Exception:
            pass
        return True

    def lifecycle(self):
        return None if self._binding is None else self._binding[0]

    def lastResult(self):
        return None if self._last_result is None else self._copy_result(self._last_result)

    def resolve(self, result):
        value = self._copy_result(result)
        disposition = self.dispositionFor(value)
        value["disposition"] = disposition
        self._last_result = value
        self.dropResolved.emit(self._copy_result(value))

        target = value.get("target") or {}
        area = target.get("area") if isinstance(target, dict) else target
        scope = target.get("scope") if isinstance(target, dict) else None
        if disposition == self.Dock:
            self.dockRequested.emit(area, scope, self._copy_result(value))
            callback = self._on_dock
            if callable(callback):
                callback(area, scope, self._copy_result(value))
        elif disposition == self.Cancel:
            self.cancelRequested.emit(self._copy_result(value))
            callback = self._on_cancel
            if callable(callback):
                callback(self._copy_result(value))
        else:
            self.floatRequested.emit(self._copy_result(value))
            callback = self._on_float
            if callable(callback):
                callback(self._copy_result(value))
        return disposition

    def _move_finished(self, result=None):
        self.resolve(result)

    def destroy(self):
        self.unbindLifecycle()
        self._on_dock = None
        self._on_float = None
        self._on_cancel = None
        self._last_result = None
