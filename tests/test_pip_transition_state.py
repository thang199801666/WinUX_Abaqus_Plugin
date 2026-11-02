"""Real PiP/Full lifecycle and native-hook tests without moving the mouse."""
import ctypes
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt import input_gate
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView


def main():
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-pip-state-', dir=temp_root) as profile:
        with patch.dict(os.environ, {'APPDATA': profile}):
            view = WinUXView({key: lambda *args, **kwargs: None for key in REQUIRED_CALLBACK_KEYS})

            def pump(count=10):
                for _ in range(count):
                    view.update()
                    time.sleep(.01)

            try:
                view._gui_runtime.show()
                pump(20)
                full_rect = view._compact_window_rect()
                full_styles = view._compact_native_window_styles(view._find_main_viewport_hwnd())
                jobs = [SimpleNamespace(job_id='123', name='Transition test', status='Running',
                                        user='test', tokens='4', elapsed='00:01')]
                view._compact_last_jobs = tuple(jobs)
                full = view._ensure_jobs_view()
                full.display(jobs)
                full.listview.select_indices([0])
                hook = None
                for cycle in range(12):
                    assert full.listview._claim_pointer_gesture()
                    full.listview._mouse_down = True
                    view.collapse_to_job_monitor()
                    pump()
                    monitor = view._compact_job_monitor
                    assert not full.listview._mouse_down
                    assert not full.listview._pointer_input_owned
                    assert input_gate._pointer_owner is None
                    hook = hook or view._compact_restore_mouse_hook
                    assert view._compact_restore_mouse_hook is hook

                    if cycle == 0:
                        restored = []
                        with patch.object(monitor, '_on_restore', lambda: restored.append(True)), \
                                patch.object(monitor, '_control_hit', return_value='restore'):
                            monitor._on_control_click()  # Unmatched release does nothing.
                            assert not restored
                            monitor._on_control_press()
                            assert not restored, 'Mode changed on mouse-down'
                            monitor._on_control_click()
                            monitor._on_control_click()
                            assert restored == [True], 'Restore did not have one press/release activation'

                    assert monitor.listview._claim_pointer_gesture()
                    monitor.listview._mouse_down = True
                    hwnd, old_proc, callback = hook
                    x, y, w, h = monitor._control_boxes['restore']
                    position = (int(y + h / 2) << 16) | int(x + w / 2)
                    # Invoke the real installed WNDPROC, but replace the final
                    # Windows dispatch to prove both down and up are forwarded.
                    with patch.object(ctypes.windll.user32, 'CallWindowProcW', return_value=91) as forward:
                        assert callback(hwnd, 0x0201, 1, position) == 91
                        assert callback(hwnd, 0x0202, 0, position) == 91
                        assert forward.call_count == 2, 'Restore swallowed native mouse-up'
                    pump(15)
                    assert not view._compact_job_monitor_active
                    assert not monitor.listview._mouse_down
                    assert not monitor.listview._pointer_input_owned
                    assert input_gate._pointer_owner is None
                    assert view._compact_restore_mouse_hook is hook
                    assert view._compact_window_rect() == full_rect
                    assert view._compact_native_window_styles(hwnd) == full_styles
                    with patch.object(view, '_refresh_compact_native_frame') as refresh:
                        assert view._restore_compact_native_frame()
                        refresh.assert_not_called()
                    assert full.selected_values()[0] == '123', 'Transition changed selection'
                    # Both directions must permit the next independent gesture.
                    assert full.listview._claim_pointer_gesture()
                    full.listview.cancel_pointer_gesture(suppress_release=False)

                for _ in range(10):
                    view.collapse_to_job_monitor()
                    stale, hover = view._compact_transition_serial, view._compact_hover_serial
                    view.restore_from_job_monitor()
                    view._complete_compact_restore_click(stale)
                    view._finish_job_monitor_transition(stale, True)
                    view._poll_compact_job_monitor_hover(hover)
                pump(20)
                assert not view._compact_hover_polling
                assert not view._compact_job_monitor_active
                assert view._compact_window_rect() == full_rect

                token = object()
                input_gate.acquire_native_modal_input(token)
                try:
                    view._prepare_job_monitor_transition()
                    assert input_gate.native_modal_input_active(), 'Live modal gate was cleared'
                finally:
                    input_gate.release_native_modal_input(token)
                pump()
                print('PASS: 12 native-hook PiP/Full cycles, forwarded mouse-up, canceled captures, '
                      '10 rapid/stale-callback cycles, geometry/styles/selection and modal protection', flush=True)
            finally:
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
