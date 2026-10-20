"""Regression: editable combo dropdown must be created after dialog content."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "DearUIQt/widgets/combo_box.py"


def test_constructor_does_not_create_popup_before_later_form_controls():
    source = SOURCE.read_text(encoding="utf-8")
    constructor = source.split("class ImGuiComboBox:", 1)[1].split(
        "# ------------------------------------------------------------------ API", 1)[0]
    assert "self._popup = None" in constructor
    assert "dpg.add_child_window(" not in constructor.split("self._popup = None", 1)[1]


def test_first_open_creates_embedded_popup_and_moves_it_to_render_tail():
    source = SOURCE.read_text(encoding="utf-8")
    ensure = source.split("def _ensure_popup", 1)[1].split("def _raise_popup", 1)[0]
    raise_block = source.split("def _raise_popup", 1)[1].split(
        "def _desired_popup_geometry", 1)[0]
    opener = source.split("def open_popup", 1)[1].split("showPopup = open_popup", 1)[0]
    assert "dpg.add_child_window(" in ensure
    assert "parent=self._popup_host" in ensure
    assert "dpg.move_item(self._popup, parent=self._popup_host)" in raise_block
    assert opener.index("self._ensure_popup()") < opener.index("self._raise_popup()")
    assert opener.index("self._raise_popup()") < opener.index("dpg.configure_item(self._popup, show=True)")


def test_popup_geometry_still_uses_full_combobox_width_and_bottom_edge():
    source = SOURCE.read_text(encoding="utf-8")
    geometry = source.split("def _desired_popup_geometry", 1)[1].split(
        "def _initial_popup_local_pos", 1)[0]
    assert "left, top = dpg.get_item_rect_min(self.shell)" in geometry
    assert "width, height = dpg.get_item_rect_size(self.shell)" in geometry
    assert "shell_bottom = int(round(top + height))" in geometry
    assert "return int(round(left)), shell_bottom, width" in geometry


def test_arrow_uses_native_imgui_geometry_not_font_glyph():
    source = SOURCE.read_text(encoding="utf-8")
    constructor = source.split("class ImGuiComboBox:", 1)[1].split(
        "# ------------------------------------------------------------------ API", 1)[0]
    assert "arrow=True" in constructor
    assert "direction=dpg.mvDir_Down" in constructor
    for bad in ('label="v"', 'label="▾"', 'label="▼"'):
        assert bad not in constructor
