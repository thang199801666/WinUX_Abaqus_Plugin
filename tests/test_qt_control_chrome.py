"""Fusion control styling must not change hit targets or inherit fuzzy edges."""
import unittest
from unittest.mock import MagicMock, call, patch

from DearUIQt.gui import style
from DearUIQt.gui.palette import QtFusionPalette as P
from DearUIQt.dialogs import theme as dialog_theme


class ControlChromeTests(unittest.TestCase):
    def backend(self):
        backend = MagicMock()
        backend.does_item_exist.return_value = False
        return backend

    def test_shared_widget_themes_explicitly_remove_border_shadows(self):
        for factory in (style.button_theme, style.line_edit_theme, style.checkbox_theme,
                        style.spin_shell_theme, style.spin_button_theme, style.tab_widget_theme):
            with self.subTest(factory=factory.__name__):
                b = self.backend()
                factory(b)
                self.assertIn(call(b.mvThemeCol_BorderShadow, (0, 0, 0, 0)),
                              b.add_theme_color.call_args_list)

    def test_default_button_keeps_blue_outline_and_neutral_surface(self):
        b = self.backend()
        style.button_theme(b, default=True)
        self.assertIn(call(b.mvThemeCol_Border, P.FOCUS), b.add_theme_color.call_args_list)
        self.assertIn(call(b.mvThemeCol_ButtonActive, (225, 225, 225, 255)),
                      b.add_theme_color.call_args_list)
        self.assertIn(call(b.mvStyleVar_FrameRounding, style.METRICS.button_rounding),
                      b.add_theme_style.call_args_list)


    def test_tool_and_command_buttons_share_win11_rounding(self):
        for factory in (style.tool_button_theme, style.command_button_theme):
            with self.subTest(factory=factory.__name__):
                b = self.backend()
                factory(b)
                self.assertIn(
                    call(b.mvStyleVar_FrameRounding, style.METRICS.button_rounding),
                    b.add_theme_style.call_args_list,
                )

    def test_disabled_button_is_not_painted_as_active_default(self):
        b = self.backend()
        style.button_theme(b, disabled=True, default=True, focused=True)
        self.assertIn(call(b.mvThemeCol_Border, P.BORDER_LIGHT), b.add_theme_color.call_args_list)
        self.assertIn(call(b.mvThemeCol_Text, P.TEXT_DISABLED), b.add_theme_color.call_args_list)

    def test_disabled_button_keeps_win11_rounding_component(self):
        for factory in (style.button_theme, style.tool_button_theme, style.command_button_theme):
            with self.subTest(factory=factory.__name__):
                b = self.backend()
                factory(b, disabled=True)
                self.assertTrue(any(
                    args and args[0] in (b.mvButton, b.mvImageButton)
                    and kwargs.get("enabled_state") is False
                    for args, kwargs in b.theme_component.call_args_list
                ))
                self.assertIn(
                    call(b.mvStyleVar_FrameRounding, style.METRICS.button_rounding),
                    b.add_theme_style.call_args_list,
                )

    def test_application_theme_pins_button_rounding_in_both_enabled_states(self):
        b = self.backend()
        style.application_theme(b)
        button_states = [
            kwargs.get("enabled_state")
            for args, kwargs in b.theme_component.call_args_list
            if args and args[0] == b.mvButton and "enabled_state" in kwargs
        ]
        self.assertIn(True, button_states)
        self.assertIn(False, button_states)

    def test_checked_checkbox_uses_dark_mark_on_light_face(self):
        for focused in (False, True):
            b = self.backend()
            style.checkbox_theme(b, checked=True, focused=focused)
            self.assertIn(call(b.mvThemeCol_CheckMark, P.TEXT), b.add_theme_color.call_args_list)
            self.assertIn(call(b.mvThemeCol_FrameBg, P.BASE), b.add_theme_color.call_args_list)
            self.assertIn(call(b.mvThemeCol_Border, P.FOCUS if focused else P.BORDER),
                          b.add_theme_color.call_args_list)

    def test_spin_subcontrol_has_neutral_button_face_and_square_shell(self):
        b = self.backend()
        style.spin_button_theme(b)
        self.assertIn(call(b.mvThemeCol_Button, P.BUTTON), b.add_theme_color.call_args_list)
        style.spin_shell_theme(b)
        self.assertIn(call(b.mvStyleVar_ChildRounding, 0), b.add_theme_style.call_args_list)

    def test_tab_theme_uses_native_tab_styles_not_just_frame_styles(self):
        b = self.backend()
        style.tab_widget_theme(b)
        self.assertIn(call(b.mvStyleVar_TabRounding, 0), b.add_theme_style.call_args_list)
        self.assertIn(call(b.mvStyleVar_TabBorderSize, 1), b.add_theme_style.call_args_list)

    def test_dialog_line_edit_shell_is_crisp_in_all_states(self):
        b = self.backend()
        with patch.object(dialog_theme, "dpg", b), patch.object(dialog_theme, "_is_theme", return_value=False), \
                patch.multiple(dialog_theme, _LINE_EDIT_SHELL_THEME=None,
                               _LINE_EDIT_SHELL_FOCUS_THEME=None, _LINE_EDIT_SHELL_DISABLED_THEME=None):
            for options in ({}, {"focused": True}, {"disabled": True}):
                dialog_theme.line_edit_shell_theme(**options)
        self.assertEqual(b.add_theme_color.call_args_list.count(
            call(b.mvThemeCol_BorderShadow, (0, 0, 0, 0))), 3)
        self.assertEqual(b.add_theme_style.call_args_list.count(
            call(b.mvStyleVar_ChildRounding, 0)), 3)
