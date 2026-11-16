"""Shared editor/combo corner contract across normal/focus/disabled themes."""
from contextlib import contextmanager
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.gui import style
from DearUIQt.dialogs import theme as dialogs
from DearUIQt.widgets import combo_box
from DearUIQt.widgets.combo_field import ComboField


class Backend:
    def __init__(self):
        self.styles, self.colors = [], []
        self.component = None

    def __getattr__(self, name):
        if name.startswith('mv'):
            return name
        raise AttributeError(name)

    def does_item_exist(self, tag):
        return False

    @contextmanager
    def theme(self, **kwargs):
        yield 'theme'

    @contextmanager
    def theme_component(self, component, **kwargs):
        previous = self.component
        self.component = component
        yield component
        self.component = previous

    def add_theme_style(self, role, *values, **kwargs):
        self.styles.append((self.component, role, values))

    def add_theme_color(self, role, value, **kwargs):
        self.colors.append((self.component, role, value))


class RoundedControls(unittest.TestCase):
    def assert_radius(self, backend, component, role='mvStyleVar_FrameRounding', radius=5):
        self.assertIn((component, role, (radius,)), backend.styles)

    def test_line_edit_and_application_states(self):
        self.assertEqual(style.METRICS.frame_rounding, style.METRICS.button_rounding)
        for state in ({}, {'focused': True}, {'disabled': True}):
            backend = Backend()
            style.line_edit_theme(backend, **state)
            self.assert_radius(backend, 'mvInputText')
        backend = Backend()
        style.application_theme(backend)
        for component in ('mvInputText', 'mvCombo'):
            self.assertEqual(backend.styles.count((component, 'mvStyleVar_FrameRounding', (5,))), 2)

    def test_dialog_controls_and_multiline(self):
        for factory, component, role in (
                (dialogs.line_edit_theme, 'mvInputText', 'mvStyleVar_FrameRounding'),
                (dialogs.combo_theme, 'mvCombo', 'mvStyleVar_FrameRounding'),
                (dialogs.line_edit_shell_theme, 'mvChildWindow', 'mvStyleVar_ChildRounding')):
            for state in ({}, {'focused': True}, {'disabled': True}):
                backend = Backend()
                with patch.object(dialogs, 'dpg', backend), patch.object(dialogs, '_is_theme', return_value=False):
                    factory(**state)
                self.assert_radius(backend, component, role)
        backend = Backend()
        with patch.object(dialogs, 'dpg', backend), patch.object(dialogs, '_is_theme', return_value=False):
            dialogs.plain_text_edit_theme()
        self.assert_radius(backend, 'mvInputText')

    def test_native_combo_shell_and_transparent_editor(self):
        for state in ({}, {'focused': True}, {'disabled': True}):
            backend = Backend()
            with patch.object(combo_box, 'dpg', backend):
                combo_box._shell_theme(**state)
                combo_box._input_theme(disabled=state.get('disabled', False))
                combo_box._combo_theme(disabled=state.get('disabled', False))
            self.assert_radius(backend, 'mvChildWindow', 'mvStyleVar_ChildRounding')
            self.assert_radius(backend, 'mvCombo', radius=4)
            self.assertIn(('mvInputText', 'mvThemeCol_FrameBg', (0, 0, 0, 0)), backend.colors)

    def test_retained_combo_shell_and_transparent_preview(self):
        for editable in (False, True):
            for disabled, focused in ((False, False), (False, True), (True, False)):
                backend = Backend()
                field = ComboField.__new__(ComboField)
                field.backend, field.editable = backend, editable
                field._themes, field._popup_visible = {}, False
                field._theme(disabled, focused, False)
                self.assert_radius(backend, 'mvAll', 'mvStyleVar_ChildRounding')
                component = 'mvInputText' if editable else 'mvButton'
                role = 'mvThemeCol_FrameBg' if editable else 'mvThemeCol_Button'
                self.assertIn((component, role, (0, 0, 0, 0)), backend.colors)


if __name__ == '__main__':
    unittest.main(verbosity=2)
