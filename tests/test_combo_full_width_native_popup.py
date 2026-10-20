"""Protect full-width native popup and editable overlay order."""
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "DearUIQt/widgets/combo_box.py").read_text(encoding="utf-8")

def test_native_popup_uses_entire_field_width():
    ctor=SOURCE.split("class ImGuiComboBox:",1)[1].split("# Compatibility names retained",1)[0]
    assert "self.button = dpg.add_combo(" in ctor
    combo=ctor.split("self.button = dpg.add_combo(",1)[1].split("        )",1)[0]
    assert "width=-2" in combo
    assert "no_preview=False" in combo
    assert "popup_align_left=True" in combo
    assert "pos=(1, 1)" in combo
    assert "dpg.add_window(" not in ctor

def test_editor_is_drawn_after_combo_but_excludes_arrow():
    ctor=SOURCE.split("class ImGuiComboBox:",1)[1].split("# Compatibility names retained",1)[0]
    assert ctor.index("self.button = dpg.add_combo(") < ctor.index("self.input = dpg.add_input_text(")
    assert "width=-editor_right_reserve" in ctor
    assert "parent=self.shell" in ctor
    assert "pos=(1, 1)" in ctor

def test_no_separate_popup_window_and_wrapper_copies_match():
    root=Path(__file__).resolve().parents[1]
    assert (root/"DearUIQt/widgets/combo_box.py").read_bytes() == (root/"WinUx/DearUIQt/widgets/combo_box.py").read_bytes()
    assert "self._popup = dpg.add_window(" not in SOURCE
