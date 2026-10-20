"""Dear ImGui tab containers with QTabWidget-like retained semantics.

The implementation is entirely Dear PyGui.  Qt terminology describes only the
visual/behavioral contract so dialog code can use one consistent API without
introducing another UI toolkit.
"""
from __future__ import annotations

from .widget import QWidget
from ..core.object import Signal, QSignalBlocker
from ..gui.style import bind_theme, tab_widget_theme


class ImGuiTabPage(QWidget):
    """One page owned by :class:`ImGuiTabWidget`."""

    def __init__(self, tag, label, *, parent, after=None, backend=None):
        super().__init__(tag, parent=parent, after=after, backend=backend)
        self._label = str(label)
        self._tab_visible = True

    def text(self):
        return self._label

    def setText(self, text):
        self._label = str(text)
        self._on_ui("label", self._configure, "label", self._label)

    def delete(self):
        self._require_ui()
        if self._deleted:
            return
        owner = self.parent
        try:
            if isinstance(owner, ImGuiTabWidget):
                owner._forget_page(self)
        finally:
            super().delete()


class ImGuiTabWidget(QWidget):
    """Compact QTabWidget-style wrapper over Dear ImGui ``mvTabBar``.

    Pages remain real Dear ImGui tabs, so mouse/keyboard navigation and native
    Dear ImGui clipping/layout are preserved.  The wrapper only adds retained
    page ownership, a stable current-index API and Qt/Fusion styling.
    """

    def __init__(self, *, parent=None, after=None, backend=None, reorderable=False):
        backend, options = self._construction(parent, backend)
        self.currentChanged = Signal()
        tag = backend.add_tab_bar(
            callback=self._changed,
            reorderable=bool(reorderable),
            **options,
        )
        super().__init__(tag, parent=parent, after=after, backend=backend)
        self.currentChanged.owner = self
        self._pages = []
        self._current = -1
        bind_theme(self.backend, self.tag, tab_widget_theme)

    def addTab(self, label):
        return self.insertTab(len(self._pages), label)

    def insertTab(self, index, label):
        self._require_ui()
        if self._deleted:
            raise RuntimeError("cannot add a tab to a deleted tab widget")
        index = int(index)
        index = len(self._pages) if index < 0 else min(index, len(self._pages))
        options = {"label": str(label), "parent": self.tag}
        if index < len(self._pages):
            options["before"] = self._pages[index].tag
        page_tag = self.backend.add_tab(**options)
        page = ImGuiTabPage(
            page_tag, label, parent=self, after=self._after, backend=self.backend)
        self._pages.insert(index, page)
        if self._current < 0:
            self.setCurrentIndex(index)
        elif index <= self._current:
            self._current += 1
            self.currentChanged.emit(self._current)
        return page

    add_tab = addTab

    def count(self):
        return len(self._pages)

    def widget(self, index):
        index = int(index)
        return self._pages[index] if 0 <= index < len(self._pages) else None

    def indexOf(self, page):
        try:
            return self._pages.index(page)
        except ValueError:
            return -1

    def tabText(self, index):
        page = self.widget(index)
        return "" if page is None else page.text()

    def setTabText(self, index, text):
        page = self.widget(index)
        if page is None:
            return False
        page.setText(text)
        return True

    def currentIndex(self):
        return self._current

    def currentWidget(self):
        return self.widget(self._current)

    def setCurrentIndex(self, index):
        self._require_ui()
        index = int(index)
        if not 0 <= index < len(self._pages) or not self._pages[index]._tab_visible:
            return False
        page = self._pages[index]
        try:
            self.backend.set_value(self.tag, page.tag)
        except Exception:
            try:
                self.backend.configure_item(page.tag, show=True)
            except Exception:
                return False
        if self._current != index:
            self._current = index
            self.currentChanged.emit(index)
        return True

    def setCurrentWidget(self, page):
        index = self.indexOf(page)
        return False if index < 0 else self.setCurrentIndex(index)

    def removeTab(self, index):
        self._require_ui()
        index = int(index)
        page = self.widget(index)
        if page is None:
            return False
        page.delete()
        return True

    def _visible_index(self, preferred=0):
        indices = list(range(preferred, len(self._pages))) + list(range(preferred - 1, -1, -1))
        return next((index for index in indices if self._pages[index]._tab_visible), -1)

    def _forget_page(self, page):
        index = self.indexOf(page)
        if index < 0:
            return
        was_current = index == self._current
        self._pages.pop(index)
        if self._current > index:
            next_index = self._current - 1
        elif was_current:
            next_index = self._visible_index(min(index, len(self._pages)))
        else:
            next_index = self._current
        changed = next_index != self._current
        self._current = next_index
        if self._current >= 0 and not self._deleted:
            try:
                self.backend.set_value(self.tag, self._pages[self._current].tag)
            except Exception:
                pass
        if changed or was_current:
            self.currentChanged.emit(self._current)

    def setTabVisible(self, index, visible):
        self._require_ui()
        index = int(index)
        page = self.widget(index)
        if page is None:
            return False
        page._tab_visible = bool(visible)
        page.setVisible(visible)
        if not visible and index == self._current:
            next_index = self._visible_index(index)
            if next_index < 0:
                self._current = -1
                self.currentChanged.emit(-1)
            else:
                self.setCurrentIndex(next_index)
        elif visible and self._current < 0:
            self.setCurrentIndex(index)
        return True

    def isTabVisible(self, index):
        self._require_ui()
        page = self.widget(index)
        return bool(page is not None and page._tab_visible)

    def clear(self):
        self._require_ui()
        was_current = self._current
        with QSignalBlocker(self):
            while self._pages:
                self.removeTab(len(self._pages) - 1)
        if was_current >= 0:
            self.currentChanged.emit(-1)

    def _changed(self, sender=None, app_data=None, user_data=None):
        if self._deleted:
            return
        native = app_data
        index = next(
            (i for i, page in enumerate(self._pages) if page.tag == native and page._tab_visible),
            self._current,
        )
        if index != self._current:
            self._current = index
            self.currentChanged.emit(index)


