"""Exercise Esc/selector/Exit against the real main GLFW viewport and hooks."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock

from WinUx.controller import WinUXController
from WinUx.controllers import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView
from WinUx.ui.native.floating_viewport import cloaked


@unittest.skipUnless(os.name == "nt", "Requires Windows native viewports")
class MainWindowDialogCycleTests(unittest.TestCase):
    def test_digitizer_selector_escape_then_native_main_close(self):
        user32 = ctypes.windll.user32
        enum_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [enum_type, wintypes.LPARAM]
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetWindow.restype = wintypes.HWND
        user32.IsWindowEnabled.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                       wintypes.WPARAM, wintypes.LPARAM]
        callbacks = {name: Mock(return_value=[]) for name in REQUIRED_CALLBACK_KEYS}
        view = WinUXView(callbacks)
        app = object.__new__(WinUXController)
        app._closing = app._close_confirmation_pending = False
        app.job_schedules = Mock(return_value=[])
        app.view = view
        app._finish_close = Mock()
        view.protocol("WM_DELETE_WINDOW", app.close)
        errors = []
        view._handle_ui_callback_error = lambda callback, info: errors.append(info[1])
        view.show_error = lambda *args: errors.append(AssertionError(str(args)))
        completed = []
        temporary_root = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode"
        temporary_root.mkdir(parents=True, exist_ok=True)

        def selector_window(owner):
            found = []
            def visit(hwnd, _param):
                if user32.GetWindow(hwnd, 4) == owner and user32.IsWindowVisible(hwnd):
                    title = ctypes.create_unicode_buffer(128)
                    user32.GetWindowTextW(hwnd, title, 128)
                    if title.value in ("Open File", "Open Folder"):
                        found.append(int(hwnd))
                return True
            user32.EnumWindows(enum_type(visit), 0)
            return found[0] if found else None

        def escape(hwnd):
            user32.PostMessageW(hwnd, 0x0100, 27, 0x00010001)
            user32.PostMessageW(hwnd, 0x0101, 27, 0xc0010001)

        with tempfile.TemporaryDirectory(dir=temporary_root) as folder:
            def scenario():
                user32.PostMessageW(view._find_main_viewport_hwnd(), 0x0010, 0, 0)
                yield "baseline-close-confirm", lambda: (
                    getattr(view, "_async_confirm_dialog", None) is not None
                    and view._async_confirm_dialog._ready)
                view._async_confirm_dialog.reject()
                yield "baseline-close-cancelled", lambda: not app._close_confirmation_pending
                for cycle in range(3):
                    view._show_plot_digitizer_dialog()
                    digitizer = view._plot_digitizer_dialog
                    yield "digitizer-ready", lambda: (
                        digitizer._ready and digitizer._native_visible
                        and user32.IsWindowVisible(digitizer._hwnd))
                    digitizer.post("open_file_selector")
                    yield "nested-selector-ready", lambda: (
                        selector_window(digitizer._hwnd)
                        and not user32.IsWindowEnabled(digitizer._hwnd))
                    selector = selector_window(digitizer._hwnd)
                    # Reopening/activating an already resident tool while its
                    # selector owns input must not unblock or focus the owner.
                    digitizer.show()
                    settle = time.monotonic() + .15
                    yield "nested-selector-keeps-input", lambda: time.monotonic() >= settle
                    self.assertFalse(user32.IsWindowEnabled(digitizer._hwnd))
                    self.assertTrue(user32.IsWindowEnabled(selector))
                    self.assertTrue(user32.IsWindowVisible(selector))
                    if cycle == 1:
                        # Both commands race with selector close/visibility IPC.
                        # Hiding a resident parent must cancel its selector, and
                        # the old hide ACK must not undo the immediate reopen.
                        digitizer.hide()
                        digitizer.show()
                        yield "rapid-reopen-cancels-selector", lambda: (
                            not user32.IsWindowVisible(selector)
                            and user32.IsWindowVisible(digitizer._hwnd)
                            and user32.IsWindowEnabled(digitizer._hwnd)
                            and digitizer._visible and digitizer._native_visible)
                        digitizer.post("open_file_selector")
                        yield "selector-after-rapid-reopen", lambda: (
                            selector_window(digitizer._hwnd)
                            and not user32.IsWindowEnabled(digitizer._hwnd))
                        selector = selector_window(digitizer._hwnd)
                    escape(selector)
                    yield "nested-selector-escaped", lambda: (
                        not user32.IsWindowVisible(selector)
                        and user32.IsWindowEnabled(digitizer._hwnd))
                    escape(digitizer._hwnd)
                    # A retained Qt-style tool closes by hiding, not deleting
                    # its resident host. Require actual native invisibility.
                    yield "digitizer-escaped", lambda: (
                        not user32.IsWindowVisible(digitizer._hwnd)
                        and (not digitizer.winfo_exists() or not digitizer._visible))
                    if cycle != 1:
                        browser = view.show_local_folder_dialog(folder, lambda path: None)
                        yield "main-folder-ready", lambda: browser._ready
                        escape(browser._hwnd)
                        yield "main-folder-escaped", lambda: not browser.winfo_exists()
                    # Use the actual WM_CLOSE/DPG exit callback, not app.close().
                    user32.PostMessageW(view._find_main_viewport_hwnd(), 0x0010, 0, 0)
                    yield "close-confirm-visible", lambda: (
                        getattr(view, "_async_confirm_dialog", None) is not None
                        and view._async_confirm_dialog._ready)
                    confirmation = view._async_confirm_dialog
                    self.assertTrue(user32.IsWindowVisible(confirmation._hwnd))
                    self.assertFalse(cloaked(confirmation._hwnd))
                    self.assertTrue(user32.IsWindowEnabled(confirmation._hwnd))
                    self.assertEqual(user32.GetWindow(confirmation._hwnd, 4),
                                     view._find_main_viewport_hwnd())
                    if cycle == 2:
                        confirmation.accept()
                        yield "close-confirm-accepted", lambda: app._finish_close.called
                    else:
                        confirmation.reject()
                        yield "close-confirm-cancelled", lambda: not app._close_confirmation_pending
                    self.assertTrue(user32.IsWindowEnabled(view._find_main_viewport_hwnd()))
                    completed.append(cycle)

            steps = scenario()
            pending = []

            def advance():
                try:
                    if pending:
                        name, predicate, deadline = pending[0]
                        if not predicate():
                            if time.monotonic() >= deadline:
                                from DearUIQt import input_gate
                                print("Main-window failure state:", {
                                    "close_pending": app._close_confirmation_pending,
                                    "schedule_reads": app.job_schedules.call_count,
                                    "modal_tokens": len(input_gate._native_modal_tokens),
                                    "modal_release_pending": input_gate._native_modal_release_pending,
                                    "modal_release_frame": input_gate._native_modal_release_guard_until_frame,
                                    "dialogs": [(dialog.title, dialog._closed, dialog._ready,
                                                 dialog._ipc_stage)
                                                for dialog in getattr(view, "_floating_dialogs", ())],
                                }, flush=True)
                                raise AssertionError("Main window stalled at " + name)
                            view.after(10, advance)
                            return
                        pending.clear()
                    name, predicate = next(steps)
                    print("Main-window scenario: " + name, flush=True)
                    pending.append((name, predicate, time.monotonic() + 8))
                    view.after(10, advance)
                except StopIteration:
                    view.request_shutdown()
                except Exception as exc:
                    errors.append(exc)
                    view.request_shutdown()

            view.after(350, advance)
            view.run()
        if errors:
            raise errors[0]
        self.assertEqual(completed, [0, 1, 2])
        app._finish_close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
