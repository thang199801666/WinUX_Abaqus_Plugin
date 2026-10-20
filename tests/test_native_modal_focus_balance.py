"""Focus repair must never undo another dialog's native input blocking."""
import ctypes
from ctypes import wintypes
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from WinUx.ui.native import native_dialog_host as host


class ModalOwnerBalanceTests(unittest.TestCase):
    def setUp(self):
        self.enabled = {100: True}
        self.api = SimpleNamespace(
            IsWindow=Mock(return_value=True),
            IsWindowVisible=Mock(return_value=True),
            IsWindowEnabled=Mock(side_effect=lambda hwnd: self.enabled.get(hwnd.value, False)),
            GetForegroundWindow=Mock(return_value=100),
            GetWindowThreadProcessId=Mock(return_value=1),
            AttachThreadInput=Mock(return_value=True),
            BringWindowToTop=Mock(), SetForegroundWindow=Mock(),
            SetActiveWindow=Mock(), SetFocus=Mock(),
        )
        self.changes = []

        def set_enabled(hwnd, enabled):
            self.enabled[int(hwnd)] = enabled
            self.changes.append((int(hwnd), enabled))

        self.contexts = [
            patch.object(host, "os", SimpleNamespace(name="nt")),
            patch.object(host, "_MODAL_OWNER_COUNTS", {}),
            patch.object(host, "_MODAL_OWNER_WAS_ENABLED", {}),
            patch.object(ctypes, "windll", SimpleNamespace(user32=self.api,
                         kernel32=SimpleNamespace(GetCurrentThreadId=Mock(return_value=1))), create=True),
            patch.object(host, "set_owner_enabled", side_effect=set_enabled),
            patch.object(host, "release_owner_mouse_capture"),
            patch.object(host, "restore_owner_focus"),
        ]
        for context in self.contexts:
            context.start()
            self.addCleanup(context.stop)

    def test_two_modals_enable_owner_only_after_final_release(self):
        self.assertTrue(host._acquire_modal_owner(100))
        self.assertTrue(host._acquire_modal_owner(100))
        host._release_modal_owner(100)
        self.assertFalse(self.enabled[100])
        host.restore_owner_focus.assert_not_called()
        host._release_modal_owner(100)
        self.assertTrue(self.enabled[100])
        self.assertEqual(self.changes, [(100, False), (100, True)])
        host.restore_owner_focus.assert_called_once_with(100)

    def test_unmatched_release_does_not_enable_or_focus_owner(self):
        self.enabled[100] = False
        host._release_modal_owner(100)
        self.assertEqual(self.changes, [])
        host.restore_owner_focus.assert_not_called()

    def test_owner_disabled_before_first_acquire_remains_disabled(self):
        self.enabled[100] = False
        host._acquire_modal_owner(100)
        host._release_modal_owner(100)
        self.assertFalse(self.enabled[100])
        host.restore_owner_focus.assert_not_called()

    def test_duplicate_release_after_balanced_close_has_no_side_effect(self):
        host._acquire_modal_owner(100)
        host._release_modal_owner(100)
        self.changes.clear()
        host.restore_owner_focus.reset_mock()
        host._release_modal_owner(100)
        self.assertEqual(self.changes, [])
        host.restore_owner_focus.assert_not_called()

    def test_invalid_owner_cannot_acquire_a_modal_reference(self):
        self.api.IsWindow.return_value = False
        self.assertFalse(host._acquire_modal_owner(100))
        self.assertEqual(host._MODAL_OWNER_COUNTS, {})

    def test_focus_repair_refuses_disabled_owner_without_enabling_it(self):
        self.enabled[100] = False
        self.assertFalse(host._restore_owner_activation(100, raise_z_order=True))
        self.assertEqual(self.changes, [])


@unittest.skipUnless(os.name == "nt", "Requires real native windows")
class NativeModalBalanceTests(unittest.TestCase):
    def test_real_owner_stays_blocked_when_one_of_two_selectors_closes(self):
        user32 = ctypes.windll.user32
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.IsWindowEnabled.argtypes = [wintypes.HWND]
        hwnd = user32.CreateWindowExW(0x08000000, "STATIC", "Modal balance check",
                                     0x90000000, -20000, -20000, 20, 20,
                                     None, None, None, None)
        self.assertTrue(hwnd)
        acquired = 0
        try:
            for _ in range(2):
                self.assertTrue(host._acquire_modal_owner(hwnd))
                acquired += 1
            host._release_modal_owner(hwnd, restore_focus=False)
            acquired -= 1
            self.assertFalse(user32.IsWindowEnabled(hwnd))
            self.assertFalse(host._restore_owner_activation(hwnd))
            self.assertFalse(user32.IsWindowEnabled(hwnd), "Focus repair bypassed the remaining modal")
            host._release_modal_owner(hwnd, restore_focus=False)
            acquired -= 1
            self.assertTrue(user32.IsWindowEnabled(hwnd))
        finally:
            for _ in range(acquired):
                host._release_modal_owner(hwnd, restore_focus=False)
            user32.DestroyWindow(hwnd)


if __name__ == "__main__":
    unittest.main()
