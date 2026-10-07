from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"


def _source():
    return (WINUX / "components" / "qt_combo_box.py").read_text(encoding="utf-8")


def _constructor():
    return _source().split("def __init__", 1)[1].split(
        "# ------------------------------------------------------------------ API", 1)[0]


def test_login_combo_uses_native_imgui_popup_inside_modal_stack():
    source = _source()
    constructor = _constructor()
    assert "self.button = dpg.add_combo(" in constructor
    assert "self._popup = dpg.add_window(" not in source
    assert "popup=True" not in source
    assert "dpg.add_selectable(" not in source


def test_native_popup_owner_spans_full_combo_width():
    constructor = _constructor()
    call = constructor.split("self.button = dpg.add_combo(", 1)[1].split("\n        )", 1)[0]
    assert "parent=self.shell" in call
    assert "pos=(0, 0)" in call
    assert "width=-1" in call
    assert "no_preview=False" in call
    assert "popup_align_left=True" in call
    assert "fit_width=False" in call


def test_editor_reserves_only_native_arrow_strip():
    constructor = _constructor()
    assert "editor_right_reserve = self.ARROW_WIDTH + 1" in constructor
    assert "width=-editor_right_reserve" in constructor
    assert constructor.index("self.input = dpg.add_input_text(") < constructor.index(
        "self.button = dpg.add_combo(")


def test_overlay_preview_stays_blank_while_history_is_selectable():
    source = _source()
    constructor = _constructor()
    assert 'default_value=""' in constructor
    assert 'dpg.set_value(self.button, "")' in source
    selected = source.split("def _native_selected", 1)[1].split(
        "# -------------------------------------------------------------- behavior", 1)[0]
    assert "self.set_current_text(value, emit=True)" in selected
    assert 'dpg.set_value(self.button, "")' in selected


def test_combo_frame_is_transparent_but_arrow_keeps_button_states():
    source = _source()
    theme = source.split("def _arrow_theme", 1)[1].split("class ImGuiComboBox", 1)[0]
    assert "base = (0, 0, 0, 0)" in theme
    assert "mvThemeCol_FrameBg" in theme
    assert "mvThemeCol_Button" in theme
    assert "mvThemeCol_ButtonHovered" in theme
    assert "mvThemeCol_ButtonActive" in theme
