"""Backend and focus contracts that previously prevented dialogs opening."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from DearUIQt.backends import dpg, use_backend
from DearUIQt.dialogs.qt_dialog import QtDialog, _editor_is_active
from DearUIQt.gui import QPainter
from DearUIQt.widgets import QWidget, QtTable


class DialogOpeningRegressionTests(unittest.TestCase):
    def test_legacy_table_export_is_available(self):
        from DearUIQt.dialogs import QtTable as DialogTable
        self.assertIs(QtTable, DialogTable)

    def test_proxy_and_renderer_can_share_widget_ownership(self):
        backend = Mock()
        with use_backend(backend):
            parent = QWidget(tag=1, backend=dpg)
            self.assertIs(parent.backend, backend)
            resolved, options = QWidget._construction(parent, dpg)
            self.assertIs(resolved, backend)
            self.assertEqual(options, {"parent": 1})
            other_backend = Mock()
            with self.assertRaises(ValueError):
                QWidget._construction(parent, other_backend)

    def test_painter_accepts_proxy_for_active_renderer_device(self):
        backend = Mock()
        with use_backend(backend):
            device = SimpleNamespace(backend=backend)
            painter = QPainter(device, backend=dpg)
            self.assertTrue(painter.isActive())
            self.assertIs(painter.device(), device)
            with self.assertRaises(ValueError):
                QPainter(device, backend=Mock())

    def test_focused_container_without_active_state_is_not_an_editor(self):
        backend = SimpleNamespace(
            get_focused_item=lambda: 123, does_item_exist=lambda tag: True,
            get_item_state=lambda tag: {"focused": True})
        with use_backend(backend):
            self.assertFalse(_editor_is_active())
            backend.get_item_state = lambda tag: {"active": True}
            self.assertTrue(_editor_is_active())

    def test_dialog_minimum_size_is_applied_to_native_window(self):
        backend = Mock()
        dialog = object.__new__(QtDialog)
        dialog.tag = 123
        backend.get_item_configuration.return_value = {"min_size": (1100, 680)}
        with use_backend(backend):
            dialog.setMinimumSize(1100, 680)
            backend.configure_item.assert_called_once_with(123, min_size=(1100, 680))
            size = dialog.minimumSize()
            self.assertEqual((size.width(), size.height()), (1100, 680))


if __name__ == "__main__":
    unittest.main()
