"""Shared dialog initial focus must not interrupt pointer activation."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from DearUIQt.dialogs.qt_dialog import QtDialog


class DialogPointerFocusTests(unittest.TestCase):
    def setUp(self):
        self.backend = SimpleNamespace(
            is_item_shown=lambda tag: True,
            is_mouse_button_down=Mock(return_value=False),
            get_focused_item=Mock(return_value=99),
            get_item_state=Mock(return_value={"active": False}),
            focus_item=Mock(), mvMouseButton_Left=0, mvMouseButton_Right=1,
            mvMouseButton_Middle=2)
        self.dialog = SimpleNamespace(
            tag=1, winfo_exists=lambda: True, _initial_focus_item=2,
            _focus_order=[2, 3], _default_button=3,
            _item_belongs_to=lambda tag, parent: tag in (1, 2, 3),
            _item_is_focusable=lambda tag: True)

    def test_mouse_down_keeps_first_click_instead_of_queuing_editor_focus(self):
        self.backend.is_mouse_button_down.side_effect = lambda button: button == 0
        with patch("DearUIQt.dialogs.qt_dialog.dpg", self.backend):
            self.assertFalse(QtDialog._focus_initial(self.dialog))
        self.backend.focus_item.assert_not_called()

    def test_active_child_keeps_mouse_caret_or_button_activation(self):
        self.backend.get_focused_item.return_value = 2
        self.backend.get_item_state.return_value = {"active": True}
        with patch("DearUIQt.dialogs.qt_dialog.dpg", self.backend):
            self.assertFalse(QtDialog._focus_initial(self.dialog))
        self.backend.focus_item.assert_not_called()

    def test_first_pointer_focus_does_not_get_overwritten_when_child_is_not_active(self):
        # Native button focus can persist after mouse-up with active=False.
        self.backend.get_focused_item.return_value = 3
        self.backend.get_item_state.return_value = {"active": False}
        with patch("DearUIQt.dialogs.qt_dialog.dpg", self.backend):
            self.assertFalse(QtDialog._focus_initial(self.dialog))
        self.backend.focus_item.assert_not_called()

    def test_first_physical_press_survives_stale_dpg_mouse_state(self):
        self.backend.is_mouse_button_down.return_value = False
        with patch("DearUIQt.dialogs.qt_dialog.dpg", self.backend), \
                patch("DearUIQt.dialogs.qt_dialog._mouse_button_down", return_value=True, create=True):
            self.assertFalse(QtDialog._focus_initial(self.dialog))
        self.backend.focus_item.assert_not_called()

    def test_idle_dialog_still_receives_initial_keyboard_focus(self):
        with patch("DearUIQt.dialogs.qt_dialog.dpg", self.backend):
            self.assertTrue(QtDialog._focus_initial(self.dialog))
        self.backend.focus_item.assert_called_once_with(2)

    def test_hidden_or_destroyed_dialog_cannot_take_focus(self):
        self.dialog.winfo_exists = lambda: False
        with patch("DearUIQt.dialogs.qt_dialog.dpg", self.backend):
            self.assertFalse(QtDialog._focus_initial(self.dialog))
        self.backend.focus_item.assert_not_called()


if __name__ == "__main__":
    unittest.main()
