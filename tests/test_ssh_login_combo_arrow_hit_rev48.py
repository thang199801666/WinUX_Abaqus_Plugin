from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"


def _read(relative):
    return (WINUX / relative).read_text(encoding="utf-8")


def test_arrow_hit_test_runs_even_when_popup_is_closed():
    source = _read("components/qt_combo_box.py")
    mouse = source.split("def _mouse_clicked", 1)[1].split("def _f4_pressed", 1)[0]
    arrow_check = mouse.index("self._point_inside(self.button, x, y)")
    popup_guard = mouse.index("if not self.popup_open()")
    assert arrow_check < popup_guard
    assert "self.toggle_popup()" in mouse[:popup_guard]


def test_drawlist_click_handler_cannot_double_toggle_popup():
    source = _read("components/qt_combo_box.py")
    handlers = source.split("def _install_button_state_handlers", 1)[1].split(
        "def _arrow_clicked", 1)[0]
    assert "add_item_clicked_handler" not in handlers
    assert "add_item_activated_handler" in handlers
    assert "add_item_deactivated_handler" in handlers


def test_rev47_layout_and_full_width_popup_are_preserved():
    source = _read("components/qt_combo_box.py")
    assert "self.button = dpg.add_drawlist(" in source
    assert "dpg.draw_triangle(" in source
    geometry = source.split("def _popup_geometry", 1)[1].split(
        "# -------------------------------------------------------------- behavior", 1)[0]
    assert "dpg.get_item_rect_min(self.shell)" in geometry
    assert "dpg.get_item_rect_size(self.shell)" in geometry
