"""Dialogs must be centered before their first visible native frame."""
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from DearUIQt.dialogs.qt_dialog import QtDialog


class PreShowCenteringTests(unittest.TestCase):
    def test_prepared_dialog_does_not_queue_visible_reposition(self):
        view = SimpleNamespace(after_render=Mock())
        dialog = SimpleNamespace(modal=True, _native_window_backend=Mock(),
                                 _native_center_prepared=True, view=view)
        QtDialog._schedule_native_modal_center(dialog)
        view.after_render.assert_not_called()

    def test_already_queued_callback_cannot_move_prepared_dialog(self):
        backend = Mock()
        dialog = SimpleNamespace(_native_center_prepared=True,
                                 _native_window_backend=backend)
        QtDialog._center_native_modal_once(dialog, 2)
        backend.centerOverOwner.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32", "Requires the native Win32 renderer")
    def test_first_show_nested_and_reopen_have_no_frame_position_jump(self):
        from tools.check_dialog_first_show import main
        main()


if __name__ == "__main__":
    unittest.main()
