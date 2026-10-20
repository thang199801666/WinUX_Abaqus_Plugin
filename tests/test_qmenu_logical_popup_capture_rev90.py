from collections import deque
from pathlib import Path

from DearUIQt.qt import QApplication, QEvent, QInputTarget, QMouseEvent, Qt

ROOT = Path(__file__).resolve().parents[1]


class Scheduler:
    def __init__(self):
        self.pending = deque()

    def after(self, _delay, callback, *args):
        self.pending.append((callback, args))
        return len(self.pending)


def test_qmenu_has_no_viewport_sized_visual_input_shield():
    source = (ROOT / "DearUIQt" / "widgets" / "menu.py").read_text(encoding="utf-8")
    ctor = source[source.index("class ImGuiMenu"):source.index("def _install_keyboard_handlers")]
    shield = source[source.index("def setInputShieldTop"):source.index("def exists")]
    popup = source[source.index("def popup("):source.index("def hide(")]

    # Regression for embedded DPG/native hosts: a fullscreen no-background
    # Dear ImGui window can expose the renderer clear colour as a black panel.
    assert "tag=self._input_shield_tag" not in ctor
    assert "get_viewport_client_width" not in shield
    assert "get_viewport_client_height" not in shield
    assert "configure_item" not in shield
    assert "focus_item" not in shield
    assert "self._show_input_shield()" not in popup
    assert "acquire_popup_input(self)" in popup


def test_menubar_opens_popup_without_fullscreen_blocker():
    source = (ROOT / "DearUIQt" / "widgets" / "menu_bar.py").read_text(encoding="utf-8")
    block = source[source.index("def _open_menu"):source.index("def _menu_hidden")]
    assert "menu.popup((x, popup_y))" in block
    assert "setInputShieldTop" not in block


def test_registering_popup_moves_hover_off_background_and_releases_old_grab():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    background = QInputTarget(parent=app, pointer_handler=lambda _event: True,
                              hit_test=lambda _pos: True)
    popup = QInputTarget(parent=app, pointer_handler=lambda _event: True,
                         hit_test=lambda _pos: False)
    try:
        app._set_hover_pointer_target(background)
        app.setMouseGrabberObject(background)
        assert app._register_popup(popup)
        assert app.activePopupWidget() is popup
        assert app.hoverPointerObject() is popup
        assert app.mouseGrabberObject() is None

        assert app._unregister_popup(popup)
        assert app.activePopupWidget() is None
        assert app.hoverPointerObject() is None
    finally:
        background.delete()
        popup.delete()
        app.delete()


def test_press_callback_that_opens_popup_does_not_recapture_background():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    popup = QInputTarget(parent=app, pointer_handler=lambda _event: True,
                         hit_test=lambda _pos: False)

    def open_popup(_event):
        app._register_popup(popup)
        return True

    background = QInputTarget(parent=app, pointer_handler=open_popup,
                              hit_test=lambda _pos: True)
    try:
        assert app.dispatchPointerEvent(QMouseEvent(
            QEvent.MouseButtonPress, (10, 10), button=Qt.RightButton,
            buttons=Qt.RightButton))
        assert app.activePopupWidget() is popup
        assert app.mouseGrabberObject() is popup
        assert app.hoverPointerObject() is popup
    finally:
        app._unregister_popup(popup)
        background.delete()
        popup.delete()
        app.delete()
