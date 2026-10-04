"""Actual hidden-HWND WNDPROC chain coverage, without a GUI viewport."""
import ctypes
from ctypes import wintypes
import os
from types import SimpleNamespace
import unittest

from WinUx.components.explorer_native_hook import ExplorerNativeHook


@unittest.skipUnless(os.name == "nt", "requires Win32")
class RealWindowHookTests(unittest.TestCase):
    def setUp(self):
        self.user32 = ctypes.windll.user32
        self.user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
        ]
        self.user32.CreateWindowExW.restype = wintypes.HWND
        self.user32.DestroyWindow.argtypes = [wintypes.HWND]
        self.user32.DestroyWindow.restype = wintypes.BOOL
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user32.IsWindowVisible.restype = wintypes.BOOL
        self.user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.GetWindowLongW.restype = wintypes.LONG
        self.user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.user32.SendMessageW.restype = ctypes.c_ssize_t
        self.hwnd = self.user32.CreateWindowExW(
            0, "STATIC", "WinUx hidden hook test", 0x80000000,
            0, 0, 100, 100, None, None, None, None)
        self.assertTrue(self.hwnd, "hidden test window creation failed")
        self.assertFalse(self.user32.IsWindowVisible(self.hwnd))
        self.hooks = []

    def tearDown(self):
        for hook in reversed(self.hooks):
            if hook._native_cursor_hook_active:
                self.assertTrue(hook._uninstall_native_cursor_hook())
        if self.hwnd:
            self.user32.DestroyWindow(self.hwnd)

    def install(self):
        view = SimpleNamespace(uid="hidden_hook", _item_drag_active=False,
                               _resize_key=None, SEPARATOR_HIT=8)
        registry = SimpleNamespace(_external_cursor_provider=None, _PENDING_EXTERNAL_DROPS=[])
        hook = ExplorerNativeHook(view, SimpleNamespace(), registry)
        hook._find_own_top_level_hwnd = lambda: self.hwnd
        hook._install_native_cursor_hook()
        self.hooks.append(hook)
        self.assertTrue(hook._native_cursor_hook_active)
        return hook

    def accepts_drops(self):
        return bool(self.user32.GetWindowLongW(self.hwnd, -20) & 0x10)

    def test_real_chain_restores_in_order_and_accepts_until_last_owner(self):
        first, second = self.install(), self.install()
        self.assertTrue(self.accepts_drops())
        self.assertFalse(first._uninstall_native_cursor_hook())
        self.assertTrue(self.accepts_drops())
        self.assertTrue(second._uninstall_native_cursor_hook())
        self.assertTrue(self.accepts_drops())
        self.assertTrue(first._uninstall_native_cursor_hook())
        self.assertFalse(self.accepts_drops())
        self.assertNotIn(self.hwnd, ExplorerNativeHook._drop_owners)

    def test_real_callback_forwards_unhandled_messages(self):
        hook = self.install()
        caption = "forwarded native message"
        buffer = ctypes.create_unicode_buffer(caption)
        self.assertTrue(self.user32.SendMessageW(self.hwnd, 0x000C, 0,
                                               ctypes.cast(buffer, ctypes.c_void_p).value))
        output = ctypes.create_unicode_buffer(100)
        self.user32.SendMessageW(self.hwnd, 0x000D, 100, ctypes.cast(output, ctypes.c_void_p).value)
        self.assertEqual(output.value, caption)
        self.assertIsNotNone(hook._native_wndproc_callback)

    def test_destroyed_hwnd_releases_callback_registry_without_restoring_proc(self):
        hook = self.install()
        hwnd = self.hwnd
        self.assertTrue(self.user32.DestroyWindow(hwnd))
        self.hwnd = None
        self.assertTrue(hook._uninstall_native_cursor_hook())
        self.assertIsNone(hook._native_wndproc_callback)
        self.assertFalse(hook._native_cursor_hook_active)
        self.assertNotIn(hwnd, ExplorerNativeHook._drop_owners)

    def test_provider_exception_cannot_escape_real_ctypes_callback(self):
        hook = self.install()
        def provider():
            raise ValueError("test cursor provider failure")
        hook.registry._external_cursor_provider = provider
        result = self.user32.SendMessageW(self.hwnd, 0x0020, self.hwnd, 1)
        self.assertIsInstance(result, int)
        self.assertTrue(hook._native_cursor_hook_active)
