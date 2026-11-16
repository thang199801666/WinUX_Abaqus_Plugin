"""WM_NCACTIVATE suppression must not veto native child-dialog activation."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.backends.native_windows import NativeWindowBackend


class NativeDeactivationHandoffTests(unittest.TestCase):
    def setUp(self):
        self.api = SimpleNamespace(
            GetWindowLongPtrW=Mock(return_value=123),
            GetWindowLongW=Mock(return_value=123),
            SetWindowLongPtrW=Mock(return_value=123),
            SetWindowLongW=Mock(return_value=123),
            CallWindowProcW=Mock(return_value=77))
        self.native = NativeWindowBackend(object())
        self.native.require = lambda: None
        self.native._rawWinId = lambda item: 20
        self.guard = Mock()
        self.guard.suppress.return_value = True
        for mocked in (
                patch('DearUIQt.backends.native_windows._windows_user32', return_value=self.api),
                patch('DearUIQt.backends.native_windows.NativeCaptionHoverGuard', return_value=self.guard)):
            mocked.start()
            self.addCleanup(mocked.stop)
        self.assertTrue(self.native.preserveFirstClientClick(1))
        self.proc = self.native._mouse_activate_hooks[20][0]

    def test_suppressed_nonclient_deactivation_allows_focus_handoff(self):
        self.assertEqual(self.proc(20, 0x0086, 0, 0), 1)
        self.api.CallWindowProcW.assert_not_called()

    def test_suppressed_caption_leave_returns_zero(self):
        self.assertEqual(self.proc(20, 0x02A2, 0, 0), 0)
        self.api.CallWindowProcW.assert_not_called()

    def test_real_activation_messages_still_reach_original_proc(self):
        self.guard.suppress.return_value = False
        self.assertEqual(self.proc(20, 0x0086, 0, 0), 77)
        self.api.CallWindowProcW.assert_called_once()


if __name__ == '__main__':
    unittest.main()
