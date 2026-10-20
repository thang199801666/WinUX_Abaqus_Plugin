from collections import deque
from contextlib import contextmanager
from pathlib import Path

from DearUIQt.qt import QApplication, QEvent, QInputTarget, QKeyEvent, Qt


class Scheduler:
    def __init__(self):
        self.pending = deque()

    def after(self, _delay, callback, *args):
        self.pending.append((callback, args))
        return len(self.pending)


class FakeBackend:
    mvKey_Escape = 1
    mvKey_Return = 2
    mvKey_Up = 3
    mvKey_A = 4
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

    def does_item_exist(self, tag):
        return tag in self.live

    def delete_item(self, tag):
        self.live.discard(tag)

    def is_key_down(self, key):
        return key in self.down


def test_input_target_owns_focus_object_without_becoming_active_window():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    changes = []
    keys = []
    first = QInputTarget(
        key_handler=lambda event: keys.append(event.key()) or True,
        focus_handler=lambda focused: changes.append(("first", focused)),
    )
    second = QInputTarget(
        focus_handler=lambda focused: changes.append(("second", focused)),
    )
    try:
        assert first.setFocus() is True
        assert app.focusObject() is first
        assert app.focusWidget() is None
        assert app.activeWindow() is None
        assert app.dispatchKeyEvent(QKeyEvent(QEvent.KeyPress, 44)) is True
        assert keys == [44]

        assert second.setFocus() is True
        assert app.focusObject() is second
        assert changes == [("first", True), ("first", False), ("second", True)]
    finally:
        first.delete()
        second.delete()
        app.delete()


def test_input_target_popup_is_exclusive_and_guarded_on_delete():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    delivered = []
    focus = QInputTarget(key_handler=lambda event: delivered.append("focus") or True)
    popup = QInputTarget(key_handler=lambda event: delivered.append("popup") or True)
    try:
        focus.setFocus()
        assert popup.grabPopup() is True
        assert app.activePopupWidget() is popup
        assert app.dispatchKeyEvent(QKeyEvent(QEvent.KeyPress, 7)) is True
        assert delivered == ["popup"]

        popup.delete()
        assert app.activePopupWidget() is None
        assert app.focusObject() is focus
        assert app.dispatchKeyEvent(QKeyEvent(QEvent.KeyPress, 8)) is True
        assert delivered == ["popup", "focus"]
    finally:
        focus.delete()
        app.delete()


def test_application_input_backend_query_tracks_live_registry():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    backend = FakeBackend()
    try:
        assert app.hasInputBackend() is False
        assert app.installInputBackend(backend) is True
        assert app.inputBackend() is backend
        assert app.hasInputBackend(backend) is True
        backend.live.clear()
        assert app.inputBackend() is None
        assert app.hasInputBackend(backend) is False
    finally:
        app.delete()


def test_explorer_uses_qapplication_input_target_with_legacy_key_fallback_only():
    root = Path(__file__).resolve().parents[1]
    list_view = (root / "WinUx" / "ui" / "components" / "explorer_list_view.py").read_text(encoding="utf-8")
    menu = (root / "WinUx" / "ui" / "components" / "explorer_context_menu.py").read_text(encoding="utf-8")
    keyboard = (root / "WinUx" / "ui" / "components" / "explorer_keyboard.py").read_text(encoding="utf-8")

    assert "QInputTarget(" in list_view
    assert "application.hasInputBackend(dpg)" in list_view
    assert "if not self._uses_qapplication_keyboard():" in list_view
    assert "target.grabPopup()" in menu
    assert "target.releasePopup()" in menu
    assert "def handle_qt_key_event(self, event):" in keyboard
    assert "Qt.ControlModifier" in keyboard


def test_explorer_keyboard_controller_consumes_qkeyevent_modifiers_without_backend_polling():
    from WinUx.ui.components.explorer_keyboard import ExplorerKeyboardController, ExplorerKeyboardInput

    class Backend:
        mvKey_Escape = 1
        mvKey_A = 2

    class View:
        _has_focus = True
        _rename_active = False

        def __init__(self):
            self.selected_all = 0
            self.hidden = 0

        def _context_menu_is_visible(self):
            return False

        def select_all(self):
            self.selected_all += 1

        def cancel_inline_rename(self):
            return False

        def _cancel_current_operation(self):
            self.hidden += 1

        def _clear_hover(self):
            pass

    view = View()
    # The fallback modifier probes intentionally return False. The QKeyEvent
    # modifier must be authoritative on the QApplication route.
    controller = ExplorerKeyboardController(
        view, Backend(),
        ExplorerKeyboardInput(
            ctrl=lambda: False, shift=lambda: False, alt=lambda: False,
            overlay_owns_input=lambda: False,
            pointer_blocked=lambda _owner=None: False,
        ),
    )
    assert controller.handle_qt_key_event(
        QKeyEvent(QEvent.KeyPress, Backend.mvKey_A, Qt.ControlModifier)) is True
    assert view.selected_all == 1
    assert controller.handle_qt_key_event(
        QKeyEvent(QEvent.KeyPress, Backend.mvKey_Escape)) is True
    assert view.hidden == 1
