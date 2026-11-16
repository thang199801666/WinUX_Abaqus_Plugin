"""Run the actual compact overlay with: abaqus python tests/test_pip_runtime.py."""
import ctypes
import os
import sys
import time
import tempfile
import traceback
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from DearUIQt.backends import dpg
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView
from WinUx.preferences.dialog_geometry import DialogGeometryPreferences


def main():
    view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
    preferences = tempfile.TemporaryDirectory(
        prefix='winux-pip-', dir=Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode')
    view._compact_geometry_preferences = DialogGeometryPreferences(root=preferences.name)
    view._gui_runtime.show()
    for _ in range(3):
        view.update()
    view.collapse_to_job_monitor()
    view._compact_job_monitor.display([
        SimpleNamespace(job_id=str(i), name='Test job {}'.format(i), status='Running',
                        user='test_user', tokens='4', elapsed='00:01')
        for i in range(1, 9)
    ])
    for _ in range(20):
        view.update()
        time.sleep(0.02)
    monitor = view._compact_job_monitor
    print('COMPONENT', monitor.__class__, flush=True)
    print('LAYER', monitor._restore_layer, 'CONTROLS', monitor._control_items, flush=True)
    print('RECT', view._compact_window_rect(), flush=True)
    hwnd = view._find_main_viewport_hwnd()
    x, y, width, height = view._compact_window_rect()
    left, top, right, bottom = view._compact_monitor_work_area(hwnd)
    assert x + width == right and y + height == bottom, 'PiP must fit the work-area corner'
    assert tuple(dpg.get_item_rect_size(view.primary_window_tag)) == (width, height), (
        'PiP content must fill its window without black padding')
    from ctypes import wintypes
    point = wintypes.POINT(180, 90)
    ctypes.windll.user32.ClientToScreen(wintypes.HWND(int(hwnd)), ctypes.byref(point))
    ctypes.windll.user32.SetCursorPos(point.x, point.y)
    def pump(frames=20):
        for _ in range(frames):
            ctypes.windll.user32.SetCursorPos(point.x, point.y)
            view.update()
            time.sleep(0.02)

    pump()
    print('HOVER', monitor._hovered, flush=True)
    assert monitor._restore_layer is not None, 'overlay creation failed'
    assert monitor._hovered, 'native hover polling failed'
    assert len(monitor._control_items) > 12
    assert {'move', 'resize'} <= monitor._control_boxes.keys()
    assert all(dpg.get_item_configuration(i)['show'] for i in monitor._control_items)
    assert dpg.get_viewport_configuration(0)['decorated']  # native PiP borderless, GLFW stays decorated
    body = monitor.listview.body_window
    assert dpg.get_item_configuration(body)['no_scrollbar']
    assert dpg.get_item_configuration(view.primary_window_tag)['no_scrollbar']
    assert not monitor.listview._scroller_arrow_overlay.vertical
    assert dpg.get_item_rect_size(body)[1] == monitor.ROW_HEIGHT * monitor.VISIBLE_ROWS
    assert dpg.get_y_scroll_max(body) > 0, 'Additional rows must be scrollable'
    left = dpg.get_item_rect_min(monitor._control_layers['restore'])
    right = dpg.get_item_rect_min(monitor._control_layers['close'])
    assert right[0] - left[0] >= 200, 'Controls must be in opposite corners'
    screenshot = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode' / 'pip_runtime.png'
    dpg.output_frame_buffer(str(screenshot))
    pump(4)
    print('SCREENSHOT', screenshot, flush=True)
    # Hover controls must not cover the first job's Name cell. This was not
    # covered by the old test, which only clicked a lower row after scrolling.
    bx, by, _, _ = monitor.listview._body_viewport_rect()
    point.x, point.y = int(bx + 180), int(by + 2)
    pump(6)
    ctypes.windll.user32.mouse_event(0x0008, 0, 0, 0, 0)
    pump(1)
    ctypes.windll.user32.mouse_event(0x0010, 0, 0, 0, 0)
    pump(16)
    assert monitor.listview._context_menu_is_visible(), 'Hover drag overlay blocked the first job menu'
    assert view.selected_job_values()[0] == '1'
    monitor.listview._hide_context_menus()
    pump(4)
    for offset_x in (24, width - 24):
        # The old 48px Restore/Close surfaces also covered the first row's
        # Job ID/Status cells, and Restore's native hot zone reached the row.
        point.x, point.y = int(bx + offset_x), int(by + 10)
        pump(6)
        ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
        pump(1)
        ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
        pump(4)
        assert view._compact_job_monitor_active, 'First-row click activated a hover control'
        assert view.selected_job_values()[0] == '1'
        ctypes.windll.user32.mouse_event(0x0008, 0, 0, 0, 0)
        pump(1)
        ctypes.windll.user32.mouse_event(0x0010, 0, 0, 0, 0)
        pump(12)
        assert monitor.listview._context_menu_is_visible(), 'Hover control blocked a job cell menu'
        assert not monitor._hovered, 'PiP hover controls must hide while a menu owns input'
        monitor.listview._hide_context_menus()
        pump(4)
    point.x, point.y = 180, 90
    ctypes.windll.user32.ClientToScreen(wintypes.HWND(int(hwnd)), ctypes.byref(point))
    pump(6)
    ctypes.windll.user32.mouse_event(0x0800, 0, 0, 0xFFFFFF88, 0)
    pump(10)
    assert dpg.get_y_scroll(body) > 0, 'Mouse wheel did not scroll additional jobs'
    ctypes.windll.user32.mouse_event(0x0008, 0, 0, 0, 0)
    pump(1)
    ctypes.windll.user32.mouse_event(0x0010, 0, 0, 0, 0)
    pump(100)
    assert monitor.listview._context_menu_is_visible(), 'PiP right-click menu did not open'
    menu = monitor.listview._item_context_menu
    from DearUIQt.backends.native_windows import NativeWindowBackend
    menu_hwnd = NativeWindowBackend().winId(menu.tag)
    assert menu_hwnd, 'Context menu must have a native window outside PiP'
    menu_rect = wintypes.RECT()
    assert ctypes.windll.user32.GetWindowRect(wintypes.HWND(menu_hwnd), ctypes.byref(menu_rect))
    from DearUIQt.notifications.placement import monitor_work_area
    area = monitor_work_area(point=(point.x, point.y))
    print('MENU RECT', (menu_rect.left, menu_rect.top, menu_rect.right, menu_rect.bottom), flush=True)
    assert area.left <= menu_rect.left and area.top <= menu_rect.top
    assert menu_rect.right <= area.right
    assert menu_rect.bottom <= area.bottom
    assert menu.globalGeometry().width() > 0
    assert menu.globalGeometry().height() > 0
    ctypes.windll.user32.WindowFromPoint.argtypes = [wintypes.POINT]
    ctypes.windll.user32.WindowFromPoint.restype = wintypes.HWND
    point.x, point.y = menu_rect.left + 100, menu_rect.top + 80
    pump(30)
    assert menu.isVisible(), 'Menu disappeared when moving from PiP into it'
    assert ctypes.windll.user32.IsWindowVisible(wintypes.HWND(menu_hwnd))
    dpg.output_frame_buffer(str(screenshot.with_name('pip_context_menu.png')))
    pump(4)
    values = view.selected_job_values()
    assert values and values[2:] == ('test_user', '4', 'Running', '00:01')
    selected_items = monitor.listview.get_selected()
    monitor.callbacks['job_user'] = lambda: 'test_user'
    monitor._context_open(selected_items)
    assert monitor.listview._find_context_menu_action_spec('cancel')['enabled']
    monitor.callbacks['job_user'] = lambda: 'another_user'
    monitor._context_open(selected_items)
    assert not monitor.listview._find_context_menu_action_spec('cancel')['enabled']
    commands = []
    monitor.callbacks['job_command'] = lambda action: commands.append(
        (action, view.selected_job_values()))
    pump(4)
    left, top, right, bottom = menu._pointer_row_rect(menu._rows['details'])
    point.x, point.y = int((left + right) / 2), int((top + bottom) / 2)
    pump(6)
    assert int(ctypes.windll.user32.WindowFromPoint(point) or 0) == menu_hwnd, (
        'PiP or hover controls are covering the context-menu command')
    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
    pump(3)
    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
    pump(6)
    assert commands == [('details', values)], 'Context command selected the wrong job'
    monitor.listview._hide_context_menus()
    pump(4)

    def click_control(action):
        x, y, w, h = monitor._control_boxes[action]
        ox, oy = dpg.get_item_rect_min(monitor._control_layers[action])
        point.x, point.y = int(ox + x + w / 2), int(oy + y + h / 2)
        pump(6)
        assert monitor._control_hit() == action, (action, dpg.get_mouse_pos(local=False))
        ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
        pump(3)
        ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
        pump(6)

    # Move outside: both the visual layer and its hit surface must disappear.
    point.x, point.y = 0, 0
    pump()
    assert not monitor._hovered
    assert all(not dpg.get_item_configuration(c.tag)['show']
               for c in monitor._controls.values())
    point.x, point.y = 180, 90
    ctypes.windll.user32.ClientToScreen(wintypes.HWND(int(hwnd)), ctypes.byref(point))
    pump()
    click_control('restore')
    assert not view._compact_job_monitor_active, 'Restore click did not restore app'
    assert dpg.get_viewport_configuration(0)['decorated']
    view.collapse_to_job_monitor()
    pump()
    point.x, point.y = 180, 90
    ctypes.windll.user32.ClientToScreen(wintypes.HWND(int(hwnd)), ctypes.byref(point))
    pump()
    closed = []
    view._close_callback = lambda: closed.append(True)
    click_control('close')
    assert closed, 'Close click did not reach application close callback'
    print('PASS: PiP context menu, selection, permissions, scrolling, Restore/Close', flush=True)
    view.request_shutdown()
    view._gui_runtime.destroy()
    preferences.cleanup()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
