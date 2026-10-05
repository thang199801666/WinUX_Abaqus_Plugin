from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"


def _read(relative):
    return (WINUX / relative).read_text(encoding="utf-8")


def test_combo_uses_native_begincombo_popup_instead_of_manual_overlay_geometry():
    source = _read("components/qt_combo_box.py")
    assert "self.button = dpg.add_combo(" in source
    assert "no_preview=True" in source
    assert "def _popup_geometry" not in source
    assert "dpg.set_item_pos(self._popup" not in source


def test_combo_keyboard_index_navigation_remains_on_editable_input():
    source = _read("components/qt_combo_box.py")
    assert "def _up_pressed" in source
    assert "def _down_pressed" in source
    assert "self.set_current_index" in source
    assert '("mvKey_F4", self._f4_pressed)' in source

def test_combo_exposes_qcombobox_max_visible_items_contract():
    source = _read("components/qt_combo_box.py")
    assert "def setMaxVisibleItems" in source
    assert "def maxVisibleItems" in source
    assert "METRICS.popup_row_height" in source


def test_spinbox_uses_compact_zero_gap_button_stack():
    style = _read("widgets/imgui_qt_style.py")
    controls = _read("widgets/controls.py")
    assert "spin_arrow_width: int = 17" in style
    assert "def spin_button_stack_theme" in style
    assert "mvStyleVar_ItemSpacing, 0, 0" in style
    assert "bind_theme(backend, self.buttons, spin_button_stack_theme)" in controls
    assert "half_height = max(10, METRICS.control_height // 2)" in controls


def test_form_labels_get_qformlayout_vertical_alignment_inset():
    style = _read("widgets/imgui_qt_style.py")
    dialog = _read("dialogs/qt_dialog.py")
    assert "form_label_top_pad: int = 4" in style
    assert "height=METRICS.form_label_top_pad" in dialog


def test_checkbox_indicator_keeps_compact_qt_spacing():
    style = _read("widgets/imgui_qt_style.py")
    assert "check_size: int = 14" in style
    assert "mvStyleVar_ItemInnerSpacing, 6, 4" in style


def test_phase11_controls_remain_dear_imgui_only():
    source = "\n".join([
        _read("widgets/imgui_qt_style.py"),
        _read("widgets/controls.py"),
        _read("components/qt_combo_box.py"),
        _read("dialogs/qt_dialog.py"),
    ])
    for forbidden in ("import tkinter", "from tkinter", "PyQt6", "PySide6"):
        assert forbidden not in source
