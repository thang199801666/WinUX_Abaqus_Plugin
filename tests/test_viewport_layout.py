"""Real viewport geometry regression: abaqus python tests/test_viewport_layout.py."""
import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from DearUIQt.backends import dpg
from DearUIQt.backends.dearpygui import dpg_window_rect
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView


def main():
    view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
    view._gui_runtime.show()

    def pump(frames=30):
        for _ in range(frames):
            view.update()
            time.sleep(.01)

    def inspect(label):
        hwnd = view._find_main_viewport_hwnd()
        rect = wintypes.RECT()
        ctypes.windll.user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect))
        root = dpg_window_rect(dpg, view.layout_root)
        primary = dpg.get_item_state(view.primary_window_tag)['rect_size']
        assert tuple(primary) == (rect.right, rect.bottom), 'Primary window does not fit its client area'
        assert view._last_content_size[0] <= root[2] - root[0], 'Workspace wider than its clipping root'
        assert view._last_content_size[1] <= root[3] - root[1], 'Workspace taller than its clipping root'
        for tag in (view.top_region, view.right_parent, view.bottom_region):
            region = dpg_window_rect(dpg, tag)
            assert region[2] <= root[2] + 1, (label, tag, region, root)
            assert region[3] <= root[3] + 1, (label, tag, region, root)
        print('PASS:', label, 'client', (rect.right, rect.bottom),
              'workspace', view._last_content_size, flush=True)

    pump()
    inspect('initial')
    for width, height in ((1000, 700), (700, 550), (1100, 750)):
        view._gui_runtime.configureViewport(width=width, height=height)
        pump()
        inspect('resize {}'.format(width))
    view.collapse_to_job_monitor()
    pump()
    view.restore_from_job_monitor()
    pump()
    inspect('restored')
    hwnd = view._find_main_viewport_hwnd()
    ctypes.windll.user32.ShowWindow(wintypes.HWND(hwnd), 3)
    pump()
    inspect('maximized')
    ctypes.windll.user32.ShowWindow(wintypes.HWND(hwnd), 9)
    pump()
    inspect('unmaximized')
    view._on_viewport_resize(app_data=None)
    pump()
    inspect('resize callback without size payload')
    view.request_shutdown()
    view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
