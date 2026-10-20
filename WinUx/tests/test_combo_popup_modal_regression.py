"""Protect modal combo hit-testing from accidental floating popup regressions."""
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'DearUIQt/widgets/combo_box.py'


def test_combo_uses_native_modal_safe_popup_owner():
    source = SOURCE.read_text(encoding='utf-8')
    constructor = source.split('class ImGuiComboBox:', 1)[1].split('def _native_value_for', 1)[0]
    assert 'self.button = dpg.add_combo(' in constructor
    assert 'no_preview=True' in constructor
    assert 'parent=self._row' in constructor
    assert 'width=self.ARROW_WIDTH' in constructor
    assert 'self._popup = dpg.add_window(' not in constructor
    assert 'label="▾"' not in constructor


def test_combo_editor_remains_independent_of_dropdown_hitbox():
    source = SOURCE.read_text(encoding='utf-8')
    constructor = source.split('class ImGuiComboBox:', 1)[1].split('def _native_value_for', 1)[0]
    assert constructor.index('self.input = dpg.add_input_text(') < constructor.index('self.button = dpg.add_combo(')
    assert 'width=-editor_right_reserve' in constructor
    assert 'callback=self._native_selected' in constructor
