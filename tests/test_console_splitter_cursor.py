"""Cursor regression: abaqus python tests/test_console_splitter_cursor.py."""
import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.gui.placement import item_screen_rect
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView


def main():
    callbacks = {key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS}
    callbacks['console_connected'] = lambda: False
    view = WinUXView(callbacks)
    view._gui_runtime.show()
    u = ctypes.windll.user32
    point = [0, 0]

    def pump(frames=20):
        for _ in range(frames):
            u.SetCursorPos(*point)
            view.update()
            time.sleep(.01)

    pump()
    hwnd = view._find_main_viewport_hwnd()
    u.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(-1), 80, 80, 1000, 700, 0x0040)
    view._console_dock_mode = 'docked'
    view._console_dock_scope = 'outer'
    view._persist_dock_state = lambda: None
    view.set_console_visible(True, persist=False, request_login=False)
    # Both native handles must be cached, as happens after visiting different
    # dividers. Otherwise returning the wrong, not-yet-loaded handle hides the bug.
    view._set_native_windows_cursor(32644, '_native_resize_ew_cursor')
    view._set_native_windows_cursor(32645, '_native_resize_ns_cursor')
    u.GetCursor.restype = wintypes.HANDLE
    u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    for area in ('right', 'left', 'bottom', 'top', 'right'):
        point[:] = [0, 0]
        view._console_dock_area = area
        view._layout_dirty = True
        view._apply_split_layout(force=True)
        pump()
        l, t, r, b = item_screen_rect(view._gui_runtime.backend, view.console_separator_hitbox)
        point[:] = [int((l + r) / 2), int(t + (b - t) * .35)]
        pump()
        expected = (view._native_resize_ew_cursor if area in ('left', 'right')
                    else view._native_resize_ns_cursor)
        assert view._console_splitter_cursor_active, (
            'Console gutter was not hovered', area, point,
            view._gui_runtime.backend.get_mouse_pos(local=False),
            view._gui_runtime.backend.get_item_state(view.console_separator_hitbox))
        for _ in range(30):
            pump(1)
            assert view._splitter_native_cursor_provider() == expected, area
            assert u.GetCursor() == expected, ('post-render cursor', area)
            u.SendMessageW(wintypes.HWND(hwnd), 0x0020, hwnd, 0x02000001)
            assert u.GetCursor() == expected, ('WM_SETCURSOR changed orientation', area)
        print('PASS:', area, 'stable hover and WM_SETCURSOR', flush=True)
    before_width = view._console_dock_width
    u.mouse_event(0x0002, 0, 0, 0, 0)
    pump(4)
    assert view._console_splitter_dragging
    point[0] += 12
    pump(8)
    assert view._console_dock_width != before_width
    assert view._splitter_native_cursor_provider() == view._native_resize_ew_cursor
    u.mouse_event(0x0004, 0, 0, 0, 0)
    pump(6)
    assert not view._console_splitter_dragging
    print('PASS: horizontal drag/release preserves orientation', flush=True)
    view.request_shutdown()
    view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
