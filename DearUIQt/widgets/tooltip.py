"""QToolTip-style retained tooltip container."""
from __future__ import annotations

from .widget import QWidget


class QToolTip(QWidget):
    """Renderer tooltip surface owned as a normal DearUIQt widget."""
    def __init__(self, target, *, parent=None, after=None, backend=None,
                 delay=0.45, hide_on_activity=True, show=False, tag=None):
        backend, _ = self._construction(parent, backend)
        native_target = getattr(target, "tag", target)
        kwargs = {
            "delay": float(delay),
            "hide_on_activity": bool(hide_on_activity),
            "show": bool(show),
        }
        if tag is not None:
            kwargs["tag"] = tag
        cm = backend.tooltip(native_target, **kwargs)
        native = cm.__enter__()
        cm.__exit__(None, None, None)
        super().__init__(native, parent=parent, after=after, backend=backend)
        self._prime_visibility_state(show)
        self._target = target

    def target(self):
        return self._target


__all__ = ["QToolTip"]
