from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"


def _read(relative):
    return (WINUX / relative).read_text(encoding="utf-8")


def test_arrow_is_real_button_with_direct_popup_callback():
    source = _read("components/qt_combo_box.py")
    constructor = source.split("def __init__", 1)[1].split(
        "# ------------------------------------------------------------------ API", 1)[0]
    assert "self.button = dpg.add_button(" in constructor
    assert "callback=self._arrow_clicked" in constructor
    assert "self.button = dpg.add_drawlist(" not in constructor
    assert "dpg.bind_item_theme(self.button, _arrow_theme())" in constructor


def test_global_mouse_handler_does_not_toggle_arrow_again():
    source = _read("components/qt_combo_box.py")
    mouse = source.split("def _mouse_clicked", 1)[1].split("def _f4_pressed", 1)[0]
    arrow_branch = mouse.split("if self._point_inside(self.button, x, y):", 1)[1].split(
        "if not self.popup_open()", 1)[0]
    assert "return" in arrow_branch
    assert "toggle_popup" not in arrow_branch


def test_full_width_popup_geometry_is_unchanged():
    source = _read("components/qt_combo_box.py")
    geometry = source.split("def _popup_geometry", 1)[1].split(
        "# -------------------------------------------------------------- behavior", 1)[0]
    assert "dpg.get_item_rect_min(self.shell)" in geometry
    assert "dpg.get_item_rect_size(self.shell)" in geometry
    assert "return (int(round(left)), popup_top, width, popup_height)" in geometry


def test_arrow_enable_state_is_native_button_state():
    source = _read("components/qt_combo_box.py")
    block = source.split("def set_enabled", 1)[1].split("setEnabled = set_enabled", 1)[0]
    assert "dpg.configure_item(self.button, enabled=self.enabled)" in block
    assert "_arrow_theme(disabled=not self.enabled)" in block
