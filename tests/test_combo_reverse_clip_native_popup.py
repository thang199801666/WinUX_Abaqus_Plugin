"""Regression for editable full-width native combo popup with editor-only clipping."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "DearUIQt" / "widgets" / "combo_box.py"


def source():
    return SRC.read_text(encoding="utf-8")


def constructor():
    text = source().split("class ImGuiComboBox:", 1)[1]
    return text.split("# ------------------------------------------------------------------ API", 1)[0]


def test_native_combo_owns_full_shell_width_and_popup():
    block = constructor()
    combo = block.split("self.button = dpg.add_combo(", 1)[1].split("\n        )", 1)[0]
    assert "parent=self.shell" in combo
    assert "pos=(1, 1)" in combo
    assert "width=-2" in combo
    assert "no_preview=False" in combo
    assert "popup_align_left=True" in combo
    assert "fit_width=False" in combo


def test_only_editor_is_clipped_before_native_arrow_strip():
    block = constructor()
    assert "self._editor_clip = dpg.add_child_window(" in block
    clip = block.split("self._editor_clip = dpg.add_child_window(", 1)[1].split("\n        )", 1)[0]
    assert "parent=self.shell" in clip
    assert "pos=(1, 1)" in clip
    assert "width=-self._editor_right_reserve" in clip
    inp = block.split("self.input = dpg.add_input_text(", 1)[1].split("\n        )", 1)[0]
    assert "parent=self._editor_clip" in inp
    assert "width=-1" in inp
    assert block.index("self.button = dpg.add_combo(") < block.index("self._editor_clip = dpg.add_child_window(")


def test_no_custom_popup_or_arrow_glyph_is_used():
    text = source()
    editable = text.split("class ImGuiComboBox:", 1)[1].split("class QComboBox", 1)[0]
    assert "dpg.add_window(" not in editable
    assert "popup=True" not in editable
    assert "arrow=True" not in editable
    assert "label=\"▾\"" not in editable
    assert "self.listbox = self.button" in editable


def test_selection_is_mirrored_back_into_editable_input():
    text = source()
    selected = text.split("def _native_selected", 1)[1].split("# -------------------------------------------------------------- behavior", 1)[0]
    assert "self.set_current_text(value, emit=True)" in selected
    assert "dpg.set_value(self.button, \"\")" in selected
