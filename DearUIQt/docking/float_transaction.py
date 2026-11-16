"""Compatibility wrapper for the unified Qt-like dock transition engine."""
from __future__ import annotations

from .transition import QDockTransition


class QDockFloatTransaction(QDockTransition):
    """Backward-compatible asynchronous docked->floating transaction."""

    Starting = QDockTransition.Running
    AwaitingPresentation = QDockTransition.AwaitingContinuation

    def __init__(self, prepare=None, create=None, present=None, transfer=None,
                 finalize=None, persist=None, activate=None, rollback=None):
        super().__init__(self.Float, (
            ("prepare", prepare),
            ("create", create),
            ("present", present),
            ("transfer", transfer),
            ("finalize", finalize),
            ("persist", persist),
            ("activate", activate),
        ), continuation_after="present", rollback=rollback, label="float")
        self.awaitingPresentation = self.awaitingContinuation
