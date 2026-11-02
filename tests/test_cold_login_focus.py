"""Cold SSH Login foreground: abaqus python tests/test_cold_login_focus.py."""
import ctypes
import os
import sys
import time
import unittest
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from DearUIQt.backends import native_windows as windows
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.preferences.login import LoginPreferences
from WinUx.view import WinUXView


class OpeningActivationTests(unittest.TestCase):
    def setUp(self):
        self.foreground = 10
        self.tick = 123
        self.api = SimpleNamespace(**{name: Mock(return_value=True) for name in (
            'IsWindow', 'IsWindowVisible', 'BringWindowToTop', 'SetActiveWindow', 'SetFocus')})
        self.api.IsIconic = Mock(return_value=False)
        self.api.GetForegroundWindow = Mock(side_effect=lambda: self.foreground)
        self.api.SetForegroundWindow = Mock(side_effect=self.set_foreground)
        self.native = windows.NativeWindowBackend(SimpleNamespace())
        self.native.require = lambda: None
        self.native._rawWinId = lambda item: 20
        self.native._configured_item_tag = 1
        self.native._configured_owner_hwnd = 10
        for mocked in (
                patch.object(windows, '_windows_user32', return_value=self.api),
                patch.object(windows, '_last_input_tick', side_effect=lambda api: self.tick),
                patch.object(windows, '_window_process_id', return_value=os.getpid() + 1)):
            mocked.start()
            self.addCleanup(mocked.stop)

    def set_foreground(self, handle):
        self.foreground = handle.value
        return True

    def test_cold_platform_fallback_is_repaired(self):
        lease = self.native.beginOwnerOpen(1)
        self.assertIsNotNone(lease)
        self.foreground = 99  # OS/GLFW fallback, not a newer user gesture.
        self.assertTrue(self.native.activateOwnedWindow(1, opening=lease))
        self.assertEqual(self.foreground, 20)

    def test_capture_before_cold_import_or_native_item_allocation(self):
        self.native._configured_item_tag = 0
        self.native._configured_owner_hwnd = 0
        lease = self.native.beginOwnerOpen('winux_primary', owner_hwnd=10)
        self.assertIsNotNone(lease)
        self.assertEqual(lease.owner_hwnd, 10)

    def test_minimized_owner_does_not_grant_activation(self):
        self.api.IsIconic.return_value = True
        self.assertIsNone(self.native.beginOwnerOpen(1))

    def test_alt_tab_is_not_overridden(self):
        lease = self.native.beginOwnerOpen(1)
        self.foreground = 99
        self.tick += 1
        self.assertFalse(self.native.activateOwnedWindow(1, opening=lease))
        self.api.BringWindowToTop.assert_not_called()
        self.api.SetForegroundWindow.assert_not_called()

    def test_background_launch_has_no_foreground_permission(self):
        self.foreground = 99
        self.assertIsNone(self.native.beginOwnerOpen(1))
        self.assertFalse(self.native.activateOwnedWindow(1))
        self.api.SetForegroundWindow.assert_not_called()

    def test_new_same_process_dialog_supersedes_opening(self):
        lease = self.native.beginOwnerOpen(1)
        self.foreground = 99
        with patch.object(windows, '_window_process_id', return_value=os.getpid()):
            self.assertFalse(self.native.activateOwnedWindow(1, opening=lease))
        self.api.SetForegroundWindow.assert_not_called()

    def test_no_input_snapshot_does_not_authorize_focus_steal(self):
        self.tick = None
        lease = self.native.beginOwnerOpen(1)
        self.foreground = 99
        self.assertFalse(self.native.activateOwnedWindow(1, opening=lease))
        self.api.SetForegroundWindow.assert_not_called()

    def test_refused_activation_is_not_reported_as_success(self):
        self.api.SetForegroundWindow.side_effect = None
        self.api.SetForegroundWindow.return_value = False
        self.assertFalse(self.native.activateOwnedWindow(1))

    def record_click(self, x=30, y=40):
        def client_rect(handle, pointer):
            rect = ctypes.cast(pointer, ctypes.POINTER(wintypes.RECT)).contents
            rect.right, rect.bottom = 420, 250
            return True
        self.api.IsWindowEnabled = Mock(return_value=True)
        self.api.GetClientRect = Mock(side_effect=client_rect)
        self.native._recordOwnedInteraction(20, (y & 0xffff) << 16 | (x & 0xffff))

    def test_later_client_click_supersedes_stale_opening(self):
        lease = self.native.beginOwnerOpen(1)
        self.tick += 1
        self.record_click()
        self.foreground = 99
        self.assertTrue(self.native.activateOwnedWindow(1, opening=lease))
        self.assertEqual(self.foreground, 20)

    def test_outside_release_does_not_authorize_repair(self):
        self.record_click(x=-1)
        self.foreground = 99
        self.assertFalse(self.native.repairOwnedInteraction(1))
        self.api.SetForegroundWindow.assert_not_called()

    def test_alt_tab_after_client_click_cancels_repair(self):
        self.record_click()
        self.tick += 1
        self.foreground = 99
        self.assertFalse(self.native.repairOwnedInteraction(1))
        self.api.SetForegroundWindow.assert_not_called()

    def test_owner_click_after_modeless_click_cancels_repair(self):
        self.record_click()
        self.tick += 1
        self.foreground = 10
        self.assertFalse(self.native.repairOwnedInteraction(1))
        self.api.SetForegroundWindow.assert_not_called()


