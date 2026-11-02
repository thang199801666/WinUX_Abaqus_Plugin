"""Real PiP/Full input regression. Moves the physical mouse; run alone."""
import ctypes
import os
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.backends import dpg
from DearUIQt import input_gate
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView


def main():
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-pip-input-', dir=temp_root) as profile:
        with patch.dict(os.environ, {'APPDATA': profile}):
            view = WinUXView({key: lambda *args, **kwargs: None for key in REQUIRED_CALLBACK_KEYS})
            user32 = ctypes.windll.user32
            original_cursor = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(original_cursor))
            target = None

            def pump(count=8):
                for _ in range(count):
                    view.update()
                    time.sleep(.015)

            def move(x, y):
                nonlocal target
                target = (int(x), int(y))
                assert user32.SetCursorPos(*target), 'Desktop mouse unavailable'
                pump(8)

            def click(x, y):
                move(x, y)
                point = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(point))
                assert (point.x, point.y) == target, (
                    'Mouse interference or inaccessible desktop: test not valid',
                    target, (point.x, point.y), view._compact_window_rect())
                user32.mouse_event(0x0002, 0, 0, 0, 0)
                pump(3)
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                pump(10)

            def click_row(listview, row):
                x, y, width, _ = listview._body_viewport_rect()
                click(x + min(width * .45, 190), y + row * listview.ROW_HEIGHT + 10)

            try:
                view._gui_runtime.show()
                pump(15)
                jobs = [SimpleNamespace(job_id=str(i), name='Input check {}'.format(i),
                                        status='Running', user='test', tokens='4', elapsed='00:01')
                        for i in range(1, 4)]
                view._compact_last_jobs = tuple(jobs)
                full = view._ensure_jobs_view()
                full.display(jobs)
                pump()
                original_rect = view._compact_window_rect()
                hook = None
                for cycle in range(6):
                    # A workspace list may still hold a canceled selection/drag
                    # when the application switches modes programmatically.
                    full.listview._claim_pointer_gesture()
                    full.listview._mouse_down = True
                    view.collapse_to_job_monitor()
                    pump(12)
                    monitor = view._compact_job_monitor
                    assert not full.listview._pointer_input_owned
                    hook = hook or view._compact_restore_mouse_hook
                    assert view._compact_restore_mouse_hook is hook
                    click_row(monitor.listview, cycle % 3)
                    assert view.selected_job_values()[0] == str(cycle % 3 + 1), (
                        'PiP selection blocked', cycle, view.selected_job_values(),
                        'owner', input_gate._pointer_owner, 'popup', input_gate._popup_input_owners,
                        'native modal', input_gate.native_modal_input_active(),
                        'down', monitor.listview._mouse_down, 'owned', monitor.listview._pointer_input_owned,
                        'rect', monitor.listview._body_viewport_rect(),
                        'mouse', dpg.get_mouse_pos(local=False))
                    # Native first-click Restore must not swallow GLFW's up-event.
                    x, y, w, h = monitor._control_boxes['restore']
                    ox, oy = dpg.get_item_rect_min(monitor._control_layers['restore'])
                    click(ox + x + w / 2, oy + y + h / 2)
                    assert not view._compact_job_monitor_active, 'Restore did not activate'
                    assert not dpg.is_mouse_button_down(dpg.mvMouseButton_Left), 'Renderer lost button-up'
                    assert not monitor.listview._pointer_input_owned, 'Hidden PiP retained capture'
                    assert view._compact_restore_mouse_hook is hook, 'WNDPROC hook was rebuilt'
                    row = (cycle + 1) % 3
                    click_row(full.listview, row)
                    assert view.selected_job_values()[0] == str(row + 1), 'Full-mode click blocked after restore'
                    assert view._compact_window_rect() == original_rect, 'Full geometry drifted'

                # Delayed callbacks from older generations must not alter a
                # newer mode, restore its frame, or spawn another hover poller.
                for _ in range(10):
                    view.collapse_to_job_monitor()
                    stale = view._compact_transition_serial
                    hover = view._compact_hover_serial
                    view.restore_from_job_monitor()
                    view._complete_compact_restore_click(stale)
                    view._finish_job_monitor_transition(stale, True)
                    view._poll_compact_job_monitor_hover(hover)
                pump(20)
                assert not view._compact_job_monitor_active
                assert not view._compact_hover_polling
                assert view._compact_window_rect() == original_rect
                click_row(full.listview, 0)
                assert view.selected_job_values()[0] == '1'

                token = object()
                input_gate.acquire_native_modal_input(token)
                try:
                    view._prepare_job_monitor_transition()
                    assert input_gate.native_modal_input_active(), 'Transition cleared a live modal gate'
                finally:
                    input_gate.release_native_modal_input(token)
                pump()
                print('PASS: 6 physical PiP/Full restore/selection cycles, 10 rapid cycles, '
                      'stable native hook, mouse-up delivery and preserved modal gate', flush=True)
            finally:
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                user32.SetCursorPos(original_cursor.x, original_cursor.y)
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
