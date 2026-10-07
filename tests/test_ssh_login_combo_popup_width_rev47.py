from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"


def _read(relative):
    return (WINUX / relative).read_text(encoding="utf-8")


def test_editable_combo_popup_width_follows_full_shell_rect():
    source = _read("components/qt_combo_box.py")
    geometry = source.split("def _popup_geometry", 1)[1].split(
        "# -------------------------------------------------------------- behavior", 1)[0]
    assert "dpg.get_item_rect_min(self.shell)" in geometry
    assert "dpg.get_item_rect_size(self.shell)" in geometry
    assert "width = max(1, int(round(width)))" in geometry
    assert "return (int(round(left)), popup_top, width, popup_height)" in geometry


def test_arrow_hit_target_no_longer_owns_a_narrow_native_combo_popup():
    source = _read("components/qt_combo_box.py")
    constructor = source.split("def __init__", 1)[1].split(
        "# ------------------------------------------------------------------ API", 1)[0]
    assert "self.button = dpg.add_drawlist(" in constructor
    assert "self._popup = dpg.add_window(" in constructor
    assert "popup=True" in constructor
    assert "self.button = dpg.add_combo(" not in constructor
    assert "no_preview=True" not in constructor


def test_history_rows_fill_the_retained_popup_and_keep_editable_input():
    source = _read("components/qt_combo_box.py")
    assert "dpg.add_selectable(" in source
    assert "parent=self._popup, width=-1" in source
    assert "readonly=not self.editable" in source
    assert "self.set_current_text(str(value), emit=True)" in source
    assert "self.close_popup()" in source
