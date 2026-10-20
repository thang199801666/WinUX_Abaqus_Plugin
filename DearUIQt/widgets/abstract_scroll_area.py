"""Qt-style abstract scroll area policy over retained backend scroll state."""
from __future__ import annotations

from ..core.object import QObject, Qt, QMargins, QSize, Signal
from .widget import QWidget


class _ScrollBarController(QObject):
    """Logical scrollbar controller for a backend-owned scroll area.

    Dear PyGui renders child-window scrollbars internally rather than as child
    items.  This controller exposes the QScrollBar state contract without
    fabricating a second visual slider on top of the native scrollbar.
    """

    def __init__(self, owner, orientation):
        super().__init__(parent=owner, after=getattr(owner, "_after", None))
        self._owner = owner
        self._orientation = int(orientation)
        self.valueChanged = Signal(self)
        self.rangeChanged = Signal(self)
        self._single_step = 20
        self._page_step = 100

    def orientation(self):
        return self._orientation

    def _getter(self, x_name, y_name, default=0):
        name = x_name if self._orientation == Qt.Horizontal else y_name
        function = getattr(self._owner.backend, name, None)
        if not callable(function):
            return default
        try:
            return int(function(self._owner.tag))
        except Exception:
            return default

    def minimum(self):
        return 0

    def maximum(self):
        return self._getter("get_x_scroll_max", "get_y_scroll_max", 0)

    def value(self):
        return self._getter("get_x_scroll", "get_y_scroll", 0)

    def setValue(self, value):
        value = max(self.minimum(), min(self.maximum(), int(value)))
        previous = self.value()
        function = getattr(
            self._owner.backend,
            "set_x_scroll" if self._orientation == Qt.Horizontal else "set_y_scroll",
            None,
        )
        if callable(function):
            try:
                function(self._owner.tag, value)
            except Exception:
                return False
        if previous != value:
            self.valueChanged.emit(value)
        return True

    def setSingleStep(self, value):
        self._single_step = max(1, int(value))

    def singleStep(self):
        return self._single_step

    def setPageStep(self, value):
        self._page_step = max(1, int(value))

    def pageStep(self):
        return self._page_step


class QAbstractScrollArea(QWidget):
    """Base class for widgets backed by one native scrolling viewport."""

    def __init__(self, *, parent=None, after=None, backend=None,
                 horizontal_scrollbar_policy=Qt.ScrollBarAsNeeded,
                 vertical_scrollbar_policy=Qt.ScrollBarAsNeeded,
                 border=False):
        backend, options = self._construction(parent, backend)
        self._horizontal_policy = self._normalize_policy(horizontal_scrollbar_policy)
        self._vertical_policy = self._normalize_policy(vertical_scrollbar_policy)
        tag = backend.add_child_window(
            width=-1,
            height=-1,
            border=bool(border),
            no_scrollbar=self._vertical_policy == Qt.ScrollBarAlwaysOff,
            no_scroll_with_mouse=False,
            horizontal_scrollbar=self._horizontal_policy != Qt.ScrollBarAlwaysOff,
            **options,
        )
        super().__init__(tag, parent=parent, after=after, backend=backend)
        self._viewport_margins = QMargins()
        self._horizontal_scrollbar = _ScrollBarController(self, Qt.Horizontal)
        self._vertical_scrollbar = _ScrollBarController(self, Qt.Vertical)

    @staticmethod
    def _normalize_policy(policy):
        value = int(policy)
        allowed = (Qt.ScrollBarAsNeeded, Qt.ScrollBarAlwaysOff, Qt.ScrollBarAlwaysOn)
        if value not in allowed:
            raise ValueError("invalid scrollbar policy")
        return value

    def viewport(self):
        # The backend child-window is both viewport and scroll owner. Returning
        # self preserves QWidget semantics without creating a fake native child.
        return self

    def horizontalScrollBar(self):
        return self._horizontal_scrollbar

    def verticalScrollBar(self):
        return self._vertical_scrollbar

    def horizontalScrollBarPolicy(self):
        return self._horizontal_policy

    def verticalScrollBarPolicy(self):
        return self._vertical_policy

    def setHorizontalScrollBarPolicy(self, policy):
        policy = self._normalize_policy(policy)
        if policy == self._horizontal_policy:
            return
        self._horizontal_policy = policy
        self._configure("horizontal_scrollbar", policy != Qt.ScrollBarAlwaysOff)

    def setVerticalScrollBarPolicy(self, policy):
        policy = self._normalize_policy(policy)
        if policy == self._vertical_policy:
            return
        self._vertical_policy = policy
        self._configure("no_scrollbar", policy == Qt.ScrollBarAlwaysOff)

    def setViewportMargins(self, *args):
        if len(args) == 1 and isinstance(args[0], QMargins):
            margins = QMargins(*tuple(args[0]))
        elif len(args) == 4:
            margins = QMargins(*args)
        else:
            raise TypeError("setViewportMargins(QMargins) or setViewportMargins(l,t,r,b)")
        self._viewport_margins = margins
        self.updateGeometry()

    def viewportMargins(self):
        return QMargins(*tuple(self._viewport_margins))

    def maximumViewportSize(self):
        size = self.size()
        margins = self._viewport_margins
        return QSize(
            max(0, size.width() - margins.left() - margins.right()),
            max(0, size.height() - margins.top() - margins.bottom()),
        )

    def scrollContentsBy(self, dx, dy):
        if dx:
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() + int(dx))
        if dy:
            bar = self.verticalScrollBar()
            bar.setValue(bar.value() + int(dy))


__all__ = ["QAbstractScrollArea"]
