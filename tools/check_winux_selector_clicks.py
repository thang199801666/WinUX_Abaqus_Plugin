"""Native selector row clicks through the real WinUx dispatcher/event loop."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import WinUx
from WinUx.controllers import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView
from WinUx.ui import FileSelector
from WinUx.ui.behaviors.plot_docking import PlotDockingMixin
from DearUIQt.core import QEvent, QMouseEvent, Qt


def main():
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.SetFocus.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    old_cursor = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(old_cursor))
    errors = []
    temporary_root = Path.home() / "AppData/Local/Temp/opencode"
    with tempfile.TemporaryDirectory(dir=str(temporary_root)) as directory, \
            patch.object(PlotDockingMixin, "_get_reference_chart_library",
                         lambda self: SimpleNamespace(snapshot=lambda: [], replace=Mock())):
        root = Path(directory)
        for name in ("Alpha", "Beta", "Delta", "Gamma"):
            (root / name).mkdir()
        view = WinUXView({name: Mock(return_value=[]) for name in REQUIRED_CALLBACK_KEYS})
        view._handle_ui_callback_error = lambda callback, info: errors.append(info[1])
        selector = None

        def scenario():
            nonlocal selector
            view._show_plot_digitizer_dialog()
            plot = view._plot_digitizer_dialog
            yield "plot visible", lambda: plot.winId()
            for folder_only in (False, True):
                selector = FileSelector(view=view, initial=directory, directory=folder_only,
                                        accepted=lambda *_: None)
                plot._file_dialog = selector
                selector.open()
                form = selector.dialog
                yield "selector listing", lambda: len(form.listbox.items) == 4 and form.winId()
                yield "rows rendered", lambda: all(
                    view._gui_runtime.backend.get_item_state(tag).get("visible")
                    and view._gui_runtime.backend.get_item_rect_size(tag)[1] > 0
                    for tag in form.listbox.items.values())
                hwnd = form.winId()
                foreground = user32.GetForegroundWindow()
                other = user32.GetWindowThreadProcessId(foreground, None)
                own = ctypes.windll.kernel32.GetCurrentThreadId()
                user32.AttachThreadInput(own, other, True)
                try:
                    user32.BringWindowToTop(wintypes.HWND(hwnd))
                    user32.SetForegroundWindow(wintypes.HWND(hwnd))
                    user32.SetFocus(wintypes.HWND(hwnd))
                finally:
                    user32.AttachThreadInput(own, other, False)
                native_input = int(user32.GetForegroundWindow() or 0) == hwnd
                print("SELECTOR_INPUT_ROUTE", "Win32" if native_input else "QApplication (foreground unavailable)", flush=True)
                for name in ("Beta", "Gamma", "Delta"):
                    key = str(root / name)
                    tag = form.listbox.items[key]
                    x, y = view._gui_runtime.backend.get_item_rect_min(tag)
                    width, height = view._gui_runtime.backend.get_item_rect_size(tag)
                    point = wintypes.POINT(round(x+15), round(y+height/2))
                    global_point = (point.x, point.y)
                    if native_input:
                        user32.SetCursorPos(point.x, point.y)
                    user32.ScreenToClient(wintypes.HWND(hwnd), ctypes.byref(point))
                    packed = (point.y << 16) | (point.x & 0xffff)
                    if native_input:
                        user32.PostMessageW(wintypes.HWND(hwnd), 0x0200, 0, packed)
                    until = time.monotonic()+.08
                    yield "hover " + name, lambda: time.monotonic() >= until
                    if native_input and int(user32.GetForegroundWindow() or 0) != hwnd:
                        native_input = False
                        print("SELECTOR_INPUT_ROUTE QApplication (foreground lost)", flush=True)
                    if native_input:
                        user32.PostMessageW(wintypes.HWND(hwnd), 0x0201, 1, packed)
                    else:
                        view._qapplication.dispatchPointerEvent(QMouseEvent(
                            QEvent.MouseButtonPress, global_point,
                            button=Qt.LeftButton, buttons=Qt.LeftButton))
                    until = time.monotonic()+.18
                    yield "press " + name, lambda: time.monotonic() >= until
                    if native_input:
                        user32.PostMessageW(wintypes.HWND(hwnd), 0x0202, 0, packed)
                    else:
                        view._qapplication.dispatchPointerEvent(QMouseEvent(
                            QEvent.MouseButtonRelease, global_point, button=Qt.LeftButton))
                    until = time.monotonic()+.08
                    yield "release " + name, lambda: time.monotonic() >= until
                    if form.listbox.current != key:
                        from DearUIQt.input_gate import native_background_input_blocked
                        print("CLICK_DIAGNOSTIC", "old_rect", (x,y,width,height), "row_state",
                              view._gui_runtime.backend.get_item_state(tag), "mouse",
                              view._gui_runtime.backend.get_mouse_pos(local=False), "foreground",
                              int(user32.GetForegroundWindow() or 0), "selector_hwnd", hwnd,
                              "gate", native_background_input_blocked(), flush=True)
                    assert form.listbox.current == key, (name, form.listbox.current, form._current_path,
                                                         list(form.listbox.items))
                    assert form._current_path == directory, "One click unexpectedly opened a folder"
                    print("SELECTOR_CLICK_OK", "folder" if folder_only else "file", name, flush=True)
                selector.close()
                selector = None
                plot._file_dialog = None
                until = time.monotonic()+.08
                yield "selector closed", lambda: time.monotonic() >= until

        steps = scenario()
        pending = []

        def advance():
            try:
                if errors:
                    raise errors[0]
                if pending:
                    label, predicate, deadline = pending[0]
                    if not predicate():
                        if time.monotonic() >= deadline and selector is not None:
                            form = selector.dialog
                            print("SELECTOR_DIAGNOSTIC", "visible", form.isVisible(), "hwnd", form.winId(),
                                  "items", len(form.listbox.items), "status", form.control_value(form.status),
                                  "initial", form._initial_location_pending,
                                  "constructing", form.isConstructing(),
                                  "render_queue", list(view._after_render_callbacks), flush=True)
                        assert time.monotonic() < deadline, "Timeout: " + label
                        view.after(10, advance)
                        return
                    pending.clear()
                label, predicate = next(steps)
                pending.append((label, predicate, time.monotonic()+5))
                view.after(10, advance)
            except StopIteration:
                view.request_shutdown()
            except Exception as exc:
                errors.append(exc)
                view.request_shutdown()

        view.after(250, advance)
        try:
            view.run()
        finally:
            user32.SetCursorPos(old_cursor.x, old_cursor.y)
        if errors:
            raise errors[0]
    print("WINUX_NESTED_SELECTOR_CLICKS_OK")


if __name__ == "__main__":
    main()
