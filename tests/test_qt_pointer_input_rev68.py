from collections import deque
from contextlib import contextmanager
from pathlib import Path

from DearUIQt.qt import QApplication, QEvent, QInputTarget, QMouseEvent, Qt


class Scheduler:
    def __init__(self):
        self.pending = deque()

    def after(self, _delay, callback, *args):
        self.pending.append((callback, args))
        return len(self.pending)


class PointerBackend:
    mvKey_Escape = 1
    mvMouseButton_Left = 10
    mvMouseButton_Right = 11
    mvMouseButton_Middle = 12
    mvKey_LControl = 20
    mvKey_RControl = 21
    mvKey_LShift = 22
    mvKey_RShift = 23
    mvKey_LAlt = 24
    mvKey_RAlt = 25

    def __init__(self):
        self._next = 100
        self.live = set()
        self.key_handlers = []
        self.click_handlers = []
        self.release_handlers = []
        self.move_handlers = []
        self.keys_down = set()
        self.buttons_down = set()
        self.mouse = (0.0, 0.0)

    @contextmanager
    def handler_registry(self):
        tag = self._next
        self._next += 1
        self.live.add(tag)
        yield tag

    def add_key_press_handler(self, *, key, callback, user_data=None):
        self.key_handlers.append((key, callback, user_data))

    def add_mouse_click_handler(self, *, button, callback, user_data=None):
        self.click_handlers.append((button, callback, user_data))

    def add_mouse_release_handler(self, *, button, callback, user_data=None):
        self.release_handlers.append((button, callback, user_data))

    def add_mouse_move_handler(self, *, callback):
        self.move_handlers.append(callback)

    def does_item_exist(self, tag):
        return tag in self.live

    def delete_item(self, tag):
        self.live.discard(tag)

    def is_key_down(self, key):
        return key in self.keys_down

    def is_mouse_button_down(self, button):
        return button in self.buttons_down

    def get_mouse_pos(self, local=False):
        return self.mouse


def test_qmouseevent_preserves_position_buttons_and_modifiers():
    event = QMouseEvent(
        QEvent.MouseButtonPress, (12, 34), button=Qt.LeftButton,
        buttons=Qt.LeftButton, modifiers=Qt.ControlModifier | Qt.ShiftModifier,
    )
    assert event.position() == (12.0, 34.0)
    assert event.globalPosition() == (12.0, 34.0)
    assert event.button() == Qt.LeftButton
    assert event.buttons() == Qt.LeftButton
    assert event.modifiers() == Qt.ControlModifier | Qt.ShiftModifier


def test_pointer_hit_test_hover_and_implicit_grab_follow_qt_priority():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    seen = []

    def handler(name):
        def _handle(event):
            seen.append((name, event.type()))
            return True
        return _handle

    left = QInputTarget(
        parent=app, pointer_handler=handler("left"),
        hit_test=lambda pos: pos[0] < 50,
    )
    right = QInputTarget(
        parent=app, pointer_handler=handler("right"),
        hit_test=lambda pos: pos[0] >= 50,
    )
    try:
        assert app.dispatchPointerEvent(QMouseEvent(QEvent.MouseMove, (10, 5))) is True
        assert app.hoverPointerObject() is left
        assert seen[-2:] == [("left", QEvent.Enter), ("left", QEvent.MouseMove)]

        assert app.dispatchPointerEvent(QMouseEvent(
            QEvent.MouseButtonPress, (10, 5), button=Qt.LeftButton,
            buttons=Qt.LeftButton)) is True
        assert app.mouseGrabberObject() is left

        # Capture keeps routing to the press owner outside its geometry.
        assert app.dispatchPointerEvent(QMouseEvent(
            QEvent.MouseMove, (90, 5), buttons=Qt.LeftButton)) is True
        assert seen[-1] == ("left", QEvent.MouseMove)

        assert app.dispatchPointerEvent(QMouseEvent(
            QEvent.MouseButtonRelease, (90, 5), button=Qt.LeftButton,
            buttons=Qt.NoButton)) is True
        assert app.mouseGrabberObject() is None
        assert app.hoverPointerObject() is right
        assert seen[-2:] == [("left", QEvent.Leave), ("right", QEvent.Enter)]

        assert app.dispatchPointerEvent(QMouseEvent(QEvent.MouseMove, (90, 5))) is True
        assert seen[-1] == ("right", QEvent.MouseMove)
    finally:
        left.delete()
        right.delete()
        app.delete()


def test_application_installs_one_pointer_bridge_and_maps_native_state():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    backend = PointerBackend()
    delivered = []
    target = QInputTarget(
        parent=app,
        pointer_handler=lambda event: delivered.append(event) or True,
        hit_test=lambda _pos: True,
    )
    try:
        assert app.installInputBackend(backend) is True
        assert app.hasPointerInputBackend(backend) is True
        registry = app._input_handler_registry
        assert len(backend.click_handlers) == 3
        assert len(backend.release_handlers) == 3
        assert len(backend.move_handlers) == 1

        # Re-install is idempotent: no duplicate global handlers.
        assert app.installInputBackend(backend) is True
        assert app._input_handler_registry == registry
        assert len(backend.click_handlers) == 3

        backend.mouse = (15.0, 20.0)
        backend.buttons_down.add(backend.mvMouseButton_Left)
        backend.keys_down.add(backend.mvKey_LControl)
        left_press = next(item for item in backend.click_handlers
                          if item[0] == backend.mvMouseButton_Left)
        _button, callback, user_data = left_press
        assert callback(user_data=user_data) is True
        event = delivered[-1]
        assert event.type() == QEvent.MouseButtonPress
        assert event.button() == Qt.LeftButton
        assert event.buttons() & Qt.LeftButton
        assert event.modifiers() & Qt.ControlModifier
        assert app.mouseGrabberObject() is target

        backend.mouse = (200.0, 300.0)
        backend.move_handlers[0]()
        assert delivered[-1].globalPosition() == (200.0, 300.0)

        backend.buttons_down.clear()
        left_release = next(item for item in backend.release_handlers
                            if item[0] == backend.mvMouseButton_Left)
        _button, callback, user_data = left_release
        assert callback(user_data=user_data) is True
        assert app.mouseGrabberObject() is None
    finally:
        target.delete()
        app.delete()


def test_explorer_uses_application_pointer_bridge_with_standalone_fallback():
    root = Path(__file__).resolve().parents[1]
    list_view = (root / "WinUx" / "ui" / "components" / "explorer_list_view.py").read_text(encoding="utf-8")
    pointer = (root / "WinUx" / "ui" / "components" / "explorer_pointer_dispatch.py").read_text(encoding="utf-8")

    assert "pointer_handler=self._handle_qt_pointer_event" in list_view
    assert "hit_test=self._qt_pointer_hit_test" in list_view
    assert "application.hasPointerInputBackend(dpg)" in list_view
    assert "if not central_pointer:" in list_view
    assert "def _handle_qt_pointer_event(self, event):" in pointer
    assert "event.buttons() & Qt.LeftButton" in pointer
    assert "event.modifiers()" in pointer
