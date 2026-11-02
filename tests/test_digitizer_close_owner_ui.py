"""Close confirmation must belong to and stack above Plot Digitizer, not WinUx."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.ui.hosting.floating_runtime import FloatingDialogRuntime


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='digitizer-close-owner-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile, 'WINUX_LOG_DIR': str(temp / 'digitizer-close-owner-logs')}):
        runtime = None
        if '--standalone' in sys.argv:
            runtime = FloatingDialogRuntime(Mock(), iter(()), {
                'kind': 'plotdigitizer', 'title': 'Plot Digitizer', 'visible': True,
                'payload': {}, 'width': 1240, 'height': 800})
            runtime.gui.createContext(manual_callbacks=True)
            runtime._publish_requested = runtime._commit_requested = True
            runtime._build()
            view, digitizer = runtime.view, runtime.form
        else:
            from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
            from WinUx.dialogs.native_reference_tools import PlotDigitizerDialog
            from WinUx.view import WinUXView
            view = WinUXView({key: lambda *a, **kw: None for key in REQUIRED_CALLBACK_KEYS})
            view._gui_runtime.show()
            digitizer = PlotDigitizerDialog(view)
            digitizer.show()

        def pump(count=30):
            for _ in range(count):
                if runtime is not None:
                    runtime._drain_form_callbacks()
                    view.drain()
                    runtime.gui.renderFrame()
                    view.mark_presented()
                else:
                    view.update()
                time.sleep(.01)

        native_checks = []
        def check_owner(prompt):
            assert prompt is not None and prompt.isVisible()
            assert prompt._requested_parent is digitizer
            assert prompt._modal_owner_candidate() is digitizer
            assert prompt.modal
            native = getattr(prompt, '_native_window_backend', None)
            owner_backend = getattr(digitizer, '_native_window_backend', None)
            child_hwnd = native.winId(prompt.tag) if native is not None else 0
            owner_hwnd = owner_backend.winId(digitizer.tag) if owner_backend is not None else 0
            if native is not None:
                assert child_hwnd, 'Warning native HWND was not presented'
            if owner_backend is not None:
                assert owner_hwnd, 'Plot Digitizer native HWND was not presented'
            if not owner_hwnd:
                owner_hwnd = view._find_main_viewport_hwnd()
            if child_hwnd and owner_hwnd:
                user32 = ctypes.windll.user32
                user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
                user32.GetWindow.restype = wintypes.HWND
                actual_owner = int(user32.GetWindow(wintypes.HWND(child_hwnd), 4) or 0)
                assert actual_owner == owner_hwnd, ('Wrong GW_OWNER', actual_owner, owner_hwnd)
                native_checks.append((child_hwnd, owner_hwnd))
                # Owned HWNDs must stack above their owner even on a desktop
                # where foreground activation / screen capture is unavailable.
                user32.GetTopWindow.argtypes = [wintypes.HWND]
                user32.GetTopWindow.restype = wintypes.HWND
                window, order = user32.GetTopWindow(None), []
                while window and len(order) < 10000:
                    order.append(int(window))
                    window = user32.GetWindow(window, 2)
                if child_hwnd in order and owner_hwnd in order:
                    assert order.index(child_hwnd) < order.index(owner_hwnd), 'Warning is behind Plot Digitizer'

        try:
            pump(40)
            original_hwnd = None
            if '--native-close' in sys.argv:
                backend = getattr(digitizer, '_native_window_backend', None)
                hwnd = backend.winId(digitizer.tag) if backend is not None else runtime.native.hwnd
                original_hwnd = hwnd
                ctypes.windll.user32.PostMessageW(wintypes.HWND(hwnd), 0x0010, 0, 0)
                ctypes.windll.user32.PostMessageW(wintypes.HWND(hwnd), 0x0010, 0, 0)
            else:
                digitizer._close_from_native()
            pump(40)
            prompt = digitizer._close_confirmation_dialog
            check_owner(prompt)
            if original_hwnd and backend is not None:
                assert backend.winId(digitizer.tag) == original_hwnd, 'WM_CLOSE destroyed the warning owner'
            digitizer._close_from_native()
            assert digitizer._close_confirmation_dialog is prompt, 'Duplicate close prompt'
            prompt._close_from_escape()
            pump()
            assert digitizer.isVisible() and not digitizer._close_confirmation_pending
            if original_hwnd and backend is not None:
                assert backend.winId(digitizer.tag) == original_hwnd, 'Cancel must retain the original native tool window'
                assert ctypes.windll.user32.IsWindowEnabled(wintypes.HWND(original_hwnd)), 'Cancel must re-enable Plot Digitizer'
            if runtime is None:
                assert view._async_confirm_active is None
                earlier = view.confirm_action_async('Earlier confirmation', 'Queue ownership test', lambda value: None)
                pump()
                digitizer._close_from_native()
                assert digitizer._close_confirmation_dialog is None
                earlier.finish(False)
                pump(40)
                queued = view._async_confirm_dialog
                check_owner(queued)
                digitizer._close_from_native()
                assert digitizer._close_confirmation_dialog is queued
                queued.finish(False)
                pump()
            digitizer._close_from_native()
            pump()
            prompt = digitizer._close_confirmation_dialog
            check_owner(prompt)
            prompt.accept()
            pump(8)
            assert not digitizer.isVisible()
            assert not digitizer._close_confirmation_pending
            if runtime is None:
                assert view._async_confirm_active is None
                digitizer.show()
                pump()
                if '--native-close' in sys.argv:
                    hwnd = digitizer._native_window_backend.winId(digitizer.tag)
                    ctypes.windll.user32.PostMessageW(wintypes.HWND(hwnd), 0x0010, 0, 0)
                else:
                    digitizer._close_from_native()
                pump(40)
                check_owner(digitizer._close_confirmation_dialog)
                digitizer.hard_destroy()
                pump()
                assert view._async_confirm_active is None, 'Tool teardown stranded confirmation queue'
            print('PASS: Plot Digitizer-owned warning; {} native GW_OWNER/z-order checks; '
                  'queued/deduplicated close, Cancel, Exit and teardown'.format(len(native_checks)), flush=True)
        finally:
            if runtime is not None:
                view._dispatcher.close()
                if runtime.native:
                    runtime.native.set_visible(False)
                    runtime.native.restore_close_handler()
                    runtime.native.close_activation_guard()
                runtime.gui.destroy()
            else:
                digitizer.hard_destroy()
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
