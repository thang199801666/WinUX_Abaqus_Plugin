from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"


def _read(relative):
    return (WINUX / relative).read_text(encoding="utf-8")


def test_combo_arrow_uses_native_imgui_combo_hit_target():
    source = _read("components/qt_combo_box.py")
    assert "self.button = dpg.add_combo(" in source
    assert "no_preview=True" in source
    assert "callback=self._native_selected" in source
    assert "self.button = dpg.add_drawlist(" not in source
    assert "self.button = dpg.add_button(" not in source
    handler = source.split("def _install_button_state_handlers", 1)[1].split(
        "def _install_handlers", 1)[0]
    assert "add_item_clicked_handler" not in handler

def test_shared_form_layout_uses_one_table_and_compact_rows():
    dialog = _read("dialogs/qt_dialog.py")
    style = _read("widgets/imgui_qt_style.py")
    assert "def form_layout(self, parent=None, *, label_width=None):" in dialog
    assert "def form_layout_row(self, table, label, builder):" in dialog
    assert "form_label_cell_theme" in dialog
    assert "mvStyleVar_CellPadding, 0, 2" in style
    assert "mvStyleVar_WindowPadding, 0, 5" in style


def test_login_uses_single_shared_form_and_hides_empty_error_slot():
    source = _read("dialogs/login_form.py")
    assert "self._form = self.form_layout(parent=self.content, label_width=78)" in source
    assert "self.form_layout_row(" in source
    assert "self._line_field" in source
    assert "self.preferred_size = (420, 184)" in source
    assert "self.error = self.status_text(error=True, wrap=360)" in source
    assert "self.set_status_text(self.error, text, error=True)" in source


def test_product_version_remains_1_1_0():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.1.0"


def test_combo_dropdown_is_native_begincombo_not_second_modal_overlay():
    source = _read("components/qt_combo_box.py")
    constructor = source.split("def __init__", 1)[1].split("# ------------------------------------------------------------------ API", 1)[0]
    assert "self.button = dpg.add_combo(" in constructor
    assert "no_preview=True" in constructor
    assert "self._popup = dpg.add_child_window(" not in source
    assert "dpg.add_selectable(" not in source
    assert "popup=True" not in source

def test_combo_uses_one_full_width_native_frame_with_editor_overlay():
    source = _read("components/qt_combo_box.py")
    constructor = source.split("def __init__", 1)[1].split("# ------------------------------------------------------------------ API", 1)[0]
    assert "self.button = dpg.add_combo(" in constructor
    assert "width=-1" in constructor
    assert "no_preview=False" in constructor
    assert "popup_align_left=True" in constructor
    assert "pos=(0, 0)" in constructor
    assert "editor_right_reserve = self.ARROW_WIDTH + 1" in constructor
    assert "pos=(1, 1)" in constructor
    assert "width=-editor_right_reserve" in constructor
    assert "dpg.add_table_column(" not in constructor
    assert "self.separator = None" in constructor
    assert "self.separator = dpg.add_drawlist(" not in constructor
    assert "ARROW_WIDTH = METRICS.arrow_width" in source


def test_combo_popup_owner_spans_entire_control_instead_of_arrow_only():
    source = _read("components/qt_combo_box.py")
    constructor = source.split("def __init__", 1)[1].split("# ------------------------------------------------------------------ API", 1)[0]
    combo_call = constructor.split("self.button = dpg.add_combo(", 1)[1].split(")\n", 1)[0]
    assert "width=-1" in combo_call
    assert "no_preview=False" in combo_call
    assert "popup_align_left=True" in combo_call
    assert "fit_width=False" in combo_call
    assert "self._popup = dpg.add_child_window(" not in source
