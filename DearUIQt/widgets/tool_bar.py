"""Generic Qt-style tool/status bars composed from DearUIQt widgets."""
from __future__ import annotations

from ..gui.action import QAction
from .buttons import QLabel, QToolButton
from ..core.object import Qt, Signal
from ..layouts.box import QHBoxLayout, QVBoxLayout
from .widget import QWidget


class QToolBar(QWidget):
    """Reusable action strip analogous to ``QToolBar``.

    Icons/resources are deliberately not owned here.  Applications may bind a
    QAction to a QToolButton, provide custom widgets, or subclass QToolButton to
    render image resources without coupling this framework to one asset system.
    """

    def __init__(self, title="", *, orientation=Qt.Horizontal, parent=None,
                 after=None, backend=None, movable=False, floatable=False):
        if orientation not in (Qt.Horizontal, Qt.Vertical):
            raise ValueError("toolbar orientation must be Qt.Horizontal or Qt.Vertical")
        backend, options = self._construction(parent, backend)
        tag = backend.add_child_window(
            width=-1,
            height=32 if orientation == Qt.Horizontal else -1,
            border=False,
            no_scrollbar=True,
            no_scroll_with_mouse=True,
            **options,
        )
        super().__init__(tag, parent=parent, after=after, backend=backend)
        self.actionTriggered = Signal(self)
        self._title = str(title or "")
        self._orientation = orientation
        self._movable = bool(movable)
        self._floatable = bool(floatable)
        self._icon_size = (20, 20)
        self._actions = []
        self._action_buttons = {}
        self._layout = self._make_layout()
        self.setLayout(self._layout)

    def _make_layout(self):
        layout_cls = QHBoxLayout if self._orientation == Qt.Horizontal else QVBoxLayout
        return layout_cls(spacing=2, parent=self, after=self._after, backend=self.backend)

    def windowTitle(self):
        return self._title

    def setWindowTitle(self, title):
        self._title = str(title or "")
        self._window_title = self._title

    def orientation(self):
        return self._orientation

    def setOrientation(self, orientation):
        if orientation not in (Qt.Horizontal, Qt.Vertical):
            raise ValueError("toolbar orientation must be Qt.Horizontal or Qt.Vertical")
        if orientation == self._orientation:
            return
        self._orientation = orientation
        self._configure("width", -1 if orientation == Qt.Horizontal else 32)
        self._configure("height", 32 if orientation == Qt.Horizontal else -1)
        # Keep action/button ownership stable; Dear ImGui groups cannot change
        # orientation in place, so migrate children to a fresh retained layout.
        old = self.takeLayout()
        new = self._make_layout()
        self.setLayout(new)
        for child in list(old._items()):
            old.takeAt(old.indexOf(child))
            new.addWidget(child)
        old.delete()
        self._layout = new

    def addAction(self, action, callback=None):
        if isinstance(action, str):
            created = QAction(action, parent=self)
            if callback is not None:
                created.triggered.connect(callback)
            action = created
        elif not isinstance(action, QAction):
            raise TypeError("toolbar action must be QAction or text")
        if action in self._actions:
            return action
        if action.parent is None:
            action.setParent(self)
        icon = action.icon()
        button = QToolButton(
            "" if icon is not None else action.text(),
            parent=self._layout, after=self._after,
            backend=self.backend, auto_raise=True, icon=icon,
            icon_size=self._icon_size)
        button.setDefaultAction(action)
        button.clicked.connect(lambda _action=action: self.actionTriggered.emit(_action))
        self._layout.addWidget(button)
        self._actions.append(action)
        self._action_buttons[action] = button
        return action

    def insertAction(self, before, action):
        self.addAction(action)
        if before not in self._actions or action is before:
            return action
        self._actions.remove(action)
        index = self._actions.index(before)
        self._actions.insert(index, action)
        button = self._action_buttons[action]
        self._layout.insertWidget(index, button)
        return action

    def removeAction(self, action):
        if action not in self._actions:
            return False
        self._actions.remove(action)
        button = self._action_buttons.pop(action, None)
        if button is not None:
            index = self._layout.indexOf(button)
            if index >= 0:
                self._layout.takeAt(index)
            button.delete()
        return True

    def actions(self):
        return list(self._actions)

    def widgetForAction(self, action):
        return self._action_buttons.get(action)

    def addWidget(self, widget):
        self._layout.addWidget(widget)
        return widget

    def addSeparator(self):
        try:
            tag = self.backend.add_separator(parent=self._layout.tag)
        except Exception:
            tag = self.backend.add_spacer(
                parent=self._layout.tag,
                width=1 if self._orientation == Qt.Horizontal else -1,
                height=-1 if self._orientation == Qt.Horizontal else 1,
            )
        separator = QWidget(tag, parent=self._layout, after=self._after, backend=self.backend)
        return separator

    def setIconSize(self, size):
        if isinstance(size, (tuple, list)):
            if len(size) != 2:
                raise ValueError("icon size requires width and height")
            width, height = map(int, size)
        else:
            width = height = int(size)
        self._icon_size = (max(1, width), max(1, height))

    def iconSize(self):
        return self._icon_size

    def setMovable(self, movable):
        self._movable = bool(movable)

    def isMovable(self):
        return self._movable

    def setFloatable(self, floatable):
        self._floatable = bool(floatable)

    def isFloatable(self):
        return self._floatable


class QStatusBar(QWidget):
    """Simple status line with transient text and permanent widgets."""

    def __init__(self, *, parent=None, after=None, backend=None):
        backend, options = self._construction(parent, backend)
        tag = backend.add_child_window(
            width=-1, height=24, border=False,
            no_scrollbar=True, no_scroll_with_mouse=True, **options)
        super().__init__(tag, parent=parent, after=after, backend=backend)
        self.messageChanged = Signal(self)
        self._layout = QHBoxLayout(spacing=6, parent=self, after=after, backend=backend)
        self.setLayout(self._layout)
        self._message_label = QLabel("", parent=self._layout, after=after, backend=backend)
        self._layout.addWidget(self._message_label)
        self._permanent_widgets = []
        self._message = ""
        self._clear_generation = 0

    def showMessage(self, message, timeout=0):
        self._message = str(message or "")
        self._message_label.setText(self._message)
        self.messageChanged.emit(self._message)
        self._clear_generation += 1
        generation = self._clear_generation
        if timeout and self._after is not None:
            self._after(max(0, int(timeout)), self._clear_if_generation, generation)

    def _clear_if_generation(self, generation):
        if generation == self._clear_generation:
            self.clearMessage()

    def clearMessage(self):
        if not self._message:
            return
        self._message = ""
        self._message_label.setText("")
        self.messageChanged.emit("")
        self._clear_generation += 1

    def currentMessage(self):
        return self._message

    def addWidget(self, widget, stretch=0):
        del stretch
        self._layout.addWidget(widget)
        return widget

    def addPermanentWidget(self, widget, stretch=0):
        del stretch
        self._layout.addWidget(widget)
        self._permanent_widgets.append(widget)
        return widget

    def removeWidget(self, widget):
        index = self._layout.indexOf(widget)
        if index < 0:
            return False
        self._layout.takeAt(index)
        if widget in self._permanent_widgets:
            self._permanent_widgets.remove(widget)
        return True


__all__ = ["QToolBar", "QStatusBar"]
