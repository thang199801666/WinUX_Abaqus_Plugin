"""Capsule scrollbar regression: abaqus python tests/test_scrollbar_thumb.py."""
import ctypes
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.backends import dpg
from DearUIQt.backends.dearpygui_scroller import DpgScrollerArrowOverlay
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.ui.components.explorer_list_view import ListViewItem
from WinUx.view import WinUXView


def main():
    for vertical in (True, False):
        for thickness in (3, 7):
            rect = (0, 0, thickness, 120) if vertical else (0, 0, 120, thickness)
            middle, centers, radius = DpgScrollerArrowOverlay._capsule_geometry(rect, vertical=vertical)
            assert radius == thickness / 2
            assert centers[0] != centers[1]
    view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
    view._gui_runtime.show()
    point = [0, 0]
    def pump(frames=20):
        for _ in range(frames):
            ctypes.windll.user32.SetCursorPos(*point)
            view.update()
            time.sleep(.01)
    pump()
    hwnd = view._find_main_viewport_hwnd()
    view._gui_runtime.configureViewport(always_on_top=True)
    ctypes.windll.user32.SetWindowPos(
        wintypes.HWND(hwnd), wintypes.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
    ctypes.windll.user32.SetForegroundWindow(wintypes.HWND(hwnd))
    lv = view.left.listview
    lv.set_items([ListViewItem(name='File {}.txt'.format(i), path='C:/test/{}.txt'.format(i),
                              is_dir=False, item_type='File') for i in range(100)])
    lv.auto_width_enabled = False
    lv._column_widths['name'] = 800
    lv._resize_layout_pending = True
    pump()
    overlay = lv._scroller_arrow_overlay
    assert set(overlay._last_axes) == {'v', 'h'}
    for axis in ('v', 'h'):
        key = axis + '_thumb'
        for suffix in ('start', 'end'):
            cfg = dpg.get_item_configuration(overlay._parts[key + '_' + suffix])
            assert cfg['show'] and cfg['radius'] >= 1
        data = overlay._last_axes[axis]
        l, t, r, b = data['hit']
        if axis == 'v':
            point[:] = [int((l + r) / 2), int(data['thumb0'] + data['length'] / 2)]
        else:
            point[:] = [int(data['thumb0'] + data['length'] / 2), int((t + b) / 2)]
        pump()
        assert overlay._expansion[axis] == 1, (
            axis, point, overlay._pointer(), overlay._foreground_input_blocked(), data)
        start = dpg.get_item_configuration(overlay._parts[key + '_start'])
        end = dpg.get_item_configuration(overlay._parts[key + '_end'])
        assert start['radius'] == end['radius'] >= 3
        ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
        pump(3)
        point[1 if axis == 'v' else 0] += 30
        pump(6)
        ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
        pump(6)
        scroll = dpg.get_y_scroll(lv.body_window) if axis == 'v' else dpg.get_x_scroll(lv.body_window)
        assert scroll > 0, 'Thumb dragging did not scroll: ' + axis
        print('PASS:', axis, 'rounded caps, idle/hover/drag, scrolling', flush=True)
    screenshot = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode' / 'scrollbar_thumb.png'
    dpg.output_frame_buffer(str(screenshot))
    pump(4)
    print('SCREENSHOT', screenshot, flush=True)
    overlay.hide()
    assert all(not dpg.get_item_configuration(overlay._parts[k])['show']
               for k in ('v_thumb_start', 'v_thumb_end', 'h_thumb_start', 'h_thumb_end'))
    view.request_shutdown()
    view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
