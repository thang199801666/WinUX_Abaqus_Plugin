"""Regression for editable QComboBox native full-width popup geometry."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "DearUIQt" / "widgets" / "combo_box.py"


def _source():
    return SRC.read_text(encoding="utf-8")


def test_native_combo_keeps_full_frame_width_but_is_clipped_to_arrow_strip():
    source = _source()
    constructor = source.split("class ImGuiComboBox:", 1)[1].split(
        "def _native_value_for", 1)[0]
    assert "self._arrow_clip = dpg.add_child_window(" in constructor
    assert "parent=self._row" in constructor
    assert "width=self._native_arrow_width" in constructor
    combo = constructor.split("self.button = dpg.add_combo(", 1)[1].split("\n        )", 1)[0]
    assert "parent=self._arrow_clip" in combo
    assert "no_preview=False" in combo
    assert "popup_align_left=True" in combo
    assert "fit_width=False" in combo
    assert "pos=(-initial_hidden_preview, 0)" in combo
    assert "width=initial_combo_width" in combo


def test_geometry_makes_combo_bbox_equal_to_resolved_field_width():
    source = _source()
    sync = source.split("def _sync_geometry", 1)[1].split("def _install_handlers", 1)[0]
    assert "shell_width = float(dpg.get_item_rect_size(self.shell)[0])" in sync
    assert "shell_width - 2 * METRICS.border_size" in sync
    assert "combo_width - self._native_arrow_width" in sync
    assert "self.button, width=combo_width" in sync
    assert "pos=(-hidden_preview, 0)" in sync


def test_editor_and_combo_have_disjoint_visible_hit_regions():
    source = _source()
    constructor = source.split("class ImGuiComboBox:", 1)[1].split(
        "def _native_value_for", 1)[0]
    assert "width=-editor_right_reserve" in constructor
    assert "parent=self._row" in constructor
    assert "parent=self._arrow_clip" in constructor
    assert "dpg.add_window(" not in constructor


def test_root_and_embedded_dearuiqt_combo_sources_are_identical():
    other = ROOT / "WinUx" / "DearUIQt" / "widgets" / "combo_box.py"
    assert SRC.read_bytes() == other.read_bytes()