def verify_cold_login():
    view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
    view._gui_runtime.show()
    native = windows.NativeWindowBackend()
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    owner = wintypes.HWND(view._find_main_viewport_hwnd())

    def pump(frames=1):
        for _ in range(frames):
            view.update()
            assert user32.IsWindowVisible(owner), 'SSH Login hid WinUx'
            assert not user32.IsIconic(owner)
            time.sleep(.015)

    # Isolate this GUI scenario from physical mouse movement on the desktop.
    # The unit cases above separately verify cancellation by newer user input.
    input_snapshot = patch.object(windows, '_last_input_tick',
                                  return_value=windows._last_input_tick(user32))
    input_snapshot.start()
    try:
        # Simulate the native foreground state of a toolbar click. No warm-up
        # render: Login is the first dialog, before deferred startup runs.
        foreground_thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
        current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        attached = user32.AttachThreadInput(current_thread, foreground_thread, True)
        try:
            user32.SetForegroundWindow(owner)
        finally:
            if attached:
                user32.AttachThreadInput(current_thread, foreground_thread, False)
        assert int(user32.GetForegroundWindow() or 0) == owner.value
        with patch.object(LoginPreferences, 'load', return_value={}):
            dialog = view.show_login()
        assert dialog._native_owner_open_lease is not None
        pump(12)
        child = native.winId(dialog.tag)
        assert child and int(user32.GetForegroundWindow() or 0) == child, (
            'Cold SSH Login fell behind another application')
        user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
        user32.GetWindow.restype = wintypes.HWND
        assert int(user32.GetWindow(wintypes.HWND(child), 4) or 0) == owner.value
        behind = int(user32.GetWindow(wintypes.HWND(child), 2) or 0)
        while behind and not user32.IsWindowVisible(wintypes.HWND(behind)):
            behind = int(user32.GetWindow(wintypes.HWND(behind), 2) or 0)
        assert behind == owner.value, 'WinUx did not remain behind SSH Login'
        assert not user32.IsWindowEnabled(owner)
        dialog.cancel_from_window()
        pump(6)
        assert user32.IsWindowEnabled(owner)
        print('PASS: first-click cold SSH Login, foreground/owner order and Cancel', flush=True)
    finally:
        input_snapshot.stop()
        view.request_shutdown()
        view._gui_runtime.destroy()


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(OpeningActivationTests))
    if not result.wasSuccessful():
        sys.exit(1)
    verify_cold_login()
