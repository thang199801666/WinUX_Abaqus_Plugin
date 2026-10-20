"""Exercise editable Qt-style history combos inside the real SSH Login modal."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import WinUx
from DearUIQt.backends import get_backend
from DearUIQt.backends.native_windows import NativeWindowBackend
from DearUIQt.backends.dearpygui import dpg_window_rect
from DearUIQt.core import QEvent, QKeyEvent, Qt
from DearUIQt.core.application import QApplication
from DearUIQt.input_gate import popup_input_active
from WinUx.ui import StandaloneUiHost, configure_ui_context
from WinUx.dialogs.login_form import LoginForm
from WinUx.ui.components.explorer_list_view import apply_white_explorer_theme


def main():
    user32 = ctypes.windll.user32
    original_cursor = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(original_cursor))
    b = get_backend()
    b.create_context()
    b.configure_app(manual_callback_management=True)
    app, form = None, None
    try:
        NativeWindowBackend(b).enable()
        host = StandaloneUiHost(b)
        configure_ui_context(host)
        app = QApplication(after=host.after)
        app.installInputBackend(b)
        b.create_viewport(title="Login Qt combo check", width=800, height=600)
        with b.window(tag="login_check_owner"):
            b.add_text("Login owner")
        b.setup_dearpygui()
        b.set_primary_window("login_check_owner", True)
        b.show_viewport()
        apply_white_explorer_theme()
        submitted = Mock()
        form = LoginForm(host, submitted, initial={
            "hosts": ["host01", "host02"], "host": "host01", "port": "22",
            "ports": {"host02": 2222}, "usernames": ["user01", "user02"],
            "username": "user01", "password": "test-only", "remember": False})
        form.password_for = lambda name: "saved-test-only" if name == "user02" else ""
        form.show()

        def frames(count=10):
            for _ in range(count):
                host.pump()
                b.render_dearpygui_frame()
                b.run_callbacks(b.get_callback_queue())

        def key(value):
            value = {Qt.Key_Return: b.mvKey_Return, Qt.Key_Down: b.mvKey_Down,
                     Qt.Key_Escape: b.mvKey_Escape}.get(value, value)
            app.dispatchKeyEvent(QKeyEvent(QEvent.KeyPress, value))
            frames(3)

        frames()
        assert form.host_combo.isEditable() and form.username_combo.isEditable()
        assert form.host_combo._choice_field is not None
        assert b.get_y_scroll_max(form.content) == 0
        from WinUx.dialogs.floating_forms import client_layout
        form._floating_kind = "login"
        layout = client_layout(form)
        for name in ("host", "username"):
            assert layout["widgets"][name][2] <= layout["widgets"][name + "_arrow"][0] + 1, layout
            editor = getattr(form, name)
            config = b.get_item_configuration(editor)
            assert config["readonly"] is False
            assert config["hint"] == "Type or choose from history"
        form.set_control_value(form.host, "")
        form.host_combo.setFocus()
        frames()
        user32 = ctypes.windll.user32
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        hwnd = form.winId()
        assert hwnd

        def click(x, y):
            user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
            origin = wintypes.POINT()
            user32.ClientToScreen(hwnd, ctypes.byref(origin))
            # A secondary viewport needs the OS hovered-viewport state too.
            user32.SetCursorPos(round(x), round(y))
            cx, cy = round(x - origin.x), round(y - origin.y)
            packed = (cy << 16) | (cx & 0xFFFF)
            user32.PostMessageW(hwnd, 0x0200, 0, packed)
            frames(3)
            user32.PostMessageW(hwnd, 0x0201, 1, packed)
            frames(2)
            user32.PostMessageW(hwnd, 0x0202, 0, packed)
            frames()
        for char in "new-server":
            user32.PostMessageW(hwnd, 0x0102, ord(char), 0)
        frames()
        assert form._snapshot()["host"] == "new-server", form._snapshot()["host"]
        form.host_combo._choice_field.syncGeometry()
        assert form.host_combo.currentText() == "new-server"

        form.host_combo.setFocus()
        frames()
        key(b.mvKey_F4)
        assert form.host_combo.popupVisible(), (
            "Modal Login did not route F4 to the combo", b.get_focused_item(),
            type(form.focusWidget()).__name__, form._accepts_dialog_keys(),
            b.get_item_state(form.host), app.activeModalWidget() is form)
        if "--diagnostics" in sys.argv:
            print("LOGIN_COMBO_NATIVE_WINDOWS", form.winId(),
                  NativeWindowBackend(b).winId(form.host_combo._choice_popup.tag),
                  b.get_item_state(form.host_combo._choice_popup.tag))
        assert popup_input_active()
        key(Qt.Key_Down)
        key(Qt.Key_Return)
        assert form._snapshot()["host"] == "host02", form._snapshot()
        assert form._snapshot()["port"] == "2222"
        assert not form._busy and not submitted.called
        assert not popup_input_active()

        rect = dpg_window_rect(b, form.username_combo.tag)
        click(rect[2] - 8, (rect[1] + rect[3]) / 2)
        native_mouse = form.username_combo.popupVisible()
        if not native_mouse:
            print("LOGIN_MOUSE_ROUTE direct control dispatch (input desktop unavailable)")
            form.username_combo._choice_field._clicked()
            frames()
        assert form.username_combo.popupVisible()
        rect = dpg_window_rect(b, form.username_combo._choice_popup._rows["1"])
        click(rect[0] + 15, (rect[1] + rect[3]) / 2)
        assert form._snapshot()["username"] == "user02"
        assert form._snapshot()["password"] == "saved-test-only"
        assert not submitted.called

        assert form.host_combo.showPopup()
        frames()
        key(Qt.Key_Escape)
        assert form.isVisible() and not form.host_combo.popupVisible()
        assert not popup_input_active()
        form._set_busy(True)
        assert not form.host_combo.isEnabled() and not form.host_combo.showPopup()
        form._set_busy(False)
        form.host_combo.setFocus()
        frames()
        key(Qt.Key_Return)
        host.pump()
        submitted.assert_called_once()
        assert form._busy
        form._set_busy(False)
        assert form.host_combo.showPopup()
        frames()
        form.cancel_from_window()
        assert form.isVisible() and not popup_input_active()
        form.cancel_from_window()
        frames()
        assert app.activePopupWidget() is None and app.activeModalWidget() is None
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.FindWindowW.restype = wintypes.HWND
        user32.IsWindowEnabled.argtypes = [wintypes.HWND]
        owner = user32.FindWindowW(None, "Login Qt combo check")
        assert owner and user32.IsWindowEnabled(owner), "Closing Login left its owner disabled"
        print("LOGIN_QT_COMBO_OK")
    finally:
        if form is not None:
            form.destroy()
        if app is not None:
            app.delete()
        b.destroy_context()
        user32.SetCursorPos(original_cursor.x, original_cursor.y)


if __name__ == "__main__":
    main()
