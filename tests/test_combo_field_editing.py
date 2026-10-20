"""Editable combo geometry and chrome must not interfere with native editing."""
import unittest
from unittest.mock import MagicMock, Mock, call

from DearUIQt.gui.palette import QtFusionPalette
from DearUIQt.gui.style import METRICS
from DearUIQt.widgets.combo_field import ComboField


class ComboFieldEditingTests(unittest.TestCase):
    def test_field_border_has_square_corners_and_no_inherited_shadow(self):
        field = self.field()
        field.backend = b = MagicMock()
        field._themes = {}
        for editable in (False, True):
            field.editable = editable
            for disabled, focused, hovered in ((False, False, False), (False, True, True),
                                                (True, False, False)):
                field._theme(disabled, focused, hovered)
        self.assertIn(call(b.mvThemeCol_BorderShadow, (0, 0, 0, 0)),
                      b.add_theme_color.call_args_list)
        self.assertIn(call(b.mvStyleVar_ChildRounding, 0), b.add_theme_style.call_args_list)
        self.assertNotIn(call(b.mvStyleVar_ChildRounding, 3), b.add_theme_style.call_args_list)

    def field(self):
        field = object.__new__(ComboField)
        field.backend = Mock()
        field.backend.get_item_rect_size.return_value = (320, 26)
        field.backend.get_item_state.return_value = {}
        field._enabled, field._deleted, field.editable = True, False, True
        field._popup_visible, field._refresh_signature = False, None
        field.tag, field.button, field.arrow = "shell", "editor", "arrow"
        field._arrow_host, field._arrow_bg = "arrow_host", "arrow_bg"
        field._separator, field._chevron = "separator", "triangle"
        field._width, field.height, field._text = 0, 26, "typed-host"
        field._focus_received, field._open = Mock(), Mock()
        field._text_changed = Mock()
        return field

    def test_resize_keeps_editor_and_arrow_hit_regions_separate(self):
        field = self.field()
        field.syncGeometry()
        self.assertIn(call("editor", width=320 - METRICS.arrow_width - 2, height=24),
                      field.backend.configure_item.call_args_list)
        self.assertIn(call("arrow_host", pos=(320 - METRICS.arrow_width - 1, 1),
                           width=METRICS.arrow_width, height=24),
                      field.backend.configure_item.call_args_list)
        self.assertIn(call("arrow", width=METRICS.arrow_width, height=24),
                      field.backend.configure_item.call_args_list)
        field.backend.set_value.assert_not_called()

    def test_editing_updates_text_without_opening_history(self):
        field = self.field()
        field._edited("editor", "new-host")
        self.assertEqual(field._text, "new-host")
        field._text_changed.assert_called_once_with("editor", "new-host", None)
        field._open.assert_not_called()

    def test_focus_targets_native_editor_without_overwriting_text(self):
        field = self.field()
        field.focus()
        field.backend.focus_item.assert_called_once_with("editor")
        field.backend.set_value.assert_not_called()


    def test_refresh_ignores_stale_native_subcontrol_state(self):
        field = self.field()
        field._theme = Mock(return_value="theme")
        field.backend.does_item_exist.return_value = True

        def state(item):
            if item == "arrow":
                raise RuntimeError("Item not found: stale-arrow")
            return {"focused": True} if item == "editor" else {}

        field.backend.get_item_state.side_effect = state
        field._refresh()
        self.assertTrue(field.hasFocus())

    def test_refresh_returns_before_querying_deleted_editor(self):
        field = self.field()
        field.backend.does_item_exist.side_effect = lambda item: item != "editor"
        field._refresh()
        field.backend.get_item_state.assert_not_called()

    def test_popup_keeps_focus_chrome_until_it_closes(self):
        field = self.field()
        field._theme = Mock(return_value="theme")
        field.setPopupVisible(True)
        field._theme.assert_called_with(False, True, False)
        self.assertIn(call("arrow_bg", fill=(225, 225, 225, 255)),
                      field.backend.configure_item.call_args_list)
        field.setPopupVisible(False)
        self.assertIn(call("arrow_bg", fill=QtFusionPalette.BUTTON),
                       field.backend.configure_item.call_args_list)

    def test_fixed_choices_have_neutral_button_surface_not_editor_white(self):
        field = self.field()
        field.editable = False
        self.assertEqual(field._surface(), QtFusionPalette.BUTTON)
        self.assertEqual(field._surface(focused=True), QtFusionPalette.BUTTON)
        self.assertNotEqual(field._surface(hovered=True), QtFusionPalette.BASE)
        field._popup_visible = True
        self.assertEqual(field._surface(), (225, 225, 225, 255))

    def test_editable_preview_stays_white_and_arrow_uses_solid_neutral_ink(self):
        field = self.field()
        field._theme = Mock(return_value="theme")
        field.setPopupVisible(True)
        self.assertEqual(field._surface(focused=True, hovered=True), QtFusionPalette.BASE)
        self.assertIn(call("triangle", color=QtFusionPalette.TEXT, fill=QtFusionPalette.TEXT),
                      field.backend.configure_item.call_args_list)

    def test_resize_centers_solid_triangle_in_existing_arrow_hit_region(self):
        field = self.field()
        field.syncGeometry()
        cx = METRICS.arrow_width / 2
        self.assertIn(call("triangle", p1=(cx - 3.5, 10.5),
                           p2=(cx + 3.5, 10.5), p3=(cx, 14.5)),
                      field.backend.configure_item.call_args_list)
