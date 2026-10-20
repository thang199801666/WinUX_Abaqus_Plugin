"""Check native Enter, focus-loss commit and Escape against temporary files."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import WinUx
from DearUIQt.backends import dpg
from DearUIQt.backends.native_windows import NativeWindowBackend
from WinUx.ui import StandaloneUiHost, configure_ui_context
from WinUx.ui.components.explorer_list_view import ExplorerListView
from WinUx.ui.components.explorer_list_model import ListViewItem


def main():
    user32 = ctypes.windll.user32
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
    user32.SetFocus.argtypes = [wintypes.HWND]
    dpg.create_context()
    dpg.configure_app(manual_callback_management=True)
    view = None
    try:
        NativeWindowBackend(dpg).enable()
        host = StandaloneUiHost(dpg)
        configure_ui_context(host)
        dpg.create_viewport(title="Rename commit check", width=650, height=450)
        with tempfile.TemporaryDirectory(prefix="winux-rename-") as directory:
            original = Path(directory) / "original.txt"
            original.write_text("rename regression", encoding="utf-8")
            with dpg.window(tag="rename_commit_root"):
                view = ExplorerListView("rename_commit_root", width=600, height=350,
                    items=[ListViewItem(original.name, str(original))])
            dpg.setup_dearpygui()
            dpg.show_viewport()

            def frames(count=12):
                for _ in range(count):
                    host.pump()
                    dpg.render_dearpygui_frame()
                    dpg.run_callbacks(dpg.get_callback_queue())

            def edit(value):
                view.select_indices([0])
                assert view.begin_inline_rename(0)
                frames()
                editor = view._rename_textbox._native_editor
                assert editor is not None, "Native editor was not activated"
                user32.SetWindowTextW(editor._hwnd_edit, value)
                return editor

            frames()
            editor = edit("enter.txt")
            user32.SendMessageW(editor._hwnd_edit, 0x0100, 0x0D, 0)
            frames()
            assert (Path(directory) / "enter.txt").exists(), (
                "Enter did not commit", view._rename_active, editor._pending_action)
            assert not view._rename_active
            print("RENAME_ENTER_OK")

            editor = edit("outside.txt")
            user32.SetFocus(view._native_hwnd)
            frames()
            assert (Path(directory) / "outside.txt").exists(), "Focus loss did not commit"
            assert not view._rename_active
            print("RENAME_FOCUS_LOSS_OK")

            editor = edit("cancelled.txt")
            user32.SendMessageW(editor._hwnd_edit, 0x0100, 0x1B, 0)
            user32.SetFocus(view._native_hwnd)
            frames()
            assert not (Path(directory) / "cancelled.txt").exists()
            assert (Path(directory) / "outside.txt").exists()
            assert not view._rename_active
            print("RENAME_ESCAPE_OK")
    finally:
        if view is not None:
            view.cancel_inline_rename()
        dpg.destroy_context()


if __name__ == "__main__":
    main()
