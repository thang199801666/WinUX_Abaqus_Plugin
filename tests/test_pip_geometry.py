"""Native PiP drag/resize/persistence: abaqus python tests/test_pip_geometry.py."""
import ctypes
import os
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from DearUIQt.backends import dpg
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.preferences.dialog_geometry import DialogGeometryPreferences
from WinUx.view import WinUXView


def main():
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-pip-geometry-', dir=temp_root) as root:
        view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
        view._compact_geometry_preferences = DialogGeometryPreferences(root=root)
        view._gui_runtime.show()
        user32 = ctypes.windll.user32
        user32.SendMessageW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.SendMessageW.restype = ctypes.c_ssize_t

        def pump(frames=8):
            for _ in range(frames):
                view.update()
                time.sleep(.015)

        def stored():
            # A new preference object proves persistence is on disk, not just
            # an in-memory rectangle retained by this particular view.
            data = DialogGeometryPreferences(root=root).load('CompactJobMonitor')
            assert data
            return tuple(data[key] for key in ('x', 'y', 'width', 'height'))

        def hit(x, y):
            packed = ((int(y) & 0xffff) << 16) | (int(x) & 0xffff)
            return user32.SendMessageW(wintypes.HWND(hwnd), 0x0084, 0, packed)

        def verify_control_alignment(width, height):
            centers = {}
            for action, (x, y, w, h) in monitor._control_boxes.items():
                ox, oy = dpg.get_item_pos(monitor._controls[action].tag)
                centers[action] = (ox + x + w / 2, oy + y + h / 2)
            for action in ('restore', 'move', 'close'):
                assert centers[action][1] == monitor.HEADER_HEIGHT / 2
            assert centers['restore'][0] == width - centers['close'][0]
            assert abs(centers['move'][0] - width / 2) <= .5
            assert centers['resize'][0] == centers['close'][0]
            assert height - centers['resize'][1] == centers['restore'][0]

        def gesture(start, delta):
            user32.SetCursorPos(*map(int, start))
            pump()

            def move_and_release():
                # Windows runs a native move/size loop on the GUI thread.
                # This worker supplies input only; it never accesses DPG/UI.
                try:
                    time.sleep(.15)
                    for step in range(1, 11):
                        user32.SetCursorPos(
                            int(start[0] + delta[0] * step / 10),
                            int(start[1] + delta[1] * step / 10))
                        time.sleep(.035)
                finally:
                    user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP

            worker = threading.Thread(target=move_and_release)
            worker.start()
            user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
            try:
                pump(40)
            finally:
                worker.join(timeout=3)
                user32.mouse_event(0x0004, 0, 0, 0, 0)
            assert not worker.is_alive()
            pump()

        try:
            pump()
            full_rect = view._compact_window_rect()
            view.collapse_to_job_monitor()
            pump(16)
            hwnd = view._find_main_viewport_hwnd()
            initial = view._compact_window_rect()
            x, y, width, height = initial
            monitor = view._compact_job_monitor
            monitor.display([
                SimpleNamespace(job_id=str(i), name='PiP job {}'.format(i),
                                status='Running', user='test_user', tokens='4', elapsed='00:01')
                for i in (1, 2)
            ])
            pump()
            verify_control_alignment(width, height)
            bx, by, _, _ = monitor.listview._body_viewport_rect()
            assert hit(bx + width // 2, by + 2) == 1, 'Drag handle overlaps the first job row'
            assert hit(x + width // 2, y + 20) == 2, 'PiP drag handle is not native HTCAPTION'
            assert hit(x + width - 12, y + height - 12) == 17
            assert hit(x + 2, y + height // 2) == 10
            assert hit(x + 24, y + 24) == 1, 'Restore must remain a clickable client control'
            assert hit(x + 80, y + 65) == 1, 'Job cells must remain interactive'

            gesture((x + width // 2, y + 20), (-240, -180))
            moved = view._compact_window_rect()
            assert moved[:2] == (x - 240, y - 180), ('Native drag failed', initial, moved)
            assert moved[2:] == initial[2:]
            assert stored() == moved, 'Drag was not saved automatically'

            # Open the first row's menu immediately after a real native drag.
            bx, by, _, _ = monitor.listview._body_viewport_rect()
            user32.SetCursorPos(int(bx + moved[2] / 2), int(by + 2))
            pump()
            user32.mouse_event(0x0008, 0, 0, 0, 0)
            pump(1)
            user32.mouse_event(0x0010, 0, 0, 0, 0)
            pump(16)
            assert monitor.listview._context_menu_is_visible(), 'Native drag broke PiP right-click'
            assert view.selected_job_values()[0] == '1'
            assert not monitor._hovered, 'Hover controls are covering the native context menu'
            assert hit(moved[0] + moved[2] // 2, moved[1] + 20) == 1, (
                'PiP drag handle must not steal the context-menu dismissal click')
            monitor.listview._hide_context_menus()
            pump()

            x, y, width, height = moved
            gesture((x + width - 12, y + height - 12), (100, 70))
            resized = view._compact_window_rect()
            assert resized == (x, y, width + 100, height + 70), ('Native resize failed', moved, resized)
            assert stored() == resized, 'Resize was not saved automatically'
            verify_control_alignment(resized[2], resized[3])
            assert tuple(dpg.get_item_rect_size(view.primary_window_tag)) == resized[2:]
            monitor = view._compact_job_monitor
            grip = dpg.get_item_pos(monitor._controls['resize'].tag)
            assert tuple(map(int, grip)) == (
                resized[2] - monitor.RESIZE_GRIP, resized[3] - monitor.RESIZE_GRIP)

            view.restore_from_job_monitor()
            pump(16)
            assert view._compact_window_rect() == full_rect, 'Full-app geometry was overwritten by PiP'
            view._compact_geometry_preferences = DialogGeometryPreferences(root=root)
            view.collapse_to_job_monitor()
            pump(16)
            assert view._compact_window_rect() == resized, 'Reopening PiP lost saved geometry'

            # User resize cannot make the job table/hover controls unusable.
            x, y, width, height = resized
            gesture((x + width - 12, y + height - 12), (-500, -350))
            minimum = view._compact_window_rect()
            assert minimum[2:] == (260, view.COMPACT_JOB_HEIGHT), minimum

            view.restore_from_job_monitor()
            pump(12)
            view._compact_geometry_preferences.save('CompactJobMonitor', {
                'x': -50000, 'y': -50000, 'width': 50000, 'height': 50000})
            view.collapse_to_job_monitor()
            pump(16)
            x, y, width, height = view._compact_window_rect()
            left, top, right, bottom = view._compact_monitor_work_area(hwnd)
            assert left <= x < x + width <= right
            assert top <= y < y + height <= bottom
            print('PASS: PiP native drag, edge/corner resize, minimum size, saved geometry, '
                  'reopen, full-app restore and off-screen recovery', flush=True)
        finally:
            view.request_shutdown()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
