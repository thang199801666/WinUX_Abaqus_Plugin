"""Regression for editable native combo click ownership and duplicated package copies."""
from pathlib import Path


def test_native_combo_has_separate_arrow_hit_area():
    root = Path(__file__).resolve().parents[1]
    source = (root / "DearUIQt/widgets/combo_box.py").read_text(encoding="utf-8")
    constructor = source.split("class ImGuiComboBox:", 1)[1].split("def _native_value_for", 1)[0]
    assert "parent=self._row" in constructor
    assert "width=self.ARROW_WIDTH" in constructor
    assert "no_preview=True" in constructor
    assert constructor.index("self.input = dpg.add_input_text(") < constructor.index("self.button = dpg.add_combo(")
    assert "pos=(0, 0)" not in constructor.split("self.button = dpg.add_combo(", 1)[1].split("dpg.bind_item_theme(self.button", 1)[0]


def test_duplicate_wrapper_copies_have_same_bytes():
    root = Path(__file__).resolve().parents[1]
    canonical = root / "DearUIQt/widgets/combo_box.py"
    bundled = root / "WinUx/DearUIQt/widgets/combo_box.py"
    assert canonical.read_bytes() == bundled.read_bytes()
