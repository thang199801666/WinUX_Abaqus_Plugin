"""Exercise selection in a native selector nested under Plot Digitizer."""
from pathlib import Path
import sys
import tempfile
import time
import ctypes
from ctypes import wintypes

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import WinUx
from DearUIQt.backends import dpg
from DearUIQt.backends.native_windows import NativeWindowBackend
from DearUIQt.core.application import QApplication
from WinUx.ui import StandaloneUiHost, configure_ui_context, FileSelector
from WinUx.view import WinUXView
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
from WinUx.runtime.dpg_callbacks import run_callback_jobs


def main():
    dpg.create_context()
    app = None
    parent = None
    selector = None
    try:
        native = NativeWindowBackend(dpg)
        native.enable()
        host = StandaloneUiHost(dpg)
        configure_ui_context(host)
        host.is_standalone_ui_host = False
        app = QApplication(after=host.after)
        host._qapplication = app
        app.installInputBackend(dpg)
        dpg.create_viewport(title="WinUX selector check", width=1100, height=800)
        with dpg.window(tag="selector_check_main"):
            dpg.add_text("Selector check parent")
        dpg.set_primary_window("selector_check_main", True)
        host.primary_window_tag = "selector_check_main"
        host._find_main_viewport_hwnd = lambda: WinUXView._find_main_viewport_hwnd(host)
        dpg.setup_dearpygui()
        dpg.show_viewport()

        def pump(count=8):
            for _ in range(count):
                run_callback_jobs(dpg.get_callback_queue() or [])
                host.pump()
                dpg.render_dearpygui_frame()
                time.sleep(.005)

        pump()
        parent = PlotDigitizerDialog(host)
        pump()
        temporary_root = Path.home() / "AppData/Local/Temp/opencode"
        with tempfile.TemporaryDirectory(dir=str(temporary_root)) as directory:
            root = Path(directory)
            for name in ("Alpha", "Beta", "Delta", "Gamma"):
                (root / name).mkdir()
            for is_directory in (False, True):
                selector = FileSelector(view=host, initial=directory, directory=is_directory,
                                        accepted=lambda *_: None)
                selector.open()
                form = selector.dialog
                deadline = time.monotonic() + 5
                while len(form.listbox.items) < 4:
                    assert time.monotonic() < deadline, "Selector listing timed out"
                    pump(1)
                pump()
                form.listbox.currentChanged.connect(lambda key: print("CURRENT", Path(key).name if key else None))
                for name in ("Beta", "Gamma", "Delta"):
                    key = str(root / name)
                    row = form.listbox.items[key]
                    x, y = dpg.get_item_rect_min(row)
                    width, height = dpg.get_item_rect_size(row)
                    print("CLICK", name, "rect=", (x, y, width, height))
                    assert form.listbox._row_pointer_clicked(point=(x + 5, y + height / 2))
                    assert form.listbox.current == key, form.listbox.current
                    pump()
                    assert form.listbox.current == key, ("Selection reset after click", name, form.listbox.current)
                if "--messages" in sys.argv:
                    user32 = ctypes.windll.user32
                    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
                    user32.SetFocus.argtypes = [wintypes.HWND]
                    user32.SetActiveWindow.argtypes = [wintypes.HWND]
                    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
                    user32.GetForegroundWindow.restype = wintypes.HWND
                    user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
                    old = wintypes.POINT()
                    user32.GetCursorPos(ctypes.byref(old))
                    hwnd = native.winId(form.tag)
                    if "--foreground" in sys.argv:
                        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
                        foreground = user32.GetForegroundWindow()
                        other_thread = user32.GetWindowThreadProcessId(foreground, None)
                        own_thread = ctypes.windll.kernel32.GetCurrentThreadId()
                        user32.AttachThreadInput(own_thread, other_thread, True)
                        try:
                            user32.BringWindowToTop(wintypes.HWND(hwnd))
                            user32.SetForegroundWindow(wintypes.HWND(hwnd))
                            user32.SetFocus(wintypes.HWND(hwnd))
                        finally:
                            user32.AttachThreadInput(own_thread, other_thread, False)
                    try:
                        for name in ("Beta", "Gamma", "Delta"):
                            key = str(root / name)
                            row = form.listbox.items[key]
                            x, y = dpg.get_item_rect_min(row)
                            size = dpg.get_item_rect_size(row)
                            point = wintypes.POINT(round(x + 12), round(y + size[1] / 2))
                            user32.SetActiveWindow(wintypes.HWND(hwnd))
                            user32.SetForegroundWindow(wintypes.HWND(hwnd))
                            user32.SetFocus(wintypes.HWND(hwnd))
                            user32.SetCursorPos(point.x, point.y)
                            user32.ScreenToClient(wintypes.HWND(hwnd), ctypes.byref(point))
                            packed = (point.y << 16) | (point.x & 0xffff)
                            user32.PostMessageW(wintypes.HWND(hwnd), 0x0200, 0, packed)
                            pump()
                            user32.PostMessageW(wintypes.HWND(hwnd), 0x0201, 1, packed)
                            pump(3)
                            user32.PostMessageW(wintypes.HWND(hwnd), 0x0202, 0, packed)
                            pump()
                            print("NATIVE_CLICK", name, "selected", form.listbox.current,
                                  "foreground", int(user32.GetForegroundWindow() or 0), "hwnd", hwnd,
                                  "mouse", dpg.get_mouse_pos(local=False))
                            assert form.listbox.current == key, (name, form.listbox.current)
                    finally:
                        user32.SetCursorPos(old.x, old.y)
                selector.close()
                selector = None
                pump()
        print("NATIVE_SELECTOR_SELECTION_OK")
    finally:
        if selector is not None:
            selector.close()
        if parent is not None:
            parent.destroy()
        if app is not None:
            app.delete()
        dpg.destroy_context()


if __name__ == "__main__":
    main()
