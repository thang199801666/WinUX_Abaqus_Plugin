"""Retained Qt-style painting surface."""
from __future__ import annotations

from .widget import QWidget


class QCanvas(QWidget):
    """QWidget-like owner for one renderer draw list.

    The wrapper owns native lifetime/geometry while :class:`QPainter` owns draw
    primitives.  Existing code may continue to use ``canvas.tag`` where a raw
    retained id is required by a renderer callback or item registry.
    """

    def __init__(self, width=-1, height=-1, *, parent=None, after=None, backend=None,
                 tag=None, show=True, pos=None):
        backend, options = self._construction(parent, backend)
        if after is not None:
            options["after"] = getattr(after, "tag", after)
        if tag is not None:
            options["tag"] = tag
        if pos is not None:
            options["pos"] = pos
        if show is not True:
            options["show"] = bool(show)
        native = backend.add_drawlist(width=width, height=height, **options)
        super().__init__(native, parent=parent, after=after, backend=backend)
        if show is not True:
            self._prime_visibility_state(show)

    def clear(self):
        self._require_ui()
        if self._deleted:
            return False
        self.backend.delete_item(self.tag, children_only=True)
        return True

    def painter(self):
        from ..gui.painting import QPainter
        return QPainter(self)


class QViewportCanvas(QWidget):
    """Top-level retained paint surface attached to the native viewport.

    This is the Qt-style boundary for overlays such as drag previews, dock
    indicators and transient selection chrome that must render above ordinary
    widgets.  Applications paint through :class:`QPainter` and never need the
    renderer ``add_viewport_drawlist`` primitive.
    """

    def __init__(self, *, front=True, backend=None, tag=None):
        backend, _options = self._construction(None, backend)
        kwargs = {"front": bool(front)}
        if tag is not None:
            kwargs["tag"] = tag
        try:
            native = backend.add_viewport_drawlist(**kwargs)
        except TypeError:
            kwargs.pop("front", None)
            native = backend.add_viewport_drawlist(**kwargs)
        super().__init__(native, parent=None, backend=backend)

    def clear(self):
        self._require_ui()
        if self._deleted or not self.exists():
            return False
        self.backend.delete_item(self.tag, children_only=True)
        return True

    def painter(self):
        from ..gui.painting import QPainter
        return QPainter(self)


__all__ = ["QCanvas", "QViewportCanvas"]
