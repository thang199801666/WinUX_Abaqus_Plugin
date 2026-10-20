"""Check native dialog placement on its very first rendered frame."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import WinUx
from DearUIQt.backends import dpg
from DearUIQt.backends.native_windows import NativeWindowBackend
from DearUIQt.core.application import QApplication
from WinUx.ui import StandaloneUiHost, configure_ui_context
from WinUx.dialogs.login_form import LoginForm
from WinUx.view import WinUXView


def rect(hwnd):
    bounds = wintypes.RECT()
    user32 = ctypes.windll.user32
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    assert user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(bounds))
    return bounds.left, bounds.top, bounds.right, bounds.bottom


def main():
    dpg.create_context()
    native = NativeWindowBackend(dpg)
    native.enable()
    app = None
    dialog = None
    nested = None
    try:
        host = StandaloneUiHost(dpg)
        configure_ui_context(host)
        host.is_standalone_ui_host = False
        app = QApplication(after=host.after)
        host._qapplication = app
        dpg.create_viewport(title="WinUX first-show check", width=900, height=650,
                            x_pos=230, y_pos=140)
        with dpg.window(tag="first_show_parent"):
            dpg.add_text("Parent window")
        dpg.set_primary_window("first_show_parent", True)
        host.primary_window_tag = "first_show_parent"
        host._find_main_viewport_hwnd = lambda: WinUXView._find_main_viewport_hwnd(host)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        for _ in range(4):
            host.pump()
            dpg.render_dearpygui_frame()
        parent_hwnd = host._find_main_viewport_hwnd()
        parent = rect(parent_hwnd)
        dialog = LoginForm(host, lambda *args: None, initial={})
        samples = []
        for _ in range(6):
            host.pump()
            dpg.render_dearpygui_frame()
            hwnd = native.winId(dialog.tag)
            if hwnd:
                samples.append(rect(hwnd))
        assert samples, "No native dialog appeared"
        assert dialog._native_center_prepared, "Pre-show placement failed"
        assert len(set(samples)) == 1, ("Dialog moved after first frame", samples)
        first = samples[0]
        assert abs((first[0] + first[2]) - (parent[0] + parent[2])) <= 2, (parent, first)
        assert abs((first[1] + first[3]) - (parent[1] + parent[3])) <= 2, (parent, first)
        print("DIALOG_FIRST_SHOW_CENTERED_OK", "parent=", parent, "frames=", samples)

        # Move the owner away from the main window's center. A nested dialog
        # must use that owner, not the original main viewport or desktop.
        x, y = dpg.get_item_pos(dialog.tag)
        dpg.set_item_pos(dialog.tag, (x + 80, y + 30))
        for _ in range(3):
            host.pump()
            dpg.render_dearpygui_frame()
        moved_parent = rect(native.winId(dialog.tag))
        nested = LoginForm(host, lambda *args: None, initial={})
        nested_frames = []
        for _ in range(5):
            host.pump()
            dpg.render_dearpygui_frame()
            hwnd = native.winId(nested.tag)
            if hwnd:
                nested_frames.append(rect(hwnd))
        assert nested_frames and len(set(nested_frames)) == 1, nested_frames
        child = nested_frames[0]
        assert abs(child[0] + child[2] - moved_parent[0] - moved_parent[2]) <= 2
        assert abs(child[1] + child[3] - moved_parent[1] - moved_parent[3]) <= 2
        print("NESTED_DIALOG_FIRST_SHOW_OK", nested_frames)
        nested.destroy()
        nested = None
        for _ in range(3):
            host.pump()
            dpg.render_dearpygui_frame()
        dialog.hide()
        for _ in range(3):
            host.pump()
            dpg.render_dearpygui_frame()
        dialog.show()
        reopened_frames = []
        for _ in range(5):
            host.pump()
            dpg.render_dearpygui_frame()
            hwnd = native.winId(dialog.tag)
            if hwnd:
                reopened_frames.append(rect(hwnd))
        assert reopened_frames and len(set(reopened_frames)) == 1, reopened_frames
        assert reopened_frames[0] == first, (first, reopened_frames)
        print("DIALOG_REOPEN_CENTERED_OK", reopened_frames)
    finally:
        if nested is not None:
            nested.destroy()
        if dialog is not None:
            dialog.destroy()
        if app is not None:
            app.delete()
        dpg.destroy_context()


if __name__ == "__main__":
    main()
