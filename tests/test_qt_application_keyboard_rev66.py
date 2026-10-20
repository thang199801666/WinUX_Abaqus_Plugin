from collections import deque
from contextlib import contextmanager

from DearUIQt.qt import QApplication, QEvent, QKeyEvent, QObject, Qt


class Scheduler:
    def __init__(self):
        self.pending = deque()

    def after(self, _delay, callback, *args):
        self.pending.append((callback, args))
        return len(self.pending)


class KeyTarget(QObject):
    def __init__(self, name, *, handled=True, **kwargs):
        super().__init__(**kwargs)
        self.name = name
        self.handled = handled
        self.keys = []

    def event(self, event):
        if event.type() == QEvent.KeyPress:
            self.keys.append((event.key(), event.modifiers()))
            return self.handled
        return super().event(event)


class FakeBackend:
    mvKey_Escape = 1
    mvKey_Return = 2
    mvKey_Up = 3
    mvKey_LControl = 10
    mvKey_RControl = 11
    mvKey_LShift = 12
    mvKey_RShift = 13
    mvKey_LAlt = 14
    mvKey_RAlt = 15

    def __init__(self):
        self._next = 100
        self.live = set()
        self.handlers = []
        self.down = set()

    @contextmanager
    def handler_registry(self):
        tag = self._next
        self._next += 1
        self.live.add(tag)
        yield tag

    def add_key_press_handler(self, *, key, callback, user_data=None):
        self.handlers.append((key, callback, user_data))
        return len(self.handlers)

    def does_item_exist(self, tag):
        return tag in self.live

    def delete_item(self, tag):
        self.live.discard(tag)

    def is_key_down(self, key):
        return key in self.down


def test_key_event_priority_popup_then_modal_then_focus_chain():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    try:
        window = KeyTarget("window", handled=True, after=scheduler.after)
        focus = KeyTarget("focus", parent=window, handled=False)
        modal = KeyTarget("modal", handled=True, after=scheduler.after)
        popup = KeyTarget("popup", handled=True, after=scheduler.after)
        app._set_active_window(window)
        app._set_focus_widget(focus)

        assert app.dispatchKeyEvent(QKeyEvent(QEvent.KeyPress, 7)) is True
        assert focus.keys == [(7, Qt.NoModifier)]
        assert window.keys == [(7, Qt.NoModifier)]

        app._register_modal(modal)
        assert app.dispatchKeyEvent(QKeyEvent(QEvent.KeyPress, 8)) is True
        assert modal.keys == [(8, Qt.NoModifier)]
        assert focus.keys == [(7, Qt.NoModifier)]

        app._register_popup(popup)
        assert app.dispatchKeyEvent(QKeyEvent(QEvent.KeyPress, 9)) is True
        assert popup.keys == [(9, Qt.NoModifier)]
        assert modal.keys == [(8, Qt.NoModifier)]
    finally:
        app.delete()


def test_native_input_bridge_is_singleton_per_application_and_maps_modifiers():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    backend = FakeBackend()
    target = KeyTarget("focus", handled=True, after=scheduler.after)
    try:
        app._set_focus_widget(target)
        assert app.installInputBackend(backend) is True
        registry = app._input_handler_registry
        handler_count = len(backend.handlers)
        assert handler_count == 3

        # Reinstalling the same backend reuses the single application registry.
        assert app.installInputBackend(backend) is True
        assert app._input_handler_registry == registry
        assert len(backend.handlers) == handler_count

        backend.down.update({backend.mvKey_LControl, backend.mvKey_RShift})
        escape = next(item for item in backend.handlers if item[0] == backend.mvKey_Escape)
        _key, callback, user_data = escape
        assert callback(user_data=user_data) is True
        key, modifiers = target.keys[-1]
        assert key == backend.mvKey_Escape
        assert modifiers & Qt.ControlModifier
        assert modifiers & Qt.ShiftModifier
        assert not (modifiers & Qt.AltModifier)
    finally:
        app.delete()
    assert registry not in backend.live


def test_qkeyevent_validates_type_and_preserves_payload():
    event = QKeyEvent(
        QEvent.KeyPress, 42, Qt.ControlModifier | Qt.ShiftModifier,
        text="A", auto_repeat=True, count=2,
    )
    assert event.key() == 42
    assert event.modifiers() == Qt.ControlModifier | Qt.ShiftModifier
    assert event.text() == "A"
    assert event.isAutoRepeat() is True
    assert event.count() == 2


def test_retained_menu_dialog_and_view_are_wired_to_application_keyboard_bridge():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    menu = (root / "DearUIQt" / "qt" / "menu.py").read_text(encoding="utf-8")
    dialog = (root / "DearUIQt" / "dialogs" / "qt_dialog.py").read_text(encoding="utf-8")
    view = (root / "WinUx" / "view.py").read_text(encoding="utf-8")
    public = (root / "DearUIQt" / "__init__.py").read_text(encoding="utf-8")

    assert "application.installInputBackend(b)" in menu
    assert "event.type() == QEvent.KeyPress" in menu
    assert "self._application_keyboard = _install_keys()" in dialog
    assert "event_type == QEvent.KeyPress" in dialog
    assert "self._qapplication.installInputBackend(dpg)" in view
    assert '"QKeyEvent": ".qt.core"' in public
