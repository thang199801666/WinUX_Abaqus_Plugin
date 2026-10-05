from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"


def _read(relative):
    return (WINUX / relative).read_text(encoding="utf-8")


def test_line_edit_and_spinbox_set_explicit_imgui_input_cursor_colour():
    source = _read("widgets/imgui_qt_style.py")
    assert 'mvThemeCol_InputTextCursor' in source
    assert 'p.TEXT_DISABLED if disabled else p.TEXT' in source
    assert 'frame_pad_y: int = 4' in source


def test_editable_combo_sets_cursor_colour_without_covering_inputtext():
    source = _read("components/qt_combo_box.py")
    assert 'mvThemeCol_InputTextCursor' in source
    assert 'auto_select_all=False' in source
    assert 'FrameBorderSize, 0' in source
    handlers = source.split("def _install_input_state_handlers", 1)[1].split(
        "def _install_button_state_handlers", 1)[0]
    assert "add_item_clicked_handler" not in handlers
    assert "focus_item(self.input)" not in handlers


def test_combo_native_popup_selection_tracks_editor_text():
    source = _read("components/qt_combo_box.py")
    assert "def _native_selected" in source
    assert "dpg.set_value(self.button, self._value)" in source
    assert "dpg.set_value(self.button, value)" in source
    assert "self.set_current_text(value, emit=True)" in source

def test_dialog_form_rows_use_compact_shared_form_layout_theme():
    style = _read("widgets/imgui_qt_style.py")
    dialog = _read("dialogs/qt_dialog.py")
    layouts = _read("widgets/layouts.py")
    assert 'def form_row_theme' in style
    assert 'mvStyleVar_CellPadding, 0, 2' in style
    assert 'form_row_theme(dpg)' in dialog
    assert 'QVBoxLayout(spacing=0' in layouts


def test_phase10_main_form_control_paths_remain_dear_imgui_only():
    source = "\n".join([
        _read("widgets/imgui_qt_style.py"),
        _read("widgets/controls.py"),
        _read("components/qt_combo_box.py"),
        _read("dialogs/qt_dialog.py"),
    ])
    for forbidden in ("import tkinter", "from tkinter", "PyQt6", "PySide6"):
        assert forbidden not in source
