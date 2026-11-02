"""Repeated physical Delete series: abaqus python tests/test_reference_delete.py."""
import ctypes
import os
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.backends import dpg
from DearUIQt.gui.placement import item_screen_rect
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.dialogs.native_reference_tools import ReferenceChartDialog
from WinUx.services.reference_charts import validate_reference
from WinUx.view import WinUXView


def main():
    user32 = ctypes.windll.user32
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-series-delete-', dir=temp_root) as profile:
        with patch.dict(os.environ, {'APPDATA': profile}):
            view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
            view._gui_runtime.show()
            source = [validate_reference({'name': 'Series {}'.format(i), 'points': [[0, 1], [1, 2]]})
                      for i in range(6)]
            dialog = ReferenceChartDialog(view, source, lambda value: None)

            def pump(frames=8):
                for _ in range(frames):
                    view.update()
                    time.sleep(.02)

            try:
                for session in range(3):
                    dialog.begin_session(source, lambda value: None)
                    dialog.show()
                    pump(24)
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
                    for remaining in range(5, -1, -1):
                        left, top, right, bottom = item_screen_rect(dpg, dialog.delete_series_button)
                        assert user32.SetCursorPos(int((left + right) / 2), int((top + bottom) / 2))
                        pump(3)
                        user32.mouse_event(0x0002, 0, 0, 0, 0)
                        pump(3)
                        user32.mouse_event(0x0004, 0, 0, 0, 0)
                        pump(12)
                        assert len(dialog._series) == remaining, (session, remaining, len(dialog._series))
                    dialog.finish(None)
                    pump()
                print('PASS: 18 physical series deletions across retained reopen sessions', flush=True)
            finally:
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
