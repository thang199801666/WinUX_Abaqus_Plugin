"""Unified Qt-like dock transition transaction engine.

``QDockTransition`` owns the common state, signal, phase ordering, cancellation
and rollback semantics for both directions of a dock transition.  A transition
may be fully synchronous (floating -> docked) or pause at one explicit
continuation boundary (docked -> floating while a native host reaches its
first-present callback).

Renderer/native code is supplied only as phase callbacks; it must not create a
parallel logical transition state machine.
"""
from __future__ import annotations

from ..core.object import Signal
from .command import QDockCommand


class QDockTransition:
    """Execute one dock-state transition through an ordered phase pipeline."""

    Dock = "dock"
    Float = "float"

    Idle = "idle"
    Running = "running"
    AwaitingContinuation = "awaiting_continuation"
    Completing = "completing"
    Committed = "committed"
    RolledBack = "rolled_back"
    Failed = "failed"

    def __init__(self, direction, phases, *, continuation_after=None,
                 rollback=None, label=None, command=None):
        direction = str(direction or "").strip().lower()
        if direction not in (self.Dock, self.Float):
            raise ValueError("unsupported dock transition direction: %r" % direction)
        self.started = Signal()
        self.transitionStarted = Signal()
        self.phaseChanged = Signal()
        self.awaitingContinuation = Signal()
        self.committed = Signal()
        self.transitionCommitted = Signal()
        self.rolledBack = Signal()
        self.transitionRolledBack = Signal()
        self.failed = Signal()
        self.transitionFailed = Signal()
        self.canceled = Signal()
        self._direction = direction
        self._label = str(label or direction)
        self._command = (QDockCommand(direction, {"label": self._label}, source="transition")
                         if command is None else QDockCommand.coerce(command))
        self._phases = tuple((str(name), callback) for name, callback in phases)
        self._continuation_after = (
            None if continuation_after is None else str(continuation_after))
        if self._continuation_after is not None:
            names = [name for name, _ in self._phases]
            if self._continuation_after not in names:
                raise ValueError("continuation phase is not in the phase pipeline")
        self._rollback = rollback
        self._state = self.Idle
        self._phase = None
        self._context = None
        self._completed = []
        self._last_error = None
        self._continuation_index = None

    @classmethod
    def dock(cls, *, prepare=None, reparent=None, finalize=None,
             persist=None, activate=None, rollback=None, label="dock", command=None):
        return cls(cls.Dock, (
            ("prepare", prepare),
            ("reparent", reparent),
            ("finalize", finalize),
            ("persist", persist),
            ("activate", activate),
        ), rollback=rollback, label=label, command=command)

    @classmethod
    def float(cls, *, prepare=None, create=None, present=None, transfer=None,
              finalize=None, persist=None, activate=None, rollback=None,
              label="float", command=None):
        return cls(cls.Float, (
            ("prepare", prepare),
            ("create", create),
            ("present", present),
            ("transfer", transfer),
            ("finalize", finalize),
            ("persist", persist),
            ("activate", activate),
        ), continuation_after="present", rollback=rollback, label=label, command=command)

    def commandObject(self):
        return self._command

    def direction(self):
        return self._direction

    def label(self):
        return self._label

    def state(self):
        return self._state

    def phase(self):
        return self._phase

    def context(self):
        return self._context

    def lastContext(self):
        return self._context

    def completedPhases(self):
        return tuple(self._completed)

    def lastError(self):
        return self._last_error

    def isRunning(self):
        return self._state in (
            self.Running, self.AwaitingContinuation, self.Completing)

    def isAwaitingContinuation(self):
        return self._state == self.AwaitingContinuation

    def diagnostics(self):
        """Return a read-only snapshot suitable for lifecycle diagnostics."""
        return {
            "direction": self._direction,
            "label": self._label,
            "state": self._state,
            "phase": self._phase,
            "completed_phases": tuple(self._completed),
            "awaiting_continuation": self.isAwaitingContinuation(),
            "has_error": self._last_error is not None,
            "command": self._command.snapshot(),
        }

    @staticmethod
    def _invoke(callback, context):
        if not callable(callback):
            return True
        return callback(context) is not False

    def _set_phase(self, phase):
        self._phase = phase
        self.phaseChanged.emit(phase, self._context)

    def _rollback_failure(self, exc, *, canceled=False):
        self._last_error = exc
        if canceled:
            self._command._canceled(exc)
        else:
            self._command._failed(exc)
        rollback_error = None
        try:
            self._set_phase("rollback")
            if callable(self._rollback):
                self._rollback(self._context, tuple(self._completed), exc)
        except Exception as rb_exc:
            rollback_error = rb_exc
        self._state = self.RolledBack if rollback_error is None else self.Failed
        completed = tuple(self._completed)
        self.rolledBack.emit(self._context, completed, exc)
        self.transitionRolledBack.emit(self._direction, self._context, completed, exc)
        if canceled:
            self.canceled.emit(self._context, completed, exc)
        self.failed.emit(self._context, exc, rollback_error)
        self.transitionFailed.emit(self._direction, self._context, exc, rollback_error)
        self._phase = None
        return False

    def _run_range(self, start, stop):
        try:
            for index in range(start, stop):
                name, callback = self._phases[index]
                self._set_phase(name)
                if not self._invoke(callback, self._context):
                    raise RuntimeError(
                        "dock %s transition phase returned False: %s" %
                        (self._direction, name))
                self._completed.append(name)
        except Exception as exc:
            return self._rollback_failure(exc)
        return True

    def begin(self, context=None):
        """Start the transition and pause if it has a continuation boundary."""
        if self.isRunning():
            return False
        self._context = {} if context is None else context
        self._completed = []
        self._last_error = None
        self._phase = None
        self._continuation_index = None
        self._state = self.Running
        self._command._requested()._running()
        self.started.emit(self._context)
        self.transitionStarted.emit(self._direction, self._context)

        stop = len(self._phases)
        if self._continuation_after is not None:
            for index, (name, _) in enumerate(self._phases):
                if name == self._continuation_after:
                    stop = index + 1
                    self._continuation_index = stop
                    break
        if not self._run_range(0, stop):
            return False

        if self._continuation_index is not None:
            self._state = self.AwaitingContinuation
            self._phase = None
            self.awaitingContinuation.emit(self._context)
            return True

        self._state = self.Committed
        self._phase = None
        self._command._finished(True)
        self.committed.emit(self._context)
        self.transitionCommitted.emit(self._direction, self._context)
        return True

    def continueTransition(self):
        """Resume a transition paused at its async continuation boundary."""
        if self._state != self.AwaitingContinuation:
            return False
        self._state = self.Completing
        start = self._continuation_index or 0
        if not self._run_range(start, len(self._phases)):
            return False
        self._state = self.Committed
        self._phase = None
        self._command._finished(True)
        self.committed.emit(self._context)
        self.transitionCommitted.emit(self._direction, self._context)
        return True

    def commit(self, context=None):
        """Run a synchronous transition to completion.

        Intended for the floating->docked direction.  For an asynchronous
        transition this starts the transaction and returns while it awaits its
        continuation boundary, matching ``begin()`` semantics.
        """
        return self.begin(context)

    def complete(self):
        """Compatibility spelling for ``continueTransition()``."""
        return self.continueTransition()

    def cancel(self, reason=None):
        if not self.isRunning():
            return False
        self._rollback_failure(
            RuntimeError(reason or "dock transition canceled"), canceled=True)
        return True
