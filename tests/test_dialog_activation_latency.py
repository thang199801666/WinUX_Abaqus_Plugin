"""Native stacking must not synchronously wait for a busy owner GUI thread."""
import ctypes
from ctypes import wintypes
import os
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from WinUx.ui.native.native_dialog_host import prepare_owned_dialog_stack


class ActivationStackTests(unittest.TestCase):
    def api(self, foreground):
        return SimpleNamespace(IsWindow=Mock(return_value=True),
                               IsWindowVisible=Mock(return_value=True),
                               GetForegroundWindow=Mock(return_value=foreground),
                               SetWindowPos=Mock(return_value=True))

    def test_foreground_owner_does_not_need_redundant_cross_thread_raise(self):
        api = self.api(100)
        with patch("WinUx.ui.native.native_dialog_host.os.name", "nt"), \
                patch.object(ctypes, "windll", SimpleNamespace(user32=api), create=True):
            self.assertTrue(prepare_owned_dialog_stack(100, 200))
        api.SetWindowPos.assert_not_called()

    def test_foreground_dialog_stack_repair_posts_foreign_owner_position_asynchronously(self):
        api = self.api(200)
        with patch("WinUx.ui.native.native_dialog_host.os.name", "nt"), \
                patch.object(ctypes, "windll", SimpleNamespace(user32=api), create=True):
            self.assertTrue(prepare_owned_dialog_stack(100, 200))
        flags = api.SetWindowPos.call_args_list[0].args[-1]
        self.assertTrue(flags & 0x4000, "owner SetWindowPos must use SWP_ASYNCWINDOWPOS")
        self.assertTrue(flags & 0x0010, "stack repair must remain nonactivating")

    def test_unrelated_foreground_is_never_raised_over(self):
        api = self.api(999)
        with patch("WinUx.ui.native.native_dialog_host.os.name", "nt"), \
                patch.object(ctypes, "windll", SimpleNamespace(user32=api), create=True):
            self.assertFalse(prepare_owned_dialog_stack(100, 200))
        api.SetWindowPos.assert_not_called()


@unittest.skipUnless(os.name == "nt", "Requires real Windows GUI queues")
class BusyOwnerActivationTests(unittest.TestCase):
    def test_busy_owner_does_not_hold_up_dialog_stack_preparation(self):
        user32 = ctypes.windll.user32
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        ready, release = threading.Event(), threading.Event()
        owner = []

        def busy_owner():
            hwnd = user32.CreateWindowExW(0x08000000, "STATIC", "Busy test owner", 0x90000000,
                                          -20000, -20000, 20, 20, None, None, None, None)
            owner.append(hwnd)
            ready.set()
            release.wait(2)
            user32.DestroyWindow(hwnd)

        worker = threading.Thread(target=busy_owner, daemon=True)
        worker.start()
        self.assertTrue(ready.wait(2))
        self.assertTrue(owner[0])
        dialog = user32.CreateWindowExW(0x08000000, "STATIC", "Test dialog", 0x90000000,
                                        -20000, -20000, 20, 20, None, None, None, None)
        timer = threading.Timer(.6, release.set)
        try:
            self.assertTrue(dialog)
            timer.start()
            with patch.object(user32, "GetForegroundWindow", Mock(return_value=dialog)):
                started = time.perf_counter()
                self.assertTrue(prepare_owned_dialog_stack(owner[0], dialog))
                elapsed = time.perf_counter() - started
            self.assertLess(elapsed, .25, "stacking synchronously waited for the busy owner")
        finally:
            release.set()
            timer.cancel()
            worker.join(timeout=2)
            user32.DestroyWindow(dialog)


if __name__ == "__main__":
    unittest.main()
