"""Dear ImGui tab containers with QTabWidget-like retained semantics.

The implementation is entirely Dear PyGui.  Qt terminology describes only the
visual/behavioral contract so dialog code can use one consistent API without
introducing another UI toolkit.
"""
from __future__ import annotations

from .controls import QWidget
from .core import Signal
from .imgui_qt_style import bind_theme, tab_widget_theme


class ImGuiTabPage(QWidget):
    """One page owned by :class:`ImGuiTabWidget`."""

    def __init__(self, tag, label, *, parent, after=None, backend=None):
        super().__init__(tag, parent=parent, after=after, backend=backend)
        self._label = str(label)

    def text(self):
        return self._label

    def setText(self, text):
        self._label = str(text)
        self._on_ui("label", self._configure, "label", self._label)


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
        page_tag = self.backend.add_tab(label=str(label), parent=self.tag)
        page = ImGuiTabPage(
            page_tag, label, parent=self, after=self._after, backend=self.backend)
        self._pages.append(page)
        if self._current < 0:
            self._current = 0
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
        index = int(index)
        if not 0 <= index < len(self._pages):
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
        index = int(index)
        page = self.widget(index)
        if page is None:
            return False
        was_current = index == self._current
        self._pages.pop(index)
        page.delete()
        if not self._pages:
            next_index = -1
        elif self._current > index:
            next_index = self._current - 1
        elif was_current:
            next_index = min(index, len(self._pages) - 1)
        else:
            next_index = self._current
        changed = next_index != self._current
        self._current = next_index
        if self._current >= 0:
            try:
                self.backend.set_value(self.tag, self._pages[self._current].tag)
            except Exception:
                pass
        if changed or was_current:
            self.currentChanged.emit(self._current)
        return True

    def _changed(self, sender=None, app_data=None, user_data=None):
        native = app_data
        index = next(
            (i for i, page in enumerate(self._pages) if page.tag == native),
            self._current,
        )
        if index != self._current:
            self._current = index
            self.currentChanged.emit(index)


# Historical Qt-style alias: implementation remains Dear ImGui/DPG.
QTabWidget = ImGuiTabWidget

__all__ = ["ImGuiTabPage", "ImGuiTabWidget", "QTabWidget"]
