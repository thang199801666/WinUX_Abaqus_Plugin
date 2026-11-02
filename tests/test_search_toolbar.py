"""Search field geometry: abaqus python tests/test_search_toolbar.py."""
import os
import sys
import time
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
    def pump(frames=20):
        for _ in range(frames):
            view.update()
            time.sleep(.01)
    pump()
    toolbars = [panel.toolbar for panel in view.panels]
    for toolbar in toolbars:
        toolbar._show_search()
    pump()
    for toolbar in toolbars:
        popup = dpg_window_rect(dpg, toolbar.search_popup)
        shell = dpg_window_rect(dpg, toolbar.search_shell)
        center = (shell[1] + shell[3]) / 2
        print('FIELD', popup, shell, flush=True)
        assert shell[3] - shell[1] == 28
        assert abs(shell[0] - popup[0] - 2) <= 1
        assert abs(popup[2] - shell[2] - 2) <= 2
        first_cell = toolbar._toolbar_grid.cell(0, 0).tag
        first_button = dpg.get_item_children(first_cell, 1)[0]
        nav_x, _nav_y = dpg.get_item_rect_min(first_button)
        end_x, _end_y = dpg.get_item_rect_min(toolbar.search_button.tag)
        end_w, _end_h = dpg.get_item_rect_size(toolbar.search_button.tag)
        assert abs(shell[0] - nav_x) <= 1, 'Search left edge differs from navigation'
        assert abs(shell[2] - (end_x + end_w)) <= 1, 'Search right edge differs from navigation'
        for item in (toolbar.search_icon.tag, toolbar.search_input.tag, toolbar.search_close.tag):
            x, y = dpg.get_item_rect_min(item)
            w, h = dpg.get_item_rect_size(item)
            print('CONTROL', (x, y, w, h), 'CENTER DELTA', y + h / 2 - center, flush=True)
            assert abs(y + h / 2 - center) <= 0.5
    screenshot = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode' / 'search_toolbar.png'
    dpg.output_frame_buffer(str(screenshot))
    pump(4)
    print('SCREENSHOT', screenshot, flush=True)
    for toolbar in toolbars:
        toolbar._hide_search()
    pump()
    assert all(not toolbar.search_visible for toolbar in toolbars)
    view.request_shutdown()
    view._gui_runtime.destroy()
    print('PASS: both search fields, padding, vertical alignment, close', flush=True)


if __name__ == '__main__':
    main()
