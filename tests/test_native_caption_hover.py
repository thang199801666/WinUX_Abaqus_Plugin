"""Native caption leaves must not flash Close or leave it stuck hot."""
import ctypes
import unittest
from ctypes import wintypes
from unittest.mock import Mock

from DearUIQt.backends.native_caption import NativeCaptionHoverGuard, _TrackMouseEvent


class NativeCaptionHoverTests(unittest.TestCase):
    def setUp(self):
        self.user32 = Mock()
        self.user32.GetCursorPos.side_effect = self._cursor
        self.user32.GetForegroundWindow.return_value = 123
        self.user32.IsWindowEnabled.return_value = True
        self.user32.WindowFromPoint.return_value = 123
        self.user32.SendMessageW.return_value = 20
        self.user32.TrackMouseEvent.return_value = True
        self.guard = NativeCaptionHoverGuard(self.user32)
        self.guard.suppress(123, 0x00A0, 20)

    @staticmethod
    def _cursor(pointer):
        point = ctypes.cast(pointer, ctypes.POINTER(wintypes.POINT)).contents
        point.x, point.y = -25, -10
        return True

    def test_stale_leave_is_suppressed_and_tracking_rearmed(self):
        for _ in range(3):
            self.assertTrue(self.guard.suppress(123, 0x02A2, 0))
        track = ctypes.cast(self.user32.TrackMouseEvent.call_args.args[0],
                            ctypes.POINTER(_TrackMouseEvent)).contents
        self.assertEqual(track.dwFlags, 0x12)
        self.assertEqual(track.hwndTrack, 123)
        self.assertEqual(self.user32.TrackMouseEvent.call_count, 3)
        self.user32.SendMessageW.assert_called_with(
            123, 0x0084, 0, ((-25 & 0xffff) | ((-10 & 0xffff) << 16)))

    def test_real_departure_is_forwarded_after_stale_leave(self):
        self.assertTrue(self.guard.suppress(123, 0x02A2, 0))
        self.user32.SendMessageW.return_value = 2  # HTCAPTION
        self.assertFalse(self.guard.suppress(123, 0x02A2, 0))
        self.assertFalse(self.guard._close_hover)

    def test_inactive_disabled_or_covered_window_does_not_suppress_leave(self):
        for function, value in (("GetForegroundWindow", 456),
                                ("IsWindowEnabled", False),
                                ("WindowFromPoint", 456)):
            with self.subTest(function=function):
                self.setUp()
                getattr(self.user32, function).return_value = value
                self.assertFalse(self.guard.suppress(123, 0x02A2, 0))
                self.user32.TrackMouseEvent.assert_not_called()

    def test_native_failures_do_not_swallow_leave(self):
        for function in ("GetCursorPos", "SendMessageW", "TrackMouseEvent"):
            with self.subTest(function=function):
                self.setUp()
                getattr(self.user32, function).side_effect = OSError("unavailable")
                self.assertFalse(self.guard.suppress(123, 0x02A2, 0))

    def test_failed_tracking_does_not_swallow_leave(self):
        self.user32.TrackMouseEvent.return_value = False
        self.assertFalse(self.guard.suppress(123, 0x02A2, 0))

    def test_other_caption_controls_are_untouched(self):
        self.guard.suppress(123, 0x00A0, 9)  # HTMAXBUTTON
        self.assertFalse(self.guard.suppress(123, 0x02A2, 0))
        self.assertFalse(self.guard.suppress(123, 0x0010, 0))  # WM_CLOSE
        self.assertFalse(self.guard.suppress(123, 0x00A1, 20))  # WM_NCLBUTTONDOWN
        self.user32.GetCursorPos.assert_not_called()

    def test_stale_nonclient_deactivation_is_suppressed_while_foreground(self):
        self.assertTrue(self.guard.suppress(123, 0x0086, 0))  # WM_NCACTIVATE(FALSE)
        self.assertTrue(self.guard._close_hover)

    def test_real_nonclient_deactivation_is_forwarded_and_clears_hover(self):
        self.user32.GetForegroundWindow.return_value = 456
        self.assertFalse(self.guard.suppress(123, 0x0086, 0))
        self.assertFalse(self.guard._close_hover)

    def test_hide_disable_and_destroy_clear_hover(self):
        for message in (0x0018, 0x000A, 0x0082):
            with self.subTest(message=message):
                self.guard.suppress(123, 0x00A0, 20)
                self.assertFalse(self.guard.suppress(123, message, 0))
                self.assertFalse(self.guard.suppress(123, 0x02A2, 0))


if __name__ == "__main__":
    unittest.main()
