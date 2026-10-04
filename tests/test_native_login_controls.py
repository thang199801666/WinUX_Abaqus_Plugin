from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "WinUx" / "dialogs" / "native_login_runtime.py"
LOGIN = ROOT / "WinUx" / "dialogs" / "login_dialog.py"
PROCESS = ROOT / "WinUx" / "services" / "floating_dialog_process.py"


def test_login_uses_real_integrated_combo_and_entry_controls():
    source = RUNTIME.read_text(encoding="utf-8")
    assert "ttk.Combobox(" in source
    assert "ttk.Entry(" in source
    assert 'style="WinUx.QtComboBox.TCombobox"' in source
    assert 'style="WinUx.QtLineEdit.TEntry"' in source
    assert "icursor(\"end\")" in source
    assert "selection_clear()" in source


def test_login_bypasses_dpg_prewarm_and_dispatches_native_runtime():
    login_source = LOGIN.read_text(encoding="utf-8")
    process_source = PROCESS.read_text(encoding="utf-8")
    assert "prewarm=False" in login_source
    assert "NativeQtLoginRuntime" in process_source
    assert 'initial.get("kind")' in process_source
