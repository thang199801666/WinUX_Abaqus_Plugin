from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"


def _read(relative):
    return (WINUX / relative).read_text(encoding="utf-8")


def test_line_edit_focus_frame_is_passive_and_keeps_imgui_caret_owner():
    style = _read("widgets/imgui_qt_style.py")
    controls = _read("widgets/controls.py")
    assert "def line_edit_theme(backend, *, disabled=False, focused=False)" in style
    assert "p.FOCUS if focused else p.BORDER" in style
    assert "_bind_focus_state_handlers" in controls
    line_block = controls.split("class ImGuiLineEdit", 1)[1].split(
        "class _ImGuiAbstractSpinBox", 1)[0]
    assert "focused=enabled and self._focused()" in line_block
    # Never synthesize a second mouse-focus event around InputText.
    assert "focus_item(self.tag)" not in line_block
    assert "add_item_clicked_handler" not in line_block


def test_checkbox_checked_state_uses_fusion_blue_fill_white_checkmark():
    style = _read("widgets/imgui_qt_style.py")
    controls = _read("widgets/controls.py")
    assert "def checkbox_theme(backend, *, disabled=False, checked=False, focused=False)" in style
    assert "bg = p.HIGHLIGHT" in style
    assert "mark = p.HIGHLIGHT_TEXT" in style
    check_block = controls.split("class ImGuiCheckBox", 1)[1].split(
        "# Qt-style names remain compatibility aliases", 1)[0]
    assert "self._refresh_style()" in check_block
    assert "checked=checked" in check_block
    assert "focused=enabled and self._focused()" in check_block


def test_push_button_has_qpushbutton_default_and_focus_state_contract():
    style = _read("widgets/imgui_qt_style.py")
    controls = _read("widgets/controls.py")
    dialog = _read("dialogs/qt_dialog.py")
    assert 'def button_theme(backend, *, role="secondary", disabled=False, focused=False, default=False)' in style
    assert "def isDefault" in controls
    assert "default=self._default" in controls
    assert "focused=enabled and self._focused()" in controls
    assert "wrappers[button] = widget" in dialog


def test_login_busy_state_updates_retained_control_themes_not_only_native_enabled_bit():
    login = _read("dialogs/login_form.py")
    assert "self.set_control_enabled(item, enabled)" in login
    assert "self._remember_widget.setEnabled(enabled)" in login
    assert "combo.set_enabled(enabled)" in login


def test_combo_and_spin_subcontrol_glyphs_are_centered_without_nested_focus_frame():
    combo = _read("components/qt_combo_box.py")
    style = _read("widgets/imgui_qt_style.py")
    assert 'mvStyleVar_ButtonTextAlign' in combo
    assert 'dpg.add_theme_color(dpg.mvThemeCol_NavHighlight, face)' in combo
    assert 'mvStyleVar_ButtonTextAlign' in style
    assert 'backend.add_theme_color(backend.mvThemeCol_NavHighlight, face)' in style


def test_settings_uses_backend_explicit_imgui_checkbox_name():
    source = _read("dialogs/settings_form.py")
    assert "ImGuiCheckBox" in source
    assert "QCheckBox" not in source


def test_phase12_form_paths_remain_dear_imgui_only():
    source = "\n".join([
        _read("widgets/imgui_qt_style.py"),
        _read("widgets/controls.py"),
        _read("components/qt_combo_box.py"),
        _read("dialogs/qt_dialog.py"),
        _read("dialogs/login_form.py"),
        _read("dialogs/settings_form.py"),
    ])
    for forbidden in ("import tkinter", "from tkinter", "PyQt6", "PySide6"):
        assert forbidden not in source
