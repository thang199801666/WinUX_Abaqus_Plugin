"""Regression coverage for the shared DearUIQt editable combo popup."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "DearUIQt" / "widgets" / "combo_box.py"
DUPLICATE = ROOT / "WinUx" / "DearUIQt" / "widgets" / "combo_box.py"


def _source():
    return SOURCE.read_text(encoding="utf-8")


def test_arrow_is_native_geometry_not_a_font_symbol_or_combo_overlay():
    source = _source()
    constructor = source.split("class ImGuiComboBox:", 1)[1].split(
        "# ------------------------------------------------------------------ API", 1)[0]
    assert "self.button = dpg.add_button(" in constructor
    assert "arrow=True" in constructor
    assert "direction=dpg.mvDir_Down" in constructor
    assert "callback=self._arrow_clicked" in constructor
    assert "self.button = dpg.add_combo(" not in constructor
    assert 'label="▾"' not in constructor


def test_dropdown_is_lazy_embedded_in_owner_dialog_and_not_a_detached_window():
    source = _source()
    constructor = source.split("class ImGuiComboBox:", 1)[1].split(
        "# ------------------------------------------------------------------ API", 1)[0]
    ensure = source.split("def _ensure_popup", 1)[1].split(
        "def _raise_popup", 1)[0]
    assert "self._popup_host = self._find_popup_host(self.shell)" in constructor
    assert "self._popup = dpg.add_child_window(" not in constructor
    assert "self._popup = dpg.add_child_window(" in ensure
    assert "parent=self._popup_host" in ensure
    assert "self._popup = dpg.add_window(" not in source
    assert "popup=True" not in source


def test_dropdown_is_created_after_dialog_and_raised_on_every_open():
    source = _source()
    ensure = source.split("def _ensure_popup", 1)[1].split(
        "def _raise_popup", 1)[0]
    raiser = source.split("def _raise_popup", 1)[1].split(
        "def _desired_popup_geometry", 1)[0]
    opener = source.split("def open_popup", 1)[1].split(
        "showPopup = open_popup", 1)[0]
    assert "self._rebuild_popup_items()" in ensure
    assert "dpg.move_item(self._popup, parent=self._popup_host)" in raiser
    assert "self._ensure_popup()" in opener
    assert "self._raise_popup()" in opener


def test_dropdown_width_and_top_come_from_full_combobox_shell():
    source = _source()
    geometry = source.split("def _desired_popup_geometry", 1)[1].split(
        "def _initial_popup_local_pos", 1)[0]
    assert "dpg.get_item_rect_min(self.shell)" in geometry
    assert "dpg.get_item_rect_size(self.shell)" in geometry
    assert "width = max(1, int(round(width)))" in geometry
    assert "shell_bottom = int(round(top + height))" in geometry
    assert "return int(round(left)), shell_bottom, width" in geometry


def test_popup_position_is_calibrated_against_rendered_rect():
    source = _source()
    sync = source.split("def _sync_popup_geometry", 1)[1].split(
        "def _calibrate_popup_geometry", 1)[0]
    assert "dpg.get_item_rect_min(self._popup)" in sync
    assert "desired_left - actual_left" in sync
    assert "desired_top - actual_top" in sync
    assert "dpg.set_item_pos(self._popup" in sync


def test_packaged_duplicate_uses_identical_shared_component():
    assert SOURCE.read_bytes() == DUPLICATE.read_bytes()
