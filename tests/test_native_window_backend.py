import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from DearUIQt.backends.api import BackendCapabilityError
from DearUIQt.backends.native_windows import NativeWindowBackend
from DearUIQt.runtime import QGuiRuntime


class NativeWindowBackendTests(unittest.TestCase):
    def extension(self):
        return SimpleNamespace(
            dearuiqt_enable_native_windows=Mock(return_value=True),
            dearuiqt_native_windows_enabled=Mock(return_value=True),
            dearuiqt_configure_native_window=Mock(),
            dearuiqt_native_window_handle=Mock(return_value=1234))

    def test_stock_backend_never_silently_emulates_native_windows(self):
        native = NativeWindowBackend(SimpleNamespace())
        self.assertFalse(native.available())
        self.assertFalse(native.isEnabled())
        with self.assertRaises(BackendCapabilityError):
            native.enable()

    def test_native_api_is_reached_through_renderer_boundary(self):
        extension = self.extension()
        native = NativeWindowBackend(SimpleNamespace(internal_dpg=extension))
        self.assertTrue(native.enable())
        native.configure(SimpleNamespace(tag=12), owner=SimpleNamespace(tag=13), modal=True)
        extension.dearuiqt_configure_native_window.assert_called_once_with(12, 13, True)
        self.assertEqual(native.winId(12), 1234)


    def test_fixed_native_dialog_removes_resize_frame_and_maximize_box(self):
        import DearUIQt.backends.native_windows as native_windows

        extension = self.extension()
        native = NativeWindowBackend(SimpleNamespace(internal_dpg=extension))
        original_style = 0x06CF0000
        expected_style = original_style & ~(0x00040000 | 0x00010000)

        class FakeUser32:
            pass

        user32 = FakeUser32()
        user32.GetWindowLongPtrW = Mock(return_value=original_style)
        user32.GetWindowLongW = user32.GetWindowLongPtrW
        user32.SetWindowLongPtrW = Mock(return_value=original_style)
        user32.SetWindowLongW = user32.SetWindowLongPtrW
        user32.SetWindowPos = Mock(return_value=True)
        original = native_windows._windows_user32
        native_windows._windows_user32 = lambda: user32
        try:
            self.assertTrue(native.setResizable(12, False))
        finally:
            native_windows._windows_user32 = original

        args = user32.SetWindowLongPtrW.call_args.args
        self.assertEqual(args[1], -16)
        self.assertEqual(int(args[2]) & 0xFFFFFFFF, expected_style)
        frame_flags = user32.SetWindowPos.call_args.args[-1]
        self.assertTrue(frame_flags & 0x0020)


    def test_qdialog_caption_policy_removes_minimize_box_but_preserves_close(self):
        import DearUIQt.backends.native_windows as native_windows

        extension = self.extension()
        native = NativeWindowBackend(SimpleNamespace(internal_dpg=extension))
        original_style = 0x06CF0000
        WS_MINIMIZEBOX = 0x00020000
        WS_MAXIMIZEBOX = 0x00010000

        class FakeUser32:
            pass

        user32 = FakeUser32()
        user32.GetWindowLongPtrW = Mock(return_value=original_style)
        user32.GetWindowLongW = user32.GetWindowLongPtrW
        user32.SetWindowLongPtrW = Mock(return_value=original_style)
        user32.SetWindowLongW = user32.SetWindowLongPtrW
        user32.SetWindowPos = Mock(return_value=True)
        original = native_windows._windows_user32
        native_windows._windows_user32 = lambda: user32
        try:
            self.assertTrue(native.setCaptionButtons(
                12, allow_minimize=False, allow_maximize=False))
        finally:
            native_windows._windows_user32 = original

        args = user32.SetWindowLongPtrW.call_args.args
        desired = int(args[2]) & 0xFFFFFFFF
        self.assertFalse(desired & WS_MINIMIZEBOX)
        self.assertFalse(desired & WS_MAXIMIZEBOX)
        self.assertTrue(desired & 0x00080000)  # WS_SYSMENU / Close remains available.
        self.assertTrue(user32.SetWindowPos.call_args.args[-1] & 0x0020)

    def test_runtime_requires_context_before_native_enable(self):
        extension = self.extension()
        extension.create_context = Mock()
        runtime = QGuiRuntime(extension)
        self.assertTrue(runtime.supportsNativeWindows())
        with self.assertRaises(RuntimeError):
            runtime.enableNativeWindows()
        runtime.createContext()
        self.assertTrue(runtime.enableNativeWindows())

    def test_existing_configure_application_contract_is_preserved(self):
        backend = SimpleNamespace(configure_app=Mock())
        runtime = QGuiRuntime(backend)
        self.assertTrue(runtime.configureApplication(manual_callback_management=True))
        backend.configure_app.assert_called_once_with(manual_callback_management=True)


