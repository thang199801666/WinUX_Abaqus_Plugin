"""Compatibility wrapper for the unified Qt-like dock transition engine."""
from __future__ import annotations

from .transition import QDockTransition


class QDockCommitTransaction(QDockTransition):
    """Backward-compatible synchronous floating->docked transaction."""

    def __init__(self, prepare=None, reparent=None, finalize=None,
                 persist=None, activate=None, rollback=None):
        super().__init__(self.Dock, (
            ("prepare", prepare),
            ("reparent", reparent),
            ("finalize", finalize),
            ("persist", persist),
            ("activate", activate),
        ), rollback=rollback, label="dock")
