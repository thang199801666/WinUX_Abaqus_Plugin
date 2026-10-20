"""Modeless popup-like surfaces that do not enter the renderer popup stack.

``QPopupPanel`` is intentionally different from :class:`QMenu`: it is an
ordinary top-level retained window with popup *geometry* and lifecycle, but no
native/ImGui popup ownership.  It is useful for autocomplete panels, terminal
context surfaces and other transient tools where an outside click must remain
available to the destination widget.
"""
from __future__ import annotations

from ..core import QPoint, QRect, QSize
from ..gui.system import QCursor, QScreen
from .widget import QWidget


class QPopupPanel(QWidget):
    """Borderless modeless top-level panel with Qt-style geometry helpers."""

    def __init__(self, *, width=180, height=80, min_width=None, max_width=None,
                 min_height=1, max_height=30000, backend=None, after=None,
                 object_name="", tag=None, transparent=False,
                 bring_to_front_on_focus=True, parent=None):
        if backend is None:
            backend = getattr(parent, "backend", None)
        if backend is None:
            from ..backends import get_backend
            backend = get_backend()
        width, height = max(1, int(width)), max(1, int(height))
        min_width = width if min_width is None else max(1, int(min_width))
        max_width = max(width, int(max_width if max_width is not None else width))
        tag = tag or backend.generate_uuid()
        with backend.window(
                tag=tag, show=False, width=width, height=height,
                min_size=(min_width, max(1, int(min_height))),
                max_size=(max_width, max(1, int(max_height))),
                no_title_bar=True, no_resize=True, no_move=True,
                no_saved_settings=True, no_scrollbar=True,
                no_scroll_with_mouse=True, no_background=bool(transparent),
                no_bring_to_front_on_focus=not bool(bring_to_front_on_focus)):
            pass
        super().__init__(tag, parent=parent, after=after, backend=backend)
        self._prime_visibility_state(False)
        self._properties.update({"width": width, "height": height, "pos": (0, 0)})
        self._configured_size = QSize(width, height)
        if object_name:
            self.setObjectName(object_name)

    def resize(self, width, height=None):
        size = width if isinstance(width, QSize) and height is None else QSize(width, height)
        self._configured_size = QSize(max(1, size.width()), max(1, size.height()))
        return super().resize(self._configured_size)

    def configuredSize(self):
        """Return the requested panel size even before its first rendered frame."""
        return QSize(self._configured_size)

    def effectiveSize(self):
        """Return rendered size when available, otherwise configured size."""
        if not self.exists():
            return QSize()
        try:
            width, height = self.backend.get_item_rect_size(self.tag)
            width, height = int(width or 0), int(height or 0)
            if width > 0 and height > 0:
                return QSize(width, height)
        except Exception:
            pass
        return self.configuredSize()

    def clampPosition(self, position, *, margin=4, screen=None):
        point = position if isinstance(position, QPoint) else QPoint(*position)
        geometry = (screen or QScreen(backend=self.backend)).geometry()
        size = self.effectiveSize()
        margin = max(0, int(margin))
        x, y = point.x(), point.y()
        if geometry.width() > size.width() + margin * 2:
            x = max(geometry.left() + margin,
                    min(x, geometry.right() - size.width() - margin + 1))
        if geometry.height() > size.height() + margin * 2:
            y = max(geometry.top() + margin,
                    min(y, geometry.bottom() - size.height() - margin + 1))
        return QPoint(x, y)

    def showAt(self, position=None, *, clamp=True, margin=4, focus=False):
        if position is None:
            position = QCursor.pos(backend=self.backend)
        point = position if isinstance(position, QPoint) else QPoint(*position)
        if clamp:
            point = self.clampPosition(point, margin=margin)
        self.move(point)
        self.show()
        if focus:
            self.setFocus()
        return True

    def containsGlobalPoint(self, point):
        if not self.isVisible() or not self.exists():
            return False
        point = point if isinstance(point, QPoint) else QPoint(*point)
        try:
            if self.underMouse():
                return True
        except Exception:
            pass
        # Hidden/fresh windows can report a zero renderer rect for one frame;
        # use the retained top-level position plus configured size in that case.
        pos = self.pos()
        size = self.effectiveSize()
        rect = QRect(pos, size)
        return rect.contains(point)


__all__ = ["QPopupPanel"]
