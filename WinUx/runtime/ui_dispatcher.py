"""Compatibility facade over DearUIQt's canonical GUI event dispatcher."""
from __future__ import annotations

import time

from DearUIQt.core.dispatcher_protocol import QAbstractEventDispatcher
from DearUIQt.core.dispatcher import QEventDispatcher
from .ui_dispatcher_legacy import UiDispatcherLegacyMixin


class UiDispatcher(UiDispatcherLegacyMixin, QAbstractEventDispatcher):
    """WinUx compatibility facade over :class:`QEventDispatcher`.

    M20 keeps only WinUx return-value/error-shape compatibility; the final legacy queue and snake-case scheduler aliases are removed. Delayed, immediate,
    priority and keyed-coalesced work all live in one canonical DearUIQt
    dispatcher.  This class retains historical method spellings/return values
    for application code while owning no scheduler, timer heap or callback
    queue of its own.
    """

    def __init__(self):
        # Keep the clock indirection for deterministic legacy tests while all
        # scheduling ownership remains in QEventDispatcher.
        self._scheduler = QEventDispatcher(clock=lambda: time.monotonic())

    def setWakeCallback(self, callback):
        return self._scheduler.setWakeCallback(callback)

    def post(self, callback, *args, key=None, priority=0):
        """Post immediate work; duplicate keyed work is rejected.

        Historical WinUx callers expect a boolean rather than a dispatcher
        token, so the facade maps the canonical token to ``True``/``False``.
        """
        if not callable(callback) or self.closed:
            return False
        token = self._scheduler.post(
            callback, *args, priority=int(priority or 0), key=key)
        return token is not None

    def postCoalesced(self, key, callback, *args, priority=0):
        return self.post(callback, *args, key=key, priority=priority)

    def postLatest(self, key, callback, *args, priority=0):
        if not callable(callback) or self.closed:
            return None
        return self._scheduler.postLatest(
            key, callback, *args, priority=int(priority or 0))

    def after(self, delay_ms, callback, *args, priority=0):
        """Schedule UI work through the canonical dispatcher.

        ``after(0)`` historically returned ``None`` in WinUx, so that return
        convention is preserved while the callback itself is still queued for
        the next dispatcher turn. Positive delays return a cancellable token.
        """
        if not callable(callback) or self.closed:
            return None
        delay_ms = max(0.0, float(delay_ms or 0))
        if delay_ms <= 0:
            self._scheduler.post(callback, *args, priority=int(priority or 0))
            return None
        return self._scheduler.after(
            delay_ms, callback, *args, priority=int(priority or 0))

    def after_cancel(self, token):
        return self._scheduler.after_cancel(token)


    def ownerThreadId(self):
        return self._scheduler.ownerThreadId()

    def isOwnerThread(self):
        return self._scheduler.isOwnerThread()

    def nextDeadlineMs(self):
        return self._scheduler.nextDeadlineMs()

    def hasPendingEvents(self):
        return self._scheduler.hasPendingEvents()

    def pendingCount(self):
        return self._scheduler.pendingCount()

    def hasCoalescedKey(self, key):
        return self._scheduler.hasCoalescedKey(key)

    def processEvents(self, max_callbacks=256, time_budget_ms=8.0, *, on_error=None):
        return self._scheduler.processEvents(
            max_callbacks=max_callbacks, time_budget_ms=time_budget_ms,
            on_error=on_error)

    def diagnosticsSnapshot(self):
        core = self._scheduler.diagnosticsSnapshot()
        pending = max(0, int(core.get("pending_count", 0) or 0))
        due = max(0, int(core.get("due_count", 0) or 0))
        return {
            "closed": bool(core.get("closed")),
            "queued_callbacks": due,
            "scheduled_callbacks": max(0, pending - due),
            "owner_thread": self._scheduler.ownerThreadId(),
            "owner_thread_id": core.get("owner_thread_id"),
            "is_owner_thread": core.get("is_owner_thread"),
            "scheduler_alive": False,
            "scheduler_fallback": False,
            "scheduler_start_error": None,
            "single_event_loop": True,
            "coalesced_posts": max(0, int(core.get("coalesced_count", 0) or 0)),
            "canonical_dispatcher": True,
            "pending_count": pending,
            "next_deadline_ms": core.get("next_deadline_ms"),
            "immediate_pending": bool(due),
            "highest_priority": core.get("highest_priority"),
            "lowest_priority": core.get("lowest_priority"),
            "turns": core.get("turns", {}),
        }

    def turnDiagnosticsSnapshot(self):
        return self._scheduler.turnDiagnosticsSnapshot()

    def callbackDiagnosticsSnapshot(self):
        return self._scheduler.callbackDiagnosticsSnapshot()

    def priorityDiagnosticsSnapshot(self, **kwargs):
        return self._scheduler.priorityDiagnosticsSnapshot(**kwargs)

    def priorityComparisonSnapshot(self, **kwargs):
        return self._scheduler.priorityComparisonSnapshot(**kwargs)

    def priorityRegressionSnapshot(self, **kwargs):
        return self._scheduler.priorityRegressionSnapshot(**kwargs)

    def longQueueWaitCallbacksSnapshot(self, **kwargs):
        return self._scheduler.longQueueWaitCallbacksSnapshot(**kwargs)

    def callbackCategoryDiagnosticsSnapshot(self, **kwargs):
        return self._scheduler.callbackCategoryDiagnosticsSnapshot(**kwargs)

    def callbackCategoryComparisonSnapshot(self, **kwargs):
        return self._scheduler.callbackCategoryComparisonSnapshot(**kwargs)

    def callbackCategoryRegressionSnapshot(self, **kwargs):
        return self._scheduler.callbackCategoryRegressionSnapshot(**kwargs)

    def callbackCategorySustainedRegressionSnapshot(self, **kwargs):
        return self._scheduler.callbackCategorySustainedRegressionSnapshot(**kwargs)

    def sustainedStarvationSnapshot(self, **kwargs):
        return self._scheduler.sustainedStarvationSnapshot(**kwargs)

    def queueWaitComparisonSnapshot(self, **kwargs):
        return self._scheduler.queueWaitComparisonSnapshot(**kwargs)

    def queueWaitRegressionSnapshot(self, **kwargs):
        return self._scheduler.queueWaitRegressionSnapshot(**kwargs)

    def compactDiagnosticsSnapshot(self):
        return self._scheduler.compactDiagnosticsSnapshot()

    def recentDiagnosticsSnapshot(self, window_seconds=5.0, *, exclude_recent_seconds=0.0):
        return self._scheduler.recentDiagnosticsSnapshot(
            window_seconds, exclude_recent_seconds=exclude_recent_seconds)

    def close(self):
        self._scheduler.close()

    @property
    def closed(self):
        return self._scheduler.isClosed()
