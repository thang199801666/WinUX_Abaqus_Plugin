from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"


def _read(relative):
    return (WINUX / relative).read_text(encoding="utf-8")


def test_combo_popup_is_positioned_while_hidden_and_clamped_to_viewport():
    source = _read("components/qt_combo_box.py")
    assert "def _popup_geometry" in source
    assert "get_viewport_client_width" in source
    assert "get_viewport_client_height" in source
    assert "show=False" in source
    assert "dpg.set_item_pos(self._popup" in source
    assert "popup_y = below_y if" in source


def test_combo_popup_keyboard_highlight_commits_only_on_enter():
    source = _read("components/qt_combo_box.py")
    assert "self._popup_index" in source
    assert "def _move_popup_highlight" in source
    assert '("mvKey_Return", self._return_pressed)' in source
    assert "self._sync_popup_selection(self._popup_index)" in source
    assert "self.set_current_text(self.items[index], emit=True)" in source


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
    assert "form_label_top_pad: int = 3" in style
    assert "height=METRICS.form_label_top_pad" in dialog


def test_checkbox_indicator_keeps_compact_qt_spacing():
    style = _read("widgets/imgui_qt_style.py")
    assert "check_size: int = 15" in style
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
