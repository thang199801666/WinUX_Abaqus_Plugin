"""Measure the real login body's scroll extent using the native renderer."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import WinUx
from DearUIQt.backends import dpg
from DearUIQt.backends.native_windows import NativeWindowBackend
from WinUx.ui import StandaloneUiHost, configure_ui_context
from WinUx.dialogs.login_form import LoginForm
from WinUx.ui.components.explorer_list_view import apply_white_explorer_theme


def main():
    dpg.create_context()
    dialog = None
    try:
        NativeWindowBackend(dpg).enable()
        host = StandaloneUiHost(dpg)
        configure_ui_context(host)
        dpg.create_viewport(title="Login layout check", width=800, height=600)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        apply_white_explorer_theme()
        dialog = LoginForm(host, lambda *args: None, initial={})
        for _ in range(10):
            host.pump()
            dpg.render_dearpygui_frame()
        maximum = dpg.get_y_scroll_max(dialog.content)
        assert maximum == 0, ("Login body should not scroll", maximum)
        for tag in (dialog.host, dialog.port, dialog.username, dialog.password,
                    dialog.remember, dialog.connect_button, dialog.cancel_button):
            assert dpg.get_item_state(tag).get("visible"), ("Clipped login control", tag)
        print("LOGIN_LAYOUT_OK", "body_scroll_max=", maximum,
              "size=", dpg.get_item_rect_size(dialog.tag))
    finally:
        if dialog is not None:
            dialog.destroy()
        dpg.destroy_context()


if __name__ == "__main__":
    main()
