"""QToolTip-style retained tooltip container."""
from __future__ import annotations

from .widget import QWidget
from ..tooltip import TOOLTIP_DELAY


class QToolTip(QWidget):
    """Renderer tooltip surface owned as a normal DearUIQt widget."""
    def __init__(self, target, *, parent=None, after=None, backend=None,
                  delay=TOOLTIP_DELAY, hide_on_activity=True, show=True, tag=None):
        # ``show`` enables Dear PyGui's delayed hover tooltip; False disables
        # it entirely. Automatic tooltips must be enabled by default, while
        # manually populated Explorer tooltips still explicitly use show=False.
        if parent is None and isinstance(target, QWidget):
            parent = target
        backend, _ = self._construction(parent, backend)
        native_target = getattr(target, "tag", target)

        # Dear PyGui tooltips are native children of their target. Paint-only
        # items (QCanvas/mvDrawlist and draw primitives) accept draw children
        # only. Entering dearpygui.tooltip() with such a target raises during
        # add_tooltip(), then its generator finally block still pops the
        # container stack, producing the misleading secondary "No container to
        # pop" failure. Reject paint targets before entering that context.
        try:
            info = backend.get_item_info(native_target)
            native_type = str((info or {}).get("type", ""))
        except Exception:
            native_type = ""
        if "mvDraw" in native_type or "Drawlist" in native_type:
            raise TypeError(
                "QToolTip requires a hoverable widget target; paint/draw items "
                "must use a viewport tooltip overlay")

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
