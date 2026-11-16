"""Rendered file-list compact/restore input; --pointer uses the physical mouse."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile
import time
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.backends import dpg, get_backend
from DearUIQt.core import QEvent, QMouseEvent, QPoint, Qt
from DearUIQt.core.application import QApplication
from DearUIQt.gui import QCursor
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.models.items import FileItem
from WinUx.view import WinUXView


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='file-list-compact-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
        application = QApplication.instance()
        physical = '--pointer' in sys.argv
        user32 = ctypes.windll.user32
        original_cursor = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(original_cursor))
        deliveries = []
        for panel in view.panels:
            listing = panel.listview
            handler = listing._qt_input_target.pointerHandler()
            def dispatch(event, listing=listing, handler=handler):
                result = handler(event)
                if event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
                    deliveries.append((listing.uid, event.type(), listing._row_at_mouse(),
                        listing._mouse_down, listing._pending_click_index, listing._header_gesture,
                        listing._suppress_next_left_release, listing._rename_active))
                return result
            listing._qt_input_target.setPointerHandler(dispatch)

        def pump(count=8):
            for _ in range(count):
                view.update()
                time.sleep(.01)

        def click(listing, row, modifiers=Qt.NoModifier):
            # Use the submitted drawlist's row origin, independently of the
            # viewport/hit-test calculation being checked.
            canvas = listing.pinned_canvas if row is None else listing.body_canvas
            x, y = dpg.get_item_rect_min(canvas)
            point = (x + 80, y + (0 if row is None else row) * listing.ROW_HEIGHT + listing.ROW_HEIGHT / 2)
            deliveries.clear()
            if physical:
                user32.SetCursorPos(*map(int, point))
                pump(2)
                cursor = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(cursor))
                assert (cursor.x, cursor.y) == tuple(map(int, point)), 'External mouse interference'
                user32.mouse_event(0x0002, 0, 0, 0, 0)
                pump(2)
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                pump(10)
                return
            with patch.object(QCursor, 'pos', return_value=QPoint(*map(int, point))), \
                    patch.object(get_backend(), 'get_mouse_pos', return_value=point):
                target = application._pointer_target_at(point)
                assert target is listing._qt_input_target, (
                    listing.uid, row, point, target, listing._body_viewport_rect())
                for event_type, buttons in ((QEvent.MouseButtonPress, Qt.LeftButton),
                                            (QEvent.MouseButtonRelease, Qt.NoButton)):
                    application.dispatchPointerEvent(QMouseEvent(
                        event_type, point, button=Qt.LeftButton,
                        buttons=buttons, modifiers=modifiers))
            pump(3)

        def check_files():
            if physical:
                user32.SetWindowPos(wintypes.HWND(view._find_main_viewport_hwnd()),
                                    wintypes.HWND(-1), 0, 0, 0, 0, 0x0013)
                pump(3)
            for panel in view.panels:
                listing = panel.listview
                for row in (0, 1, 5, 1, 0):
                    click(listing, row)
                    assert listing.selected == {row}, (panel.panel_id, row, listing.selected,
                        listing._body_viewport_rect(), dpg.get_item_rect_min(listing.body_canvas),
                        dpg.get_mouse_pos(local=False), listing._body_local_pos(), listing._row_at_mouse(),
                        application.hoverPointerObject(), application.focusWidget(),
                        int(user32.GetForegroundWindow() or 0), view._find_main_viewport_hwnd(), deliveries)
                    pump()
                    assert listing.selected == {row}, 'File selection changed without input'
                if not physical:
                    click(listing, 1, Qt.ControlModifier)
                    assert listing.selected == {0, 1}, (panel.panel_id, listing.selected)
                    click(listing, 5, Qt.ShiftModifier)
                    assert listing.selected == set(range(1, 6)), (panel.panel_id, listing.selected)
                    check_parent(panel)

        def check_parent(panel):
            listing = panel.listview
            assert listing._pinned_item.name == '..'
            requested = Mock()
            original = panel.callbacks['double_click']
            panel.callbacks['double_click'] = requested
            other = view.right if panel is view.left else view.left
            other_selected = set(other.listview.selected)
            try:
                listing._pinned_last_click_time = 0.0
                click(listing, None)
                assert not listing.selected, 'Parent click left a file selected'
                requested.assert_not_called()
                click(listing, 0)
                assert listing.selected == {0}, 'Parent hover stole the first file click'
                click(listing, None)
                requested.assert_not_called()  # A file click broke the pair.
                click(listing, None)
                requested.assert_called_once_with(panel, listing._pinned_item)
                assert requested.call_args.args[1].data['path'] == panel.current_path.parent
                assert other.listview.selected == other_selected, 'Parent click affected the other pane'
                assert listing._pinned_last_click_time == 0.0
                # A canceled gesture / mode transition must also break the pair.
                click(listing, None)
                listing.cancel_pointer_gesture()
                click(listing, None)
                assert requested.call_count == 1, 'Canceled parent click paired with a later click'
                click(listing, 1)
                assert listing.selected == {1}, 'Parent activation blocked the second file'
            finally:
                panel.callbacks['double_click'] = original

        try:
            view._gui_runtime.show()
            for panel in view.panels:
                folder = PurePosixPath('/test') if panel.panel_id == 'server' else Path(profile)
                panel.display(folder, [FileItem('file_%02d.inp' % i,
                    folder / ('file_%02d.inp' % i), False, i + 10, 100) for i in range(12)])
            pump(25)
            if physical:
                user32.GetForegroundWindow.restype = wintypes.HWND
                thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
                current = ctypes.windll.kernel32.GetCurrentThreadId()
                attached = user32.AttachThreadInput(current, thread, True)
                try:
                    user32.SetForegroundWindow(wintypes.HWND(view._find_main_viewport_hwnd()))
                finally:
                    if attached:
                        user32.AttachThreadInput(current, thread, False)
            check_files()
            for _ in range(1 if physical else 3):
                view.collapse_to_job_monitor()
                pump(12)
                view.restore_from_job_monitor()
                pump(20)
                check_files()
            print('PASS: Local/Server file lists, first two rows, alternating clicks, compact/restore; '
                  + ('physical mouse' if physical else 'routed events, Ctrl/Shift and parent-row click/double-click isolation'), flush=True)
        finally:
            if physical:
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                user32.SetCursorPos(original_cursor.x, original_cursor.y)
            view.request_shutdown()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
