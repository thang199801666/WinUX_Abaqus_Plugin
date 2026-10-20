"""Qt-style scroll-area container over one backend-owned viewport."""
from __future__ import annotations

from ..core.object import Qt
from .widget import QWidget
from .abstract_scroll_area import QAbstractScrollArea


class QScrollArea(QAbstractScrollArea):
    """Scrollable viewport that owns at most one content widget."""

    def __init__(self, *, parent=None, after=None, backend=None,
                 widget_resizable=True, horizontal_scrollbar=True,
                 vertical_scrollbar=True,
                 horizontal_scrollbar_policy=None,
                 vertical_scrollbar_policy=None):
        if horizontal_scrollbar_policy is None:
            horizontal_scrollbar_policy = (
                Qt.ScrollBarAsNeeded if horizontal_scrollbar else Qt.ScrollBarAlwaysOff)
        if vertical_scrollbar_policy is None:
            vertical_scrollbar_policy = (
                Qt.ScrollBarAsNeeded if vertical_scrollbar else Qt.ScrollBarAlwaysOff)
        super().__init__(
            parent=parent, after=after, backend=backend,
            horizontal_scrollbar_policy=horizontal_scrollbar_policy,
            vertical_scrollbar_policy=vertical_scrollbar_policy,
            border=False,
        )
        self._widget = None
        self._widget_resizable = bool(widget_resizable)
        self._alignment = 0

    def setWidget(self, widget):
        self._require_ui()
        if not isinstance(widget, QWidget):
            raise TypeError("scroll area widget must be QWidget")
        if widget._deleted:
            raise RuntimeError("cannot install a deleted scroll widget")
        if widget.backend is not self.backend:
            raise ValueError("scroll area and content must use the same backend")
        if widget is self:
            raise ValueError("a scroll area cannot contain itself")
        if self._widget is widget:
            self._apply_widget_resizable()
            return widget

        old = self.takeWidget()
        if old is not None:
            old.delete()
        self.backend.move_item(widget._layout_tag(), parent=self.tag)
        widget.setParent(self)
        self._widget = widget
        self._apply_widget_resizable()
        return widget

    def widget(self):
        widget = self._widget
        if widget is not None and widget._deleted:
            self._widget = None
            return None
        return widget

    def takeWidget(self):
        self._require_ui()
        widget = self.widget()
        if widget is None:
            return None
        native_parent = None
        try:
            native_parent = self.backend.get_item_parent(self.tag)
        except Exception:
            pass
        if native_parent:
            self.backend.move_item(widget._layout_tag(), parent=native_parent)
        widget.setParent(self.parent)
        self._widget = None
        return widget

    def setWidgetResizable(self, resizable):
        self._widget_resizable = bool(resizable)
        self._on_ui("scroll-widget-resizable", self._apply_widget_resizable)

    def widgetResizable(self):
        return self._widget_resizable

    def setAlignment(self, alignment):
        self._alignment = int(alignment)

    def alignment(self):
        return self._alignment

    def _apply_widget_resizable(self):
        widget = self.widget()
        if widget is None:
            return
        try:
            if self._widget_resizable:
                self.backend.configure_item(widget._layout_tag(), width=-1)
        except Exception:
            pass

    def ensureVisible(self, x, y, xmargin=50, ymargin=50):
        target_x = max(0, int(float(x) - max(0.0, float(xmargin))))
        target_y = max(0, int(float(y) - max(0.0, float(ymargin))))
        hbar = self.horizontalScrollBar()
        vbar = self.verticalScrollBar()
        if hbar.maximum() > 0:
            hbar.setValue(max(hbar.value(), target_x))
        if vbar.maximum() > 0:
            vbar.setValue(max(vbar.value(), target_y))

    def ensureWidgetVisible(self, child_widget, xmargin=50, ymargin=50):
        if not isinstance(child_widget, QWidget):
            raise TypeError("child_widget must be QWidget")
        position = child_widget.pos()
        self.ensureVisible(position.x(), position.y(), xmargin, ymargin)

    def delete(self):
        super().delete()
        self._widget = None


__all__ = ["QScrollArea"]
