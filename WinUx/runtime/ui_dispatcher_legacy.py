"""External-only compatibility shims for the historical WinUx dispatcher API.

Production WinUx code uses the canonical QAbstractEventDispatcher surface.
These wrappers remain inherited by UiDispatcher so third-party/older code can
migrate without reintroducing a second scheduler or queue.
"""


class UiDispatcherLegacyMixin:
    def drain(self, on_error=None, max_callbacks=None, time_budget_ms=None):
        """Deprecated compatibility wrapper; use processEvents()."""
        limit = None if max_callbacks is None else max(0, int(max_callbacks))
        budget = None if time_budget_ms is None else max(0.0, float(time_budget_ms))
        if on_error is None:
            handler = None
        else:
            def handler(callback, exc):
                on_error(callback, (type(exc), exc, exc.__traceback__))
        return self.processEvents(
            max_callbacks=limit, time_budget_ms=budget, on_error=handler)

    def snapshot(self):
        """Deprecated compatibility wrapper; use diagnosticsSnapshot()."""
        return self.diagnosticsSnapshot()


__all__ = ["UiDispatcherLegacyMixin"]
