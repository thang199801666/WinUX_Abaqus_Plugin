"""Native geometry smoke test plus real thumb drag on an input desktop."""
import ctypes
from ctypes import wintypes
import sys
import time

import pytest

pytestmark = [pytest.mark.windows_native,
              pytest.mark.skipif(sys.platform != "win32", reason="Windows DPG runtime")]


@pytest.fixture
def scroller_window():
    import dearpygui.dearpygui as dpg
    from DearUIQt.qt.scroller import DpgScrollerArrowOverlay
    from WinUx.runtime.dpg_callbacks import run_callback_jobs
    from WinUx.ui.native.native_dialog_host import find_process_window
    dpg.create_context()
    overlay = None
    try:
        dpg.configure_app(manual_callback_management=True)
        with dpg.window(tag="scroller_root", no_scrollbar=True):
            with dpg.child_window(width=-1, height=-1, border=False) as body:
                dpg.add_spacer(width=1000, height=1800)
        overlay = DpgScrollerArrowOverlay(dpg, body, "native_scroller", horizontal=True)
        dpg.create_viewport(title="WinUx scroller interaction", width=520, height=400)
        dpg.set_primary_window("scroller_root", True)
        dpg.setup_dearpygui()
        dpg.show_viewport()

        def pump(count=4):
            for _ in range(count):
                run_callback_jobs(dpg.get_callback_queue() or [])
                overlay.update()
                dpg.render_dearpygui_frame()
                time.sleep(.005)

        pump(8)
        yield dpg, overlay, pump, find_process_window("WinUx scroller interaction")
    finally:
        if overlay is not None:
            overlay.destroy()
        dpg.destroy_context()


def test_real_hit_surfaces_cover_drawn_scroll_gutters(scroller_window):
    dpg, overlay, pump, hwnd = scroller_window
    assert set(overlay._hits) == {"v", "h"}
    assert set(overlay._last_axes) == {"v", "h"}
    children = dpg.get_item_children(overlay.container, 1)
    anchor_index = children.index(dpg.get_alias_id(overlay.anchor))
    for tag in overlay._hits.values():
        assert children.index(dpg.get_alias_id(tag)) < anchor_index
    for axis, tag in overlay._hits.items():
        expected = overlay._last_axes[axis]["hit"]
        x, y = dpg.get_item_rect_min(tag)
        width, height = dpg.get_item_rect_size(tag)
        assert (x, y, x+width, y+height) == pytest.approx(expected, abs=1)


@pytest.mark.parametrize("axis", ["v", "h"])
def test_physical_thumb_drag_changes_native_scroll(scroller_window, axis):
    dpg, overlay, pump, hwnd = scroller_window
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    if not user32.GetForegroundWindow():
        pytest.skip("No foreground/input desktop available for physical drag")
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow(hwnd)
    if int(user32.GetForegroundWindow() or 0) != hwnd:
        pytest.skip("Windows did not grant foreground to the test viewport")
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.DWORD, ctypes.c_size_t]
    old = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(old))

    def move(x, y):
        point = wintypes.POINT(round(x), round(y))
        assert user32.ClientToScreen(hwnd, ctypes.byref(point))
        user32.SetCursorPos(point.x, point.y)
        pump()

    try:
        data = overlay._last_axes[axis]
        center = data["thumb0"] + data["length"] / 2
        if axis == "v":
            move(data["hit"][2] - 4, center)
        else:
            move(center, data["hit"][3] - 4)
        user32.mouse_event(2, 0, 0, 0, 0)
        pump()
        assert overlay._gesture is not None and overlay._gesture["kind"] == "drag"
        if axis == "v":
            move(data["hit"][2] - 4, data["thumb0"] + 100)
            assert dpg.get_y_scroll(overlay.target_item) > 0
        else:
            move(data["thumb0"] + 100, data["hit"][3] - 4)
            assert dpg.get_x_scroll(overlay.target_item) > 0
        user32.mouse_event(4, 0, 0, 0, 0)
        pump()
        assert overlay._gesture is None and not overlay._captured
    finally:
        user32.mouse_event(4, 0, 0, 0, 0)
        user32.SetCursorPos(old.x, old.y)