if __name__ == "__main__":
    unittest.main()

class NativeOwnerHandoffTests(unittest.TestCase):
    class FakeUser32:
        def __init__(self, foreground=1234, owner=5678, enabled=False):
            self.foreground = foreground
            self.owner = owner
            self.enabled = enabled
            self.calls = []
            self.GetWindow = Mock(side_effect=self._get_window)
            self.IsWindow = Mock(return_value=True)
            self.IsWindowVisible = Mock(return_value=True)
            self.GetForegroundWindow = Mock(side_effect=lambda: self.foreground)
            self.IsWindowEnabled = Mock(side_effect=lambda _hwnd: self.enabled)
            self.EnableWindow = Mock(side_effect=self._enable)
            self.BringWindowToTop = Mock(side_effect=lambda _hwnd: self.calls.append("raise") or True)
            self.SetForegroundWindow = Mock(side_effect=self._foreground)
            self.SetActiveWindow = Mock(side_effect=lambda _hwnd: self.calls.append("active") or 0)
            self.SetFocus = Mock(side_effect=lambda _hwnd: self.calls.append("focus") or 0)

        def _get_window(self, _hwnd, relation):
            self.calls.append(("owner", relation))
            return self.owner

        def _enable(self, _hwnd, value):
            self.enabled = bool(value)
            self.calls.append("enable")
            return True

        def _foreground(self, hwnd):
            self.foreground = int(getattr(hwnd, "value", hwnd) or 0)
            self.calls.append("foreground")
            return True

    def backend(self):
        extension = SimpleNamespace(
            dearuiqt_enable_native_windows=Mock(return_value=True),
            dearuiqt_native_windows_enabled=Mock(return_value=True),
            dearuiqt_configure_native_window=Mock(),
            dearuiqt_native_window_handle=Mock(return_value=1234))
        return NativeWindowBackend(SimpleNamespace(internal_dpg=extension))

    def test_foreground_native_dialog_hands_off_to_disabled_owner_before_hide(self):
        import DearUIQt.backends.native_windows as native_windows
        user32 = self.FakeUser32(foreground=1234, owner=5678, enabled=False)
        original = native_windows._windows_user32
        native_windows._windows_user32 = lambda: user32
        try:
            self.assertTrue(self.backend().handoffOwnerBeforeHide(99))
        finally:
            native_windows._windows_user32 = original
        self.assertTrue(user32.enabled)
        self.assertEqual(user32.foreground, 5678)
        self.assertLess(user32.calls.index("enable"), user32.calls.index("raise"))
        self.assertLess(user32.calls.index("raise"), user32.calls.index("foreground"))

    def test_background_close_never_steals_foreground_from_other_application(self):
        import DearUIQt.backends.native_windows as native_windows
        user32 = self.FakeUser32(foreground=9999, owner=5678, enabled=False)
        original = native_windows._windows_user32
        native_windows._windows_user32 = lambda: user32
        try:
            self.assertFalse(self.backend().handoffOwnerBeforeHide(99))
        finally:
            native_windows._windows_user32 = original
        user32.EnableWindow.assert_not_called()
        user32.BringWindowToTop.assert_not_called()
        user32.SetForegroundWindow.assert_not_called()
        self.assertEqual(user32.foreground, 9999)
