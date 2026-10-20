"""Dialog resize must be available to real forms, not just mocked in tests."""
import unittest
from unittest.mock import Mock, patch

from DearUIQt.core import QSize
from DearUIQt.dialogs.qt_dialog import QtDialog
from WinUx.dialogs.transfer_center_form import TransferCenterDialog


class DialogResizeTests(unittest.TestCase):
    def dialog(self, cls=QtDialog):
        dialog = object.__new__(cls)
        dialog.tag = "resize_dialog"
        dialog.width, dialog.height = 820, 320
        dialog.winfo_exists = Mock(return_value=True)
        dialog.minimumSize = Mock(return_value=QSize(620, 240))
        dialog.updateGeometry = Mock()
        return dialog

    def test_resize_updates_native_and_retained_size(self):
        dialog = self.dialog()
        with patch("DearUIQt.dialogs.qt_dialog.dpg") as backend:
            dialog.resize(840, 400)
            self.assertEqual((dialog.width, dialog.height), (840, 400))
            backend.configure_item.assert_called_once_with(
                dialog.tag, width=840, height=400)
            backend.show_item.assert_not_called()
            backend.set_item_pos.assert_not_called()
        dialog.updateGeometry.assert_called_once_with()

    def test_qsize_overload_respects_minimum(self):
        dialog = self.dialog()
        with patch("DearUIQt.dialogs.qt_dialog.dpg") as backend:
            dialog.resize(QSize(100, 100))
            backend.configure_item.assert_called_once_with(
                dialog.tag, width=620, height=240)

    def test_destroyed_dialog_is_not_resized(self):
        dialog = self.dialog()
        dialog.winfo_exists.return_value = False
        with patch("DearUIQt.dialogs.qt_dialog.dpg") as backend:
            dialog.resize(840, 400)
            backend.configure_item.assert_not_called()
        dialog.updateGeometry.assert_not_called()

    def test_transfer_center_show_uses_real_resize(self):
        dialog = self.dialog(TransferCenterDialog)
        dialog._visible_state = False
        dialog._target_window_height = Mock(return_value=260)
        dialog._center_over_winux = Mock()
        dialog._schedule_window_balance = Mock()
        with patch("DearUIQt.dialogs.qt_dialog.dpg") as backend, \
                patch.object(QtDialog, "show", return_value=True):
            self.assertTrue(dialog.show())
            backend.configure_item.assert_called_once_with(
                dialog.tag, width=820, height=260)
        dialog._center_over_winux.assert_called_once_with()
