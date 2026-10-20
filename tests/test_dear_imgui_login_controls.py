from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGIN_FORM = ROOT / "WinUx" / "dialogs" / "login_form.py"
LOGIN_DIALOG = ROOT / "WinUx" / "dialogs" / "login_dialog.py"
# The editable login combo moved into the shared DearUIQt widget library.
COMBO = ROOT / "DearUIQt" / "widgets" / "combo_box.py"
PROCESS = ROOT / "WinUx" / "services" / "floating_dialog_process.py"
FLOATING_FORMS = ROOT / "WinUx" / "dialogs" / "floating_forms.py"
HOST = ROOT / "WinUx" / "ui" / "hosting" / "host.py"


def test_login_uses_only_dearpygui_runtime():
    process_source = PROCESS.read_text(encoding="utf-8")
    login_source = LOGIN_DIALOG.read_text(encoding="utf-8")
    assert "FloatingDialogRuntime" in process_source
    assert "NativeQtLoginRuntime" not in process_source
    assert "tkinter" not in process_source
    assert "ttk" not in process_source
    # The login entry point is the shared DearUIQt/(Dear ImGui / Dear PyGui)
    # dialog stack; the old dedicated native Tk login runtime is gone.
    assert "Dear ImGui / Dear PyGui" in process_source
    assert "LoginDialog" in login_source
    assert "inprocess_adapters" in login_source


def test_login_can_use_dpg_prewarm_like_other_floating_dialogs():
    forms = FLOATING_FORMS.read_text(encoding="utf-8")
    host = HOST.read_text(encoding="utf-8")
    # Login is now just one more prewarmable form kind handled by the shared
    # floating dialog host; the pool claim has no login special case.
    assert 'FORM_KINDS = ("login"' in forms
    assert 'if kind == "login"' in forms
    assert "def claim" in host
    assert "pool.claim(refill=False, kind=kind)" in host
    assert "login" not in host


def test_editable_combo_is_dpg_input_plus_full_width_native_combo():
    source = COMBO.read_text(encoding="utf-8")
    assert "dpg.add_input_text(" in source
    assert "self.button = dpg.add_combo(" in source
    assert "no_preview=False" in source
    assert "callback=self._native_selected" in source
    assert 'label="v"' not in source
    assert "dpg.add_child_window(" in source  # outer one-frame shell only
    assert "self._popup = dpg.add_child_window(" not in source
    assert "dpg.add_selectable(" not in source
    assert "tkinter" not in source
    assert "PyQt" not in source

def test_combo_mouse_click_is_left_to_imgui_inputtext_for_caret():
    source = COMBO.read_text(encoding="utf-8")
    # A click callback calling focus_item was the source of nav-focus without
    # an active InputText/caret on the bundled Dear PyGui build.
    input_handler = source.split("def _install_input_state_handlers", 1)[1].split(
        "def _install_button_state_handlers", 1
    )[0]
    assert "add_item_clicked_handler" not in input_handler
    assert "focus_item(self.input)" not in input_handler
    assert "auto_select_all=False" in source


def test_login_form_still_uses_shared_dpg_combo_wrapper():
    source = LOGIN_FORM.read_text(encoding="utf-8")
    assert "ImGuiComboBox" in source
    # The form consumes the shared editable DPG combo wrapper (retained inside
    # DearUIQt/widgets) instead of batch dpg.* calls of its own.
    assert "combo.setEditable(True)" in source
    assert "QtComboBox" not in source
