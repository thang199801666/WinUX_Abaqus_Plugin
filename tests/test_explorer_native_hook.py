import ctypes
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from WinUx.components.explorer_native_hook import ExplorerNativeHook


class NativeHookTests(unittest.TestCase):
    def setUp(self):
        self.user32, self.shell32 = Mock(), Mock()
        self.native = SimpleNamespace(user32=self.user32, shell32=self.shell32)
        for patcher in (patch.object(ctypes, "windll", self.native, create=True),
                        patch.object(ctypes, "set_last_error", Mock(), create=True),
                        patch.object(ctypes, "get_last_error", Mock(return_value=0), create=True),
                        patch.object(ExplorerNativeHook, "_drop_owners", {})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def hook(self):
        hook = ExplorerNativeHook(SimpleNamespace(), Mock(), SimpleNamespace())
        hook._native_hwnd, hook._native_old_wndproc = 10, 123
        hook._native_wndproc_callback = ctypes.CFUNCTYPE(ctypes.c_int)(lambda: 0)
        hook._native_cursor_hook_active = hook._native_drop_enabled = True
        return hook

    def make_top(self, hook):
        address = ctypes.cast(hook._native_wndproc_callback, ctypes.c_void_p).value
        self.user32.GetWindowLongPtrW.return_value = address
        self.user32.GetWindowLongW.return_value = address

    def test_deferred_hook_preserves_drop_acceptance_and_callback(self):
        hook = self.hook()
        ExplorerNativeHook._drop_owners[10] = {hook}
        self.user32.GetWindowLongPtrW.return_value = 999
        self.user32.GetWindowLongW.return_value = 999
        self.assertFalse(hook._uninstall_native_cursor_hook())
        self.shell32.DragAcceptFiles.assert_not_called()
        self.assertIsNotNone(hook._native_wndproc_callback)
        self.assertIn(hook, ExplorerNativeHook._drop_owners[10])

    def test_uninstall_top_preserves_other_owner_and_last_owner_disables_drops(self):
        first, second = self.hook(), self.hook()
        ExplorerNativeHook._drop_owners[10] = {first, second}
        self.make_top(second)
        self.assertTrue(second._uninstall_native_cursor_hook())
        self.shell32.DragAcceptFiles.assert_not_called()
        self.assertEqual(ExplorerNativeHook._drop_owners[10], {first})
        self.make_top(first)
        self.assertTrue(first._uninstall_native_cursor_hook())
        self.assertEqual(self.shell32.DragAcceptFiles.call_args.args[1], False)
        self.assertNotIn(10, ExplorerNativeHook._drop_owners)
        self.assertIsNone(first._native_wndproc_callback)
        self.assertFalse(first._uninstall_native_cursor_hook())

    def test_restore_failure_preserves_callback_and_drop_registration(self):
        hook = self.hook()
        ExplorerNativeHook._drop_owners[10] = {hook}
        self.make_top(hook)
        self.user32.SetWindowLongPtrW.side_effect = OSError("restore failed")
        self.user32.SetWindowLongW.side_effect = OSError("restore failed")
        self.assertFalse(hook._uninstall_native_cursor_hook())
        self.shell32.DragAcceptFiles.assert_not_called()
        self.assertIn(hook, ExplorerNativeHook._drop_owners[10])
        self.assertTrue(hook._native_cursor_hook_active)

    def test_shell_drop_handle_released_on_query_failure(self):
        hook = self.hook()
        self.shell32.DragQueryFileW.side_effect = OSError("query failed")
        with self.assertRaises(OSError):
            hook._read_shell_drop(self.shell32, 123)
        self.shell32.DragFinish.assert_called_once_with(123)

    def test_shell_drop_keeps_unicode_paths_and_drop_point(self):
        hook = self.hook()
        paths = ["D:/caf\u00e9.inp", "D:/other.inp"]
        def point(handle, output):
            output._obj.x, output._obj.y = 12, 34
            return True
        def query(handle, index, buffer, length):
            if index == 0xFFFFFFFF:
                return len(paths)
            if buffer is not None:
                buffer.value = paths[index]
            return len(paths[index])
        self.shell32.DragQueryPoint.side_effect = point
        self.shell32.DragQueryFileW.side_effect = query
        actual, drop = hook._read_shell_drop(self.shell32, 123)
        self.assertEqual(actual, paths)
        self.assertEqual((drop.x, drop.y), (12, 34))
        self.shell32.DragFinish.assert_called_once_with(123)

    def test_geometry_without_header_clears_old_hit_regions(self):
        hook = self.hook()
        hook.view.header_canvas = "header"
        hook.view._safe_item_rect = lambda item: None
        hook._native_header_screen_rect = (0, 0, 100, 30)
        hook._native_separator_screen_x = (50,)
        hook._update_native_cursor_geometry()
        self.assertIsNone(hook._native_header_screen_rect)
        self.assertEqual(hook._native_separator_screen_x, ())
