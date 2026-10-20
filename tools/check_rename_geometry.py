"""Render an Explorer and check rename alignment against its painted canvas."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import WinUx
from DearUIQt.backends import dpg
from DearUIQt.backends.native_windows import NativeWindowBackend
from WinUx.ui import StandaloneUiHost, configure_ui_context
from WinUx.ui.components.explorer_list_view import ExplorerListView
from WinUx.ui.components.explorer_list_model import ListViewItem


def main():
    dpg.create_context()
    native = NativeWindowBackend(dpg)
    if "--native" in sys.argv:
        native.enable()
    view = None
    try:
        host = StandaloneUiHost(dpg)
        configure_ui_context(host)
        moved = "--moved" in sys.argv
        dpg.create_viewport(title="Rename geometry check", width=650, height=450,
                            x_pos=360 if moved else 100, y_pos=240 if moved else 100)
        with dpg.window(tag="rename_check_root", no_title_bar=True):
            view = ExplorerListView(
                "rename_check_root", width=600, height=350,
                items=[ListViewItem("Test-17-0285-{:02d}.inp".format(i),
                                    "C:/Test-17-0285-{:02d}.inp".format(i))
                       for i in range(79)])
        dpg.setup_dearpygui()
        dpg.show_viewport()
        for _ in range(8):
            host.pump()
            dpg.render_dearpygui_frame()
        if "--scrolled" in sys.argv:
            dpg.set_y_scroll(view.body_window, 112, when=dpg.mvSetScrollFlags_Now)
            for _ in range(3):
                host.pump()
                dpg.render_dearpygui_frame()
        index = 7 if "--scrolled" in sys.argv else 4
        view.select_indices([index])
        assert view.begin_inline_rename(index)
        request = view._rename_textbox._request
        canvas_x, canvas_y = dpg.get_item_rect_min(view.body_canvas)
        expected_y = canvas_y + index * view.ROW_HEIGHT
        expected_y += (view.ROW_HEIGHT - request.height) / 2
        assert abs(request.top - expected_y) <= 1, (request.top, expected_y)
        print("RENAME_GEOMETRY_OK", "viewport=", view._body_viewport_rect(),
              "canvas=", (canvas_x, canvas_y),
              "editor=", (request.left, request.top))
        import ctypes
        from ctypes import wintypes
        point = wintypes.POINT(0, 0)
        ctypes.windll.user32.ClientToScreen(wintypes.HWND(view._native_hwnd), ctypes.byref(point))
        expected_x, expected_y = request.left, request.top
        if not native.isEnabled():
            expected_x += point.x
            expected_y += point.y
        view._rename_textbox.pump()
        view._rename_textbox.pump()
        editor = view._rename_textbox._native_editor
        assert editor is not None and editor.is_active(), "Native EDIT was not created"

        def check_popup():
            rect = wintypes.RECT()
            assert ctypes.windll.user32.GetWindowRect(editor._hwnd_edit, ctypes.byref(rect))
            actual = (rect.left, rect.top)
            expected = (round(expected_x), round(expected_y))
            assert actual == expected, ("Native EDIT is offset from painted label", actual, expected)

        check_popup()
        # Real Win32 key dispatch, including the startup selection-repair pump.
        from WinUx.ui.components.native_rename import basename_select_end, WM_KEYDOWN, VK_RIGHT
        end = basename_select_end(request.text)
        assert editor.get_selection() == (0, end), editor.get_selection()
        ctypes.windll.user32.SendMessageW(editor._hwnd_edit, WM_KEYDOWN, VK_RIGHT, 0)
        view._rename_textbox.pump()
        assert editor.get_selection() == (end, end), editor.get_selection()
        ctypes.windll.user32.SendMessageW(editor._hwnd_edit, WM_KEYDOWN, VK_RIGHT, 0)
        assert editor.get_selection() == (end + 1, end + 1), editor.get_selection()
        print("NATIVE_RENAME_RIGHT_ARROW_OK")
        # Typing changes width: that path must use the same coordinate mapping.
        ctypes.windll.user32.SetWindowTextW(
            editor._hwnd_edit, "Test-17-0285-longer.inp")
        view._rename_textbox._sync_native_width(editor)
        check_popup()
        print("NATIVE_RENAME_ALIGNMENT_OK", "native_windows=", native.isEnabled(),
              "screen_position=", (round(expected_x), round(expected_y)))
    finally:
        if view is not None:
            view.cancel_inline_rename()
        dpg.destroy_context()


if __name__ == "__main__":
    main()
