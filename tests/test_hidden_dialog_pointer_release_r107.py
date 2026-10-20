"""Retained dialogs must never strand QApplication mouse capture when hidden."""
from collections import deque

from DearUIQt.qt import QApplication, QObject, QEvent, QMouseEvent, QInputTarget, QPointer, Qt


class Scheduler:
    def __init__(self):
        self.pending = deque()

    def after(self, _delay, callback, *args):
        self.pending.append((callback, args))
        return len(self.pending)


class HidingModal(QObject):
    def __init__(self, app):
        super().__init__(parent=app, after=app._after)
        self.app = app
        self.visible = True
        self.presses = 0

    def isVisible(self):
        return self.visible

    def winfo_exists(self):
        return not self._deleted

    def event(self, event):
        if event.type() == QEvent.MouseButtonPress:
            self.presses += 1
            # Equivalent to a retained QDialog OK/Cancel callback: hide and
            # unregister synchronously while the press is still dispatching.
            self.visible = False
            self.app._unregister_modal(self)
            self.app._widget_hidden(self)
            return True
        return False


def test_hidden_modal_is_not_recaptured_after_its_closing_press():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    dialog = HidingModal(app)
    explorer_events = []
    explorer = QInputTarget(
        parent=app,
        pointer_handler=lambda event: explorer_events.append(event.type()) or True,
        hit_test=lambda _pos: True,
    )
    try:
        app._register_modal(dialog)
        assert app.dispatchPointerEvent(QMouseEvent(
            QEvent.MouseButtonPress, (10, 10), button=Qt.LeftButton,
            buttons=Qt.LeftButton)) is True
        assert dialog.presses == 1
        assert app.activeModalWidget() is None
        assert app.mouseGrabberObject() is None

        # The release that follows the closing press has no hidden receiver.
        assert app.dispatchPointerEvent(QMouseEvent(
            QEvent.MouseButtonRelease, (10, 10), button=Qt.LeftButton,
            buttons=Qt.NoButton)) is True
        assert app.mouseGrabberObject() is None

        # The next independent click belongs to Explorer/ListView normally.
        assert app.dispatchPointerEvent(QMouseEvent(
            QEvent.MouseButtonPress, (10, 10), button=Qt.LeftButton,
            buttons=Qt.LeftButton)) is True
        assert explorer_events[-1] == QEvent.MouseButtonPress
        assert app.mouseGrabberObject() is explorer
    finally:
        explorer.delete()
        dialog.delete()
        app.delete()


def test_widget_hidden_releases_descendant_mouse_and_hover_ownership():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    root = QObject(parent=app, after=scheduler.after)
    child = QInputTarget(
        parent=root,
        pointer_handler=lambda _event: True,
        hit_test=lambda _pos: True,
    )
    try:
        app.setMouseGrabberObject(child)
        app._set_hover_pointer_target(child)
        assert app.mouseGrabberObject() is child
        assert app.hoverPointerObject() is child

        app._widget_hidden(root)

        assert app.mouseGrabberObject() is None
        assert app.hoverPointerObject() is None
    finally:
        child.delete()
        root.delete()
        app.delete()


def test_pointer_hit_test_self_heals_a_stale_hidden_grabber():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    hidden = HidingModal(app)
    hidden.visible = False
    explorer_events = []
    explorer = QInputTarget(
        parent=app,
        pointer_handler=lambda event: explorer_events.append(event.type()) or True,
        hit_test=lambda _pos: True,
    )
    try:
        # Simulate a stale grab left by an older/custom path.  Public grabMouse
        # now rejects hidden targets, but hit-testing must still self-heal any
        # pre-existing stale QPointer.
        app._mouse_grabber = QPointer(hidden)
        assert app.mouseGrabberObject() is hidden

        assert app.dispatchPointerEvent(QMouseEvent(
            QEvent.MouseButtonPress, (5, 5), button=Qt.LeftButton,
            buttons=Qt.LeftButton)) is True

        assert explorer_events == [QEvent.MouseButtonPress]
        assert app.mouseGrabberObject() is explorer
    finally:
        explorer.delete()
        hidden.delete()
        app.delete()
