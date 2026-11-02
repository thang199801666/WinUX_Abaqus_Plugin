"""Physical dialog drag policy: abaqus python tests/test_dialog_caption_drag.py.

Run alone; do not move the mouse during the test.
"""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from DearUIQt.backends import dpg
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.dialogs.native_reference_tools import ReferenceChartDialog, PlotDigitizerDialog
from WinUx.ui.native.native_dock_gesture import _native_caption_band
from WinUx.view import WinUXView


def main():
    user32 = ctypes.windll.user32
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-caption-drag-', dir=temp_root) as profile:
        with patch.dict(os.environ, {'APPDATA': profile}):
            view = WinUXView({key: lambda *a, **kw: None for key in REQUIRED_CALLBACK_KEYS})
            view._gui_runtime.show()

            def pump(frames=8):
                for _ in range(frames):
                    view.update()
                    time.sleep(.015)

            def rectangle(hwnd):
                rect = wintypes.RECT()
                user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
                return rect.left, rect.top, rect.right, rect.bottom

            def drag(start, dx=70, dy=45):
                user32.SetCursorPos(*map(int, start))
                pump(3)
                done = threading.Event()

                def move_pointer():
                    # USER32's caption drag owns a modal move loop on the UI
                    # thread. Deliver movement/release independently so a
                    # blocked render turn cannot leave the button held down.
                    user32.mouse_event(0x0002, 0, 0, 0, 0)
                    try:
                        time.sleep(.12)
                        for step in range(1, 13):
                            user32.SetCursorPos(int(start[0] + dx * step / 12),
                                                int(start[1] + dy * step / 12))
                            time.sleep(.04)
                    finally:
                        user32.mouse_event(0x0004, 0, 0, 0, 0)
                        done.set()

                worker = threading.Thread(target=move_pointer, daemon=True)
                worker.start()
                while not done.is_set():
                    pump(1)
                worker.join()
                pump()

            try:
                for factory in (
                        lambda: ReferenceChartDialog(view, [], lambda result: None),
                        lambda: PlotDigitizerDialog(view)):
                    dialog = factory()
                    dialog.show()
                    pump(25)
                    hwnd = dialog._native_window_backend.winId(dialog.tag)
                    user32.GetForegroundWindow.restype = wintypes.HWND
                    thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
                    current = ctypes.windll.kernel32.GetCurrentThreadId()
                    attached = user32.AttachThreadInput(current, thread, True)
                    try:
                        user32.SetForegroundWindow(wintypes.HWND(hwnd))
                    finally:
                        if attached:
                            user32.AttachThreadInput(current, thread, False)
                    assert int(user32.GetForegroundWindow() or 0) == hwnd
                    assert dpg.get_item_configuration(dialog.tag)['no_move']
                    before = rectangle(hwnd)
                    # Blank footer space previously let ImGui drag the whole
                    # native viewport, stealing gestures from client content.
                    rect = dialog._content_widget.globalGeometry()
                    drag((rect.x() + 12, rect.y() + 12))
                    assert rectangle(hwnd) == before, ('Client drag moved dialog', before, rectangle(hwnd))
                    client = wintypes.RECT()
                    origin = wintypes.POINT()
                    user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(client))
                    user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(origin))
                    drag((origin.x + 15, origin.y + client.bottom - 18))
                    assert rectangle(hwnd) == before, ('Footer drag moved dialog', before, rectangle(hwnd))
                    top, bottom = _native_caption_band(hwnd)
                    drag(((before[0] + before[2]) // 2, before[1] + (top + bottom) // 2))
                    assert rectangle(hwnd)[:2] != before[:2], ('Caption drag was disabled', before, rectangle(hwnd))
                    dialog.reject()
                    pump()
                print('PASS: Chart and Plot Digitizer ignore client/footer window drags; native captions still move both dialogs')
            finally:
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
