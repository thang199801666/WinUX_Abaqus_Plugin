"""Qt choice semantics independently of native popup rendering."""
import unittest
from pathlib import Path
from unittest.mock import Mock

from DearUIQt.core import Qt
from DearUIQt.widgets import QComboBox
from DearUIQt.widgets.combo_popup import ComboPopup
from tests.test_dearuiqt_widgets_r77 import FakeBackend


class ComboChoiceTests(unittest.TestCase):
    def editable_combo(self):
        combo = self.combo()
        combo._editable = True
        combo._choice_field.button = combo.tag
        combo._choice_field.setText.side_effect = lambda text: combo.backend.set_value(combo.tag, text)
        return combo

    def test_editable_text_accepts_values_outside_history(self):
        combo = self.editable_combo()
        self.assertTrue(combo.setCurrentText("new-server"))
        self.assertEqual(combo.currentText(), "new-server")
        self.assertEqual(combo.currentIndex(), -1)

    def test_editable_enter_and_text_navigation_belong_to_the_form_editor(self):
        combo = self.editable_combo()
        for key in (Qt.Key_Return, Qt.Key_Space, Qt.Key_Home, Qt.Key_End):
            self.assertFalse(combo._handle_choice_key(key))

    def test_typing_emits_edit_signals_and_login_callback_once(self):
        combo = self.editable_combo()
        edited, changed, activated = [], [], []
        combo.editTextChanged.connect(edited.append)
        combo.currentTextChanged.connect(changed.append)
        combo.activated.connect(activated.append)
        callback = combo._external_callback = Mock()
        combo.backend.set_value(combo.tag, "typed-host")
        combo._choice_edited(combo.tag, "typed-host")
        combo._choice_edited(combo.tag, "typed-host")
        self.assertEqual(edited, ["typed-host"])
        self.assertEqual(changed, ["typed-host"])
        self.assertEqual(activated, [])
        callback.assert_called_once_with(combo.tag, "typed-host", combo)

    def test_bundled_combo_components_match_the_canonical_package(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("combo_box.py", "combo_field.py", "combo_popup.py"):
            self.assertEqual((root / "DearUIQt/widgets" / name).read_bytes(),
                             (root / "WinUx/DearUIQt/widgets" / name).read_bytes())

    def combo(self):
        combo = QComboBox(["Entity", "Integer", "Player"], backend=FakeBackend())
        combo._choice_field = Mock()
        combo._choice_popup = Mock()
        combo._choice_popup.isVisible.return_value = False
        return combo

    def test_programmatic_change_emits_change_but_not_activation(self):
        combo = self.combo()
        changed, activated = [], []
        combo.currentIndexChanged.connect(changed.append)
        combo.activated.connect(activated.append)
        combo.setCurrentIndex(1)
        combo.setCurrentIndex(1)
        self.assertEqual(changed, [1])
        self.assertEqual(activated, [])

    def test_user_can_activate_current_choice_without_duplicate_change(self):
        combo = self.combo()
        changed, activated = [], []
        combo.currentIndexChanged.connect(changed.append)
        combo.activated.connect(activated.append)
        combo._choice_activated("0")
        self.assertEqual(changed, [])
        self.assertEqual(activated, [0])
        combo._choice_popup.hide.assert_called_once_with()

    def test_closed_keyboard_changes_selection_and_stops_at_edges(self):
        combo = self.combo()
        combo._handle_choice_key(Qt.Key_Down)
        self.assertEqual(combo.currentIndex(), 1)
        combo._handle_choice_key(Qt.Key_End)
        combo._handle_choice_key(Qt.Key_Down)
        self.assertEqual(combo.currentIndex(), 2)
        combo._handle_choice_key(Qt.Key_Home)
        combo._handle_choice_key(Qt.Key_Up)
        self.assertEqual(combo.currentIndex(), 0)

    def test_native_backend_key_codes_are_accepted(self):
        combo = self.combo()
        combo._handle_choice_key(combo.backend.mvKey_Down)
        self.assertEqual(combo.currentIndex(), 1)

    def test_disable_closes_popup_and_prevents_keyboard_changes(self):
        combo = self.combo()
        combo.setEnabled(False)
        combo._choice_popup.hide.assert_called_once_with()
        self.assertFalse(combo._handle_choice_key(Qt.Key_Down))
        self.assertEqual(combo.currentIndex(), 0)

    def test_popup_navigation_highlights_without_wrapping(self):
        popup = object.__new__(ComboPopup)
        popup._active_action = "0"
        popup._visible_action_ids = lambda: ["0", "1", "2"]
        popup.selectRow = Mock()
        popup.navigate("up")
        popup.selectRow.assert_called_with(0)
        popup.navigate("end")
        popup.selectRow.assert_called_with(2)

    def test_invalid_initial_value_falls_back_to_first_choice(self):
        combo = QComboBox(["A", "B"], current="missing", backend=FakeBackend())
        self.assertEqual(combo.currentText(), "A")

    def test_popup_row_limit_controls_real_geometry_and_scrolling(self):
        popup = object.__new__(ComboPopup)
        popup.backend = Mock()
        popup.tag = "popup"
        popup.setActions = Mock()
        popup.configureChoices(["a"] * 20, 250, 5)
        config = popup.backend.configure_item.call_args.kwargs
        self.assertEqual(config["width"], 250)
        self.assertEqual(config["height"], 5 * popup.ROW_HEIGHT + 2)
        self.assertFalse(config["no_scrollbar"])
