"""Login must use editable Qt combos without losing its form behavior."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from DearUIQt.dialogs.qt_dialog import QtDialog
from WinUx.dialogs.login_form import LoginForm


class LoginQtComboTests(unittest.TestCase):
    def test_history_field_uses_owned_editable_combo_and_native_editor_alias(self):
        form = object.__new__(LoginForm)
        form.tag, form._form = 10, 20
        form.view = SimpleNamespace(after=Mock())
        form._combos, form._control_wrappers = [], {}
        form._focus_order = []
        form._qt_parent = Mock(return_value="editor_owner")
        form.own_widget = lambda widget: widget
        form.form_layout_row = lambda parent, label, create: create(30)
        combo = Mock(tag=40)
        combo.lineEdit.return_value = Mock(tag=50)
        callback = Mock()
        with patch("WinUx.dialogs.login_form.QComboBox", return_value=combo) as create:
            result = form._combo_field("Host:", ["old-host"], "new-host", callback)
        self.assertIs(result, combo)
        create.assert_called_once_with(
            items=["old-host"], current="new-host", width=-1, callback=callback,
            parent="editor_owner", after=form.view.after, editable=True)
        combo.setPopupParent.assert_called_once_with(10)
        combo.lineEdit.return_value.configure.assert_called_once_with(hint="Type or choose from history")
        self.assertIs(form._control_wrappers[50], combo)
        self.assertEqual(form._combos, [combo])
        self.assertEqual(form._focus_order, [50])

    def test_enter_does_not_connect_while_history_is_open(self):
        form = object.__new__(LoginForm)
        combo = Mock()
        form._combos = [combo]
        combo.popupVisible.return_value = True
        with patch.object(QtDialog, "invoke_default") as default:
            form.invoke_default()
            default.assert_not_called()
            combo.popupVisible.return_value = False
            form.invoke_default()
            default.assert_called_once_with()

    def test_cancel_first_closes_history_then_closes_login(self):
        form = object.__new__(LoginForm)
        combo = Mock()
        form._combos, form._busy = [combo], False
        form.destroy = Mock()
        combo.popupVisible.return_value = True
        form.cancel_from_window()
        combo.hidePopup.assert_called_once_with()
        form.destroy.assert_not_called()
        combo.popupVisible.return_value = False
        form.cancel_from_window()
        form.destroy.assert_called_once_with()
