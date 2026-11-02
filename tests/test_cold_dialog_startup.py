"""Cold modal regression: abaqus python tests/test_cold_dialog_startup.py [frames]."""
import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from DearUIQt.backends.native_presentation import presentation_for
from DearUIQt.backends.native_windows import NativeWindowBackend
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView


def main():
    startup_frames = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
    view._gui_runtime.show()
    native = NativeWindowBackend()
    user32 = ctypes.windll.user32
    owner = wintypes.HWND(view._find_main_viewport_hwnd())
    presentation = presentation_for(view._gui_runtime.backend, create=True)
    assert presentation is not None

    def pump(frames=1):
        for _ in range(frames):
            view.update()
            assert user32.IsWindowVisible(owner), 'Cold modal hid the main window'
            assert not user32.IsIconic(owner), 'Cold modal minimized the main window'
            time.sleep(.01)

    def show_and_verify(title):
        dialog = view.show_message(title, 'Job 123: Running')
        original_cloak = presentation._cloak
        exposure = []

        def record_cloak(hwnd, enabled):
            if not enabled and int(hwnd) == native._rawWinId(dialog.tag):
                # The old implementation disabled WinUx on frame zero while
                # its only dialog was still cloaked. At the first reveal the
                # owner must still be enabled; disable happens next render,
                # after the modal has a visible native activation target.
                assert user32.IsWindowEnabled(owner), (
                    'Owner disabled before cold dialog was presented')
                exposure.append(int(hwnd))
            return original_cloak(hwnd, enabled)

        presentation._cloak = record_cloak
        try:
            for _ in range(12):
                pump()
                if dialog._native_presentation_pending:
                    assert user32.IsWindowEnabled(owner), (
                        'Invisible cold dialog disabled the main window')
            assert len(exposure) == 1, exposure
            assert not user32.IsWindowEnabled(owner), 'Presented modal did not disable its owner'
            assert user32.IsWindowVisible(wintypes.HWND(native.winId(dialog.tag)))
        finally:
            presentation._cloak = original_cloak
            dialog.accept()
            pump(4)
        assert user32.IsWindowEnabled(owner), 'Closing modal left WinUx disabled'

    try:
        # No warm-up by default: Job Details is the very first rendered dialog,
        # before even the main viewport's deferred startup callback has run.
        pump(startup_frames)
        show_and_verify('Job Details')
        show_and_verify('Job Status')
        parent = view.show_message('Parent dialog', 'Open a nested dialog')
        pump(6)
        parent_hwnd = wintypes.HWND(native.winId(parent.tag))
        nested = view.show_message('Nested dialog', 'Keep the original native owner')
        for _ in range(8):
            pump()
            if nested._native_presentation_pending:
                assert user32.IsWindowEnabled(parent_hwnd)
        user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
        user32.GetWindow.restype = wintypes.HWND
        assert int(user32.GetWindow(wintypes.HWND(native.winId(nested.tag)), 4) or 0) == parent_hwnd.value
        assert not user32.IsWindowEnabled(parent_hwnd)
        nested.accept()
        pump(4)
        assert user32.IsWindowEnabled(parent_hwnd)
        assert not user32.IsWindowEnabled(owner)
        parent.accept()
        pump(4)
        assert user32.IsWindowEnabled(owner)
        early = view.show_message('Cancelled during startup', 'Job 123')
        pump()
        early.accept()
        pump(4)
        assert user32.IsWindowEnabled(owner), 'Cancelled hidden modal disabled WinUx'
        assert not presentation.pending and not presentation.cloaked
        print('PASS: cold Job Details/Status after {} startup frames; '
              'deferred modality, nested ownership, close and early cancellation'.format(startup_frames), flush=True)
    finally:
        view.request_shutdown()
        view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