class ImGuiStackedWidget(QWidget):
    """QStackedWidget-style retained page container.

    Only the old and new page cross the Python/native boundary when the current
    index changes.  That is materially cheaper than reconfiguring every page on
    each navigation click and matches Qt's stacked-layout semantics.
    """

    def __init__(self, *, parent=None, after=None, backend=None):
        backend, options = self._construction(parent, backend)
        self.currentChanged = Signal()
        tag = backend.add_group(**options)
        super().__init__(tag, parent=parent, after=after, backend=backend)
        self.currentChanged.owner = self
        self._pages = []
        self._current = -1

    def addPage(self):
        """Create and append one empty QWidget page for incremental population."""
        self._require_ui()
        initially_visible = not self._pages
        page_tag = self.backend.add_group(parent=self.tag, show=initially_visible)
        page = QWidget(page_tag, parent=self, after=self._after, backend=self.backend)
        page._prime_visibility_state(initially_visible)
        self.addWidget(page)
        return page

    def addWidget(self, widget):
        return self.insertWidget(len(self._pages), widget)

    def insertWidget(self, index, widget):
        self._require_ui()
        if not isinstance(widget, QWidget) or widget._deleted:
            raise TypeError("QStackedWidget requires a live QWidget")
        if widget.backend is not self.backend:
            raise ValueError("stack and page must use the same backend")
        if widget in self._pages:
            return self._pages.index(widget)
        index = max(0, min(int(index), len(self._pages)))
        options = {"parent": self.tag}
        if index < len(self._pages):
            options["before"] = self._pages[index]._layout_tag()
        self.backend.move_item(widget._layout_tag(), **options)
        widget.setParent(self)
        self._pages.insert(index, widget)
        if self._current < 0:
            self._current = index
            widget.setVisible(True)
            self.currentChanged.emit(index)
        else:
            widget.setVisible(False)
            if index <= self._current:
                self._current += 1
        self.updateGeometry()
        return index

    def count(self):
        return len(self._pages)

    def widget(self, index):
        index = int(index)
        return self._pages[index] if 0 <= index < len(self._pages) else None

    def indexOf(self, widget):
        try:
            return self._pages.index(widget)
        except ValueError:
            return -1

    def currentIndex(self):
        return self._current

    def currentWidget(self):
        return self.widget(self._current)

    def setCurrentIndex(self, index):
        self._require_ui()
        index = int(index)
        if not 0 <= index < len(self._pages):
            return False
        if index == self._current:
            return True
        previous = self.currentWidget()
        current = self._pages[index]
        # Hide first to prevent one-frame overlap when pages contain tables or
        # other full-width hit-test surfaces. Only two native visibility calls.
        if previous is not None:
            previous.setVisible(False)
        current.setVisible(True)
        self._current = index
        self.currentChanged.emit(index)
        return True

    def setCurrentWidget(self, widget):
        index = self.indexOf(widget)
        return False if index < 0 else self.setCurrentIndex(index)

    def removeWidget(self, widget):
        self._require_ui()
        index = self.indexOf(widget)
        if index < 0:
            return False
        was_current = index == self._current
        if was_current:
            widget.setVisible(False)
        self._pages.pop(index)
        # Match QStackedWidget: removing a page does not delete it or transfer
        # QObject ownership. The caller may reinsert or explicitly reparent it.
        if not self._pages:
            self._current = -1
            if was_current:
                self.currentChanged.emit(-1)
        elif was_current:
            self._current = -1
            self.setCurrentIndex(min(index, len(self._pages) - 1))
        elif index < self._current:
            self._current -= 1
        self.updateGeometry()
        return True

    def sizeHint(self):
        hints = [page.sizeHint() for page in self._pages]
        valid = [hint for hint in hints if hint.isValid()]
        if not valid:
            return super().sizeHint()
        from ..core.object import QSize
        return QSize(max(hint.width() for hint in valid), max(hint.height() for hint in valid))


QStackedWidget = ImGuiStackedWidget


# Historical Qt-style alias: implementation remains Dear ImGui/DPG.
QTabWidget = ImGuiTabWidget

__all__ = ["ImGuiTabPage", "ImGuiTabWidget", "QTabWidget", "ImGuiStackedWidget", "QStackedWidget"]
