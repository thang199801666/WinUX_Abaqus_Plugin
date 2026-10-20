from collections import deque

from DearUIQt.QtCore import QEvent, Qt
from DearUIQt.QtGui import QKeyEvent, QMouseEvent
from DearUIQt.QtWidgets import QApplication, QWidget


class Scheduler:
    def __init__(self):
        self.pending = deque()

    def after(self, _delay, callback, *args):
        self.pending.append((callback, args))
        return len(self.pending)


class Backend:
    def __init__(self):
        self.config = {1: {}, 2: {}}
        self.focused = None

    def configure_item(self, tag, **values):
        self.config.setdefault(tag, {}).update(values)

    def does_item_exist(self, tag):
        return tag in self.config

    def get_item_configuration(self, tag):
        return dict(self.config.get(tag, {}))

    def get_item_parent(self, tag):
        return 0

    def focus_item(self, tag):
        self.focused = tag

    def delete_item(self, tag):
        self.config.pop(tag, None)


class KeyWidget(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.keys = []

    def keyPressEvent(self, event):
        self.keys.append((event.key(), event.modifiers()))
        event.accept()


class MouseWidget(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.presses = []

    def mousePressEvent(self, event):
        self.presses.append(event.position())
        event.accept()


def test_qwidget_key_event_hook_participates_in_qapplication_dispatch():
    scheduler = Scheduler()
    backend = Backend()
    app = QApplication(after=scheduler.after)
    try:
        widget = KeyWidget(1, backend=backend, after=scheduler.after)
        app._set_focus_widget(widget)
        assert app.dispatchKeyEvent(
            QKeyEvent(QEvent.KeyPress, 77, Qt.ControlModifier)) is True
        assert widget.keys == [(77, Qt.ControlModifier)]
    finally:
        app.delete()


def test_default_child_key_handler_ignores_and_bubbles_to_parent_widget():
    scheduler = Scheduler()
    backend = Backend()
    app = QApplication(after=scheduler.after)
    try:
        parent = KeyWidget(1, backend=backend, after=scheduler.after)
        child = QWidget(2, parent=parent, backend=backend, after=scheduler.after)
        app._set_focus_widget(child)
        assert app.dispatchKeyEvent(QKeyEvent(QEvent.KeyPress, 88)) is True
        assert parent.keys == [(88, Qt.NoModifier)]
    finally:
        app.delete()


def test_qwidget_mouse_hook_receives_qmouseevent_through_normal_event_path():
    backend = Backend()
    widget = MouseWidget(1, backend=backend)
    event = QMouseEvent(
        QEvent.MouseButtonPress, (12, 20), button=Qt.LeftButton,
        buttons=Qt.LeftButton)
    assert widget.sendEvent(event) is True
    assert widget.presses == [(12.0, 20.0)]
