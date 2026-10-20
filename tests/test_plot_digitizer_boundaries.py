from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "WinUx" / "plotdigitizer"


def test_core_and_application_do_not_depend_on_winux_ui_or_dpg():
    forbidden = (
        "dearpygui", "WinUx.ui", "..ui", "...ui",
        "dialogs.", "reference_charts",
    )
    for layer in ("core", "application"):
        for path in (ROOT / layer).glob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert not any(token in text for token in forbidden), path


def test_winux_dependencies_are_confined_to_ui_and_integration():
    assert (ROOT / "ui" / "dialog.py").exists()
    assert (ROOT / "integration" / "winux.py").exists()
    shim = (ROOT.parent / "dialogs" / "plot_digitizer_form.py").read_text(encoding="utf-8")
    assert "plotdigitizer.ui" in shim
