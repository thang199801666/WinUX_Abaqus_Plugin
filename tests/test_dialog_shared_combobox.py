"""All dialog factories share the new combo without changing callback contracts."""
from pathlib import PurePosixPath
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from DearUIQt.core import QEvent, QKeyEvent, Qt
from DearUIQt.dialogs.combo_callbacks import adapt_combo_callback
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.widgets import QComboBox
from tests.test_dearuiqt_widgets_r77 import FakeBackend


class ComboCallbackTests(unittest.TestCase):
    def test_zero_one_two_three_and_variadic_callbacks(self):
        seen = []
        callbacks = [lambda: seen.append(()), lambda sender: seen.append((sender,)),
                     lambda sender, value: seen.append((sender, value)),
                     lambda sender, value, data: seen.append((sender, value, data)),
                     lambda *args: seen.append(args)]
        data = PurePosixPath("/jobs/example.inp")
        for callback in callbacks:
            adapt_combo_callback(callback, data)("internal_editor", "Run After", SimpleNamespace(tag="combo"))
        self.assertEqual(seen, [(), ("combo",), ("combo", "Run After"),
                               ("combo", "Run After", data), ("combo", "Run After", data)])

    def test_optional_capture_is_not_overwritten(self):
        seen = []
        def callback(sender, value, data, capture="kept"):
            seen.append(capture)
        adapt_combo_callback(callback)(None, "value", SimpleNamespace(tag=1))
        self.assertEqual(seen, ["kept"])

    def test_callback_error_propagates_without_retry(self):
        callback = Mock(side_effect=TypeError("callback body failed"))
        with self.assertRaisesRegex(TypeError, "callback body failed"):
            adapt_combo_callback(callback)(None, "value", SimpleNamespace(tag=1))
        callback.assert_called_once()


class DialogComboFactoryTests(unittest.TestCase):
    def test_factory_retains_tag_state_userdata_and_focus_mapping(self):
        dialog = object.__new__(QtDialog)
        dialog.tag, dialog.view = "dialog", SimpleNamespace(after=Mock())
        dialog._control_wrappers, dialog._focus_order = {}, []
        dialog._qt_parent = lambda parent: parent
        dialog.own_widget = lambda widget: widget
        widget = Mock(tag="shell", _choice_field=SimpleNamespace(button="focus_item"))
        seen = []
        data = object()
        with patch("DearUIQt.dialogs.qt_dialog.QComboBox", return_value=widget) as create, \
                patch("DearUIQt.dialogs.qt_dialog.get_backend", return_value="backend"), \
                patch("DearUIQt.dialogs.qt_dialog.dpg"):
            tag = dialog.combo(["Now", "Run After"], parent="cell", default_value="Now",
                               callback=lambda sender, value, payload: seen.append((sender, value, payload)),
                               user_data=data, enabled=False, show=False, width=180)
        self.assertEqual(tag, "shell")
        self.assertIs(dialog.control_wrapper(tag), widget)
        self.assertIs(dialog.control_wrapper("focus_item"), widget)
        self.assertEqual(dialog._focus_order, ["focus_item"])
        widget.setEnabled.assert_called_once_with(False)
        widget.hide.assert_called_once_with()
        widget.setPopupParent.assert_called_once_with("dialog")
        options = create.call_args.kwargs
        self.assertFalse(options["editable"])
        self.assertEqual(options["current"], "Now")
        options["callback"]("focus_item", "Run After", widget)
        self.assertEqual(seen, [("shell", "Run After", data)])

    def test_modal_dialog_forwards_keys_to_its_focused_combo(self):
        dialog = object.__new__(QtDialog)
        combo = QComboBox(["a", "b"], backend=FakeBackend())
        combo._choice_field = Mock()
        combo._choice_key_event = Mock(return_value=True)
        dialog._accepts_dialog_keys = lambda: True
        dialog.focusWidget = lambda: combo
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_F4)
        self.assertTrue(dialog._handle_key_event(event))
        combo._choice_key_event.assert_called_once_with(event)

    def test_active_editor_uses_retained_focus_when_native_nav_reports_a_container(self):
        dialog = object.__new__(QtDialog)
        combo = QComboBox(["saved"], backend=FakeBackend())
        combo._choice_field = Mock()
        combo._choice_field.hasFocus.return_value = True
        combo._choice_key_event = Mock(return_value=True)
        dialog._control_wrappers = {combo.tag: combo}
        dialog._accepts_dialog_keys = lambda: True
        dialog.focusWidget = lambda: None
        application = SimpleNamespace(focusObject=lambda: SimpleNamespace(parent=combo))
        with patch("DearUIQt.core.application.QApplication.instance", return_value=application):
            self.assertTrue(dialog._handle_key_event(QKeyEvent(QEvent.KeyPress, Qt.Key_F4)))
        combo._choice_key_event.assert_called_once()

    def test_confirming_popup_does_not_also_invoke_default(self):
        dialog = object.__new__(QtDialog)
        combo = QComboBox(["a", "b"], backend=FakeBackend())
        combo.popupVisible = Mock(return_value=False)
        combo._choice_popup_closed_frame = 7
        dialog._control_wrappers = {combo.tag: combo}
        dialog.enter_editors, dialog.active_table = set(), None
        dialog._default, dialog._default_button = Mock(), "default"
        dialog._item_is_focusable = lambda item: True
        with patch("DearUIQt.dialogs.qt_dialog.dpg") as backend:
            backend.get_frame_count.return_value = 7
            backend.get_focused_item.return_value = None
            dialog.invoke_default()
            dialog._default.assert_not_called()
            backend.get_frame_count.return_value = 8
            dialog.invoke_default()
            dialog._default.assert_called_once_with()

    def test_hidden_composite_combo_is_not_a_tab_stop(self):
        dialog = object.__new__(QtDialog)
        combo = QComboBox(["a", "b"], backend=FakeBackend())
        dialog._control_wrappers = {"inner_button": combo}
        combo.hide()
        with patch("DearUIQt.dialogs.qt_dialog.dpg") as backend:
            backend.does_item_exist.return_value = True
            backend.is_item_shown.return_value = True
            self.assertFalse(dialog._item_is_focusable("inner_button"))
        self.assertFalse(combo._handle_choice_key(Qt.Key_Down))

    def test_standalone_default_handler_opens_focused_fixed_choices_instead_of_running(self):
        dialog = object.__new__(QtDialog)
        combo = QComboBox(["a", "b"], backend=FakeBackend())
        combo._choice_field = Mock()
        combo.showPopup = Mock()
        dialog._control_wrappers = {combo.tag: combo}
        dialog.focusWidget = lambda: combo
        dialog._default = Mock()
        with patch("DearUIQt.dialogs.qt_dialog.dpg") as backend:
            backend.get_frame_count.return_value = 7
            dialog.invoke_default()
        combo.showPopup.assert_called_once_with()
        dialog._default.assert_not_called()
