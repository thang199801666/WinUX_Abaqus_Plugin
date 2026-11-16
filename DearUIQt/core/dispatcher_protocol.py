"""Canonical dispatcher contract shared by GUI and worker event loops.

This interface is intentionally backend-neutral and threadless.  Hosts may use
specialized queue implementations, but DearUIQt/WinUx scheduling code should
consume these public methods instead of probing private heaps/queues.
"""
from __future__ import annotations


class QAbstractEventDispatcher:
    """Small structural contract for Qt-style event dispatchers.

    Subclasses own callback delivery on exactly one thread.  Larger priority
    values run first only after deadline readiness; deadlines always dominate
    priority.  Implementations must not create a scheduler/render thread merely
    to satisfy this interface.
    """

    def ownerThreadId(self):
        raise NotImplementedError

    def isOwnerThread(self):
        raise NotImplementedError

    def setWakeCallback(self, callback):
        raise NotImplementedError

    def after(self, delay_ms, callback, *args, priority=0):
        raise NotImplementedError

    def post(self, callback, *args, priority=0, key=None, **kwargs):
        raise NotImplementedError

    def postCoalesced(self, key, callback, *args, priority=0):
        raise NotImplementedError

    def postLatest(self, key, callback, *args, priority=0):
        """Keep one pending keyed callback while replacing its payload."""
        raise NotImplementedError

    def after_cancel(self, token):
        raise NotImplementedError

    def nextDeadlineMs(self):
        raise NotImplementedError

    def hasPendingEvents(self):
        raise NotImplementedError

    def processEvents(self, max_callbacks=256, time_budget_ms=8.0, *, on_error=None):
        raise NotImplementedError

    def diagnosticsSnapshot(self):
        raise NotImplementedError

    def turnDiagnosticsSnapshot(self):
        raise NotImplementedError

    def callbackDiagnosticsSnapshot(self):
        raise NotImplementedError

    def priorityDiagnosticsSnapshot(self, *, window_seconds=30.0, starvation_threshold_ms=50.0, min_samples=1):
        raise NotImplementedError

    def priorityComparisonSnapshot(self, *, current_window_seconds=5.0, baseline_window_seconds=30.0, min_current_samples=3, min_baseline_samples=8):
        raise NotImplementedError

    def priorityRegressionSnapshot(self, *, current_window_seconds=5.0, baseline_window_seconds=30.0, min_current_samples=3, min_baseline_samples=8, max_p95_ratio=2.5, max_p95_delta_ms=25.0):
        raise NotImplementedError

    def longQueueWaitCallbacksSnapshot(self, *, window_seconds=30.0, threshold_ms=50.0, limit=8):
        raise NotImplementedError

    def callbackCategoryDiagnosticsSnapshot(self, *, window_seconds=30.0, category_depth=2):
        raise NotImplementedError

    def callbackCategoryComparisonSnapshot(self, *, current_window_seconds=5.0, baseline_window_seconds=30.0, min_current_samples=3, min_baseline_samples=8, category_depth=2):
        raise NotImplementedError

    def callbackCategoryRegressionSnapshot(self, *, current_window_seconds=5.0, baseline_window_seconds=30.0, min_current_samples=3, min_baseline_samples=8, category_depth=2, max_p95_ratio=2.5, max_p95_delta_ms=25.0, max_callback_p95_delta_ms=8.0):
        raise NotImplementedError

    def callbackCategorySustainedRegressionSnapshot(self, *, current_window_seconds=15.0, baseline_window_seconds=60.0, min_current_samples=8, min_baseline_samples=24, category_depth=2, max_p95_ratio=2.5, max_p95_delta_ms=25.0, max_callback_p95_delta_ms=8.0, top_limit=5):
        raise NotImplementedError

    def sustainedStarvationSnapshot(self, *, window_seconds=30.0, starvation_threshold_ms=50.0, min_samples=5, min_starvation_fraction=0.5):
        raise NotImplementedError

    def queueWaitComparisonSnapshot(self, *, current_window_seconds=5.0, baseline_window_seconds=30.0, min_current_samples=5, min_baseline_samples=20):
        raise NotImplementedError

    def queueWaitRegressionSnapshot(self, *, current_window_seconds=5.0, baseline_window_seconds=30.0, min_current_samples=5, min_baseline_samples=20, max_p95_ratio=2.0, max_p95_delta_ms=20.0):
        raise NotImplementedError

    def compactDiagnosticsSnapshot(self):
        raise NotImplementedError

    def recentDiagnosticsSnapshot(self, window_seconds=5.0, *, exclude_recent_seconds=0.0):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError


__all__ = ["QAbstractEventDispatcher"]
