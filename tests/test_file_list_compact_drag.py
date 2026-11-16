"""Rubber-band and cross-panel drags before/after compact mode; no SSH I/O."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.backends import dpg, get_backend
from DearUIQt.core import QEvent, QMouseEvent, QPoint, Qt
from DearUIQt.core.application import QApplication
from DearUIQt.gui import QCursor
from DearUIQt import input_gate
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.models.items import FileItem
from WinUx.view import WinUXView


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    physical = '--pointer' in sys.argv
    user32 = ctypes.windll.user32
    original = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(original))
    with tempfile.TemporaryDirectory(dir=temp) as profile, patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
        app = QApplication.instance()
        pointer_state = {'lagging_buttons': False}
        captures = []
        def pump(count=6):
            for _ in range(count):
                view.update()
                time.sleep(.01)
        def event(kind, point):
            buttons = Qt.NoButton if kind == QEvent.MouseButtonRelease else Qt.LeftButton
            if kind == QEvent.MouseMove and pointer_state['lagging_buttons']:
                # A stale renderer button mask must not erase the accepted
                # left-button gesture which QApplication still captures.
                buttons = Qt.RightButton
            button = Qt.NoButton if kind == QEvent.MouseMove else Qt.LeftButton
            if physical:
                user32.SetCursorPos(*map(int, point))
                pump(2)
                actual = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(actual))
                assert (actual.x, actual.y) == tuple(map(int, point)), 'External mouse interference; physical test is not valid'
                if kind == QEvent.MouseButtonPress:
                    user32.mouse_event(0x0002, 0, 0, 0, 0)
                elif kind == QEvent.MouseButtonRelease:
                    user32.mouse_event(0x0004, 0, 0, 0, 0)
                pump(4)
            else:
                with patch.object(QCursor, 'pos', return_value=QPoint(*map(int, point))), \
                        patch.object(QCursor, 'viewportPos', return_value=point), \
                        patch.object(get_backend(), 'get_mouse_pos', return_value=point):
                    app.dispatchPointerEvent(QMouseEvent(kind, point, button=button, buttons=buttons))
        def diagnose(lv):
            return (lv.uid, lv._mouse_down, lv._rubber_active, lv._item_drag_active,
                    lv._pointer_input_owned, input_gate._pointer_owner,
                    app.mouseGrabberObject(), lv._header_gesture,
                    lv._body_viewport_rect(), lv._suppress_next_left_release)
        def verify_painted_overlay(name, point, color):
            if not physical:
                return
            from PIL import Image
            screenshot = temp / ('file_list_%s_%d.png' % (name, len(captures)))
            captures.append(screenshot)
            dpg.output_frame_buffer(str(screenshot))
            pump(5)
            origin = wintypes.POINT()
            client = wintypes.RECT()
            hwnd = wintypes.HWND(view._find_main_viewport_hwnd())
            user32.ClientToScreen(hwnd, ctypes.byref(origin))
            user32.GetClientRect(hwnd, ctypes.byref(client))
            with Image.open(screenshot) as image:
                x = round((point[0] - origin.x) * image.width / max(1, client.right))
                y = round((point[1] - origin.y) * image.height / max(1, client.bottom))
                pixels = [image.getpixel((px, py))[:3]
                          for px in range(max(0, x - 1), min(image.width, x + 2))
                          for py in range(max(0, y - 1), min(image.height, y + 2))]
                assert any(max(abs(a - b) for a, b in zip(pixel, color[:3])) <= 30
                           for pixel in pixels), (name, point, (x, y), pixels, screenshot)
            if '--screenshot' in sys.argv:
                print('FRAMEBUFFER', screenshot, flush=True)
        def check(activate=False, lagging_buttons=False):
            pointer_state['lagging_buttons'] = lagging_buttons
            if physical and activate:
                hwnd = view._find_main_viewport_hwnd()
                user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(-1), 0, 0, 0, 0, 0x0013)
                user32.GetForegroundWindow.restype = wintypes.HWND
                thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
                current = ctypes.windll.kernel32.GetCurrentThreadId()
                attached = user32.AttachThreadInput(current, thread, True)
                try:
                    user32.SetForegroundWindow(wintypes.HWND(hwnd))
                finally:
                    if attached:
                        user32.AttachThreadInput(current, thread, False)
                pump(3)
            for panel, target in ((view.left, view.right), (view.right, view.left)):
                lv = panel.listview
                lv._last_click_time = 0
                x, y = dpg.get_item_rect_min(lv.body_canvas)
                right = lv._body_viewport_rect()[2]
                start = (right - 35, y + lv.ROW_HEIGHT / 2)
                finish = (x + 2, y + 3.5 * lv.ROW_HEIGHT)
                event(QEvent.MouseButtonPress, start)
                event(QEvent.MouseMove, finish)
                assert lv._rubber_active, ('rubber-band did not start', diagnose(lv))
                view._drain_queue()
                rectangle = dpg.get_item_configuration(lv._rubber_rect_tag)
                if getattr(lv, '_primary_pointer_overlays', False):
                    assert dpg.get_item_configuration(lv._rubber_layer_tag)['primary_viewport']
                assert rectangle['show'], 'Rubber-band state was active but its primitive stayed hidden'
                assert rectangle['pmax'][0] - rectangle['pmin'][0] > 20
                assert rectangle['pmax'][1] - rectangle['pmin'][1] > 20
                verify_painted_overlay('rubberband',
                    ((rectangle['pmin'][0] + rectangle['pmax'][0]) / 2, rectangle['pmin'][1]),
                    lv.theme_config['rubber_border'])
                event(QEvent.MouseButtonRelease, finish)
                assert not lv._rubber_active and lv.selected == set(range(4)), (lv.selected, diagnose(lv))
                lv.clear_selection()
                lv._last_click_time = 0
                dropped = Mock()
                old_drop = lv.on_drop
                lv.on_drop = dropped
                try:
                    start = (x + 12, y + lv.ROW_HEIGHT / 2)
                    event(QEvent.MouseButtonPress, start)
                    event(QEvent.MouseMove, (start[0] + 45, start[1] + 3))
                    assert lv._item_drag_active, ('file drag did not start', diagnose(lv))
                    assert lv._drag_preview._group.isVisible(), 'File drag preview remained hidden'
                    if getattr(lv, '_primary_pointer_overlays', False):
                        assert dpg.get_item_configuration(lv._drag_preview._canvas.tag)['primary_viewport']
                    translation = lv._drag_preview._group._translation
                    verify_painted_overlay('drag_preview',
                        (translation[0] + 9, translation[1] + 15),
                        lv._drag_preview.theme_config.get('drag_accent', (0, 120, 215, 255)))
                    tx, ty = dpg.get_item_rect_min(target.listview.body_canvas)
                    finish = (tx + 80, ty + target.listview.ROW_HEIGHT / 2)
                    event(QEvent.MouseMove, finish)
                    event(QEvent.MouseButtonRelease, finish)
                    dropped.assert_called_once()
                    assert [item.name for item in dropped.call_args.args[3]] == ['file_00.inp']
                    assert not lv._item_drag_active and not lv._pointer_input_owned
                finally:
                    lv.on_drop = old_drop
            pump()
        try:
            view._gui_runtime.show()
            for panel in view.panels:
                folder = PurePosixPath('/test') if panel.panel_id == 'server' else Path(profile)
                panel.display(folder, [FileItem('file_%02d.inp' % i,
                    folder / ('file_%02d.inp' % i), False, 10, 100) for i in range(8)])
            pump(25)
            check(activate=True)
            view.display_jobs([SimpleNamespace(job_id=str(i), name='Job %02d' % i,
                               status='Running', user='test', tokens='4', elapsed='00:01')
                               for i in range(30)])
            pump()
            for _ in range(3):
                other = view.right.listview._qt_input_target
                app.setMouseGrabberObject(other)
                view.left.listview.cancel_pointer_gesture()
                assert app.mouseGrabberObject() is other, 'Cancellation released another view capture'
                view.right.listview.cancel_pointer_gesture()
                assert app.mouseGrabberObject() is None
                # A mode change can arrive while a Qt-routed mouse gesture is
                # still captured (for example while restoring via native UI).
                listing = view.left.listview
                listing._claim_pointer_gesture()
                listing._mouse_down = True
                app.setMouseGrabberObject(listing._qt_input_target)
                app._implicit_grab_buttons = Qt.LeftButton
                view.collapse_to_job_monitor()
                assert app.mouseGrabberObject() is None, 'Full workspace retained Qt mouse capture in compact mode'
                pump(12)
                compact_list = view._compact_job_monitor.listview
                compact_list._claim_pointer_gesture()
                compact_list._mouse_down = True
                app.setMouseGrabberObject(compact_list._qt_input_target)
                app._implicit_grab_buttons = Qt.LeftButton
                if physical:
                    monitor = view._compact_job_monitor
                    wx, wy, ww, wh = view._compact_window_rect()
                    user32.SetCursorPos(int(wx + ww / 2), int(wy + wh / 2))
                    pump(12)
                    x, y, width, height = monitor._control_boxes['restore']
                    ox, oy = dpg.get_item_rect_min(monitor._control_layers['restore'])
                    point = (ox + x + width / 2, oy + y + height / 2)
                    event(QEvent.MouseButtonPress, point)
                    event(QEvent.MouseButtonRelease, point)
                    assert not view._compact_job_monitor_active, 'Native Restore did not activate'
                else:
                    view.restore_from_job_monitor()
                assert app.mouseGrabberObject() is None, 'Compact list retained Qt mouse capture after restore'
                pump(20)
                check()
                if not physical:
                    check(lagging_buttons=True)
            print('PASS: Local/Server rubber-band and cross-pane drag/drop across three compact/restore cycles')
        finally:
            if physical:
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                user32.SetCursorPos(original.x, original.y)
            view.request_shutdown()
            view._destroy_components()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
