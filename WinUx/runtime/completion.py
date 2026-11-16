"""Completion-aware task submission with a legacy integration fallback.

Production WinUx task lanes own a ``BackgroundTaskManager`` and therefore
marshal ``on_done`` callbacks through the shared ``UiDispatcher``.  A few test
and third-party controller proxies still provide only the historical
``submit(name, worker, ...)`` shape.  This adapter preserves those integrations
without weakening the production event-posted path.
"""
from __future__ import annotations

from types import SimpleNamespace


def submit_with_completion(submitter, manager, name, worker, on_done, *, scheduler=None, **kwargs):
    """Submit *worker* and deliver one completion callback.

    When *manager* is present the real task lane owns completion delivery.  If
    no manager is available, wrap the worker and synthesize the small subset of
    ``BackgroundTaskHandle`` used by controller completion callbacks.
    """
    if manager is not None:
        return submitter(name, worker, on_done=on_done, **kwargs)

    delivered = [False]

    def deliver(handle):
        if delivered[0]:
            return
        delivered[0] = True
        after = getattr(scheduler, "after", None) if scheduler is not None else None
        if callable(after):
            after(0, on_done, handle)
        else:
            on_done(handle)

    def legacy_worker():
        try:
            result = worker()
        except Exception as exc:
            handle = SimpleNamespace(state="failed", result=None, exception=exc)
        else:
            handle = SimpleNamespace(state="completed", result=result, exception=None)
        deliver(handle)
        return handle.result

    handle = submitter(name, legacy_worker, **kwargs)
    if getattr(handle, "state", None) == "rejected" and not delivered[0]:
        deliver(SimpleNamespace(
            state="rejected", result=None,
            exception=getattr(handle, "exception", RuntimeError("background queue is busy")),
        ))
    return handle
