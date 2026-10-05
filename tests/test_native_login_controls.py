from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGIN = ROOT / "WinUx" / "dialogs" / "login_dialog.py"
FORM = ROOT / "WinUx" / "dialogs" / "login_form.py"
FLOATING_FORMS = ROOT / "WinUx" / "dialogs" / "floating_forms.py"
LEGACY_RUNTIME = ROOT / "WinUx" / "dialogs" / "native_login_runtime.py"


def test_legacy_native_tk_login_runtime_is_removed():
    assert not LEGACY_RUNTIME.exists()


def test_login_uses_process_isolated_dear_imgui_form_runtime():
    login = LOGIN.read_text(encoding="utf-8")
    form = FORM.read_text(encoding="utf-8")
    factory = FLOATING_FORMS.read_text(encoding="utf-8")
    assert "FloatingDialogController" in login
    assert "LoginForm" in factory
    assert 'if kind == "login"' in factory
    assert "ImGuiComboBox" in form
    assert "ImGuiCheckBox" in form
    for forbidden in ("tkinter", "ttk.Combobox", "NativeQtLoginRuntime"):
        assert forbidden not in login + form + factory
