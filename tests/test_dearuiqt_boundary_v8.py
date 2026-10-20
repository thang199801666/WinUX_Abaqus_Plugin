from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dearuiqt_python_sources_never_import_winux():
    violations = []
    for path in (ROOT / "DearUIQt").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "import WinUx" in text or "from WinUx" in text:
            violations.append(path.relative_to(ROOT).as_posix())
    assert violations == []


def test_winux_login_and_settings_consume_canonical_qcheckbox_api():
    for relative in ("WinUx/dialogs/login_form.py", "WinUx/dialogs/settings_form.py"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "QCheckBox" in source
        assert "ImGuiCheckBox(" not in source


def test_example_uses_dearuiqt_without_winux_ui_facade():
    source = (ROOT / "examples/dearuiqt_demo.py").read_text(encoding="utf-8")
    assert "from DearUIQt import" in source
    assert "from WinUx.ui" not in source
    assert not (ROOT / "examples/shared_ui_demo.py").exists()


def test_reference_chart_multiline_formula_uses_dearuiqt_plain_text_wrapper():
    source = (ROOT / "WinUx/dialogs/reference_chart_form.py").read_text(encoding="utf-8")
    assert "self.plain_text_edit(" in source
    formula_block = source.split("with dpg.group(parent=editor_panel, show=False) as formula_group:", 1)[1].split("self.data_table =", 1)[0]
    assert "dpg.add_input_text(" not in formula_block
