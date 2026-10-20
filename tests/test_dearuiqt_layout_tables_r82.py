from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def test_application_layouts_do_not_construct_renderer_tables_directly():
    offenders = []
    for path in (ROOT / "WinUx").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if any(token in source for token in (
            "dpg.table(", "dpg.table_row(", "dpg.add_table(", "dpg.add_table_column("
        )):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_remaining_browser_and_reference_layouts_use_qgridlayout():
    for relative in (
        "WinUx/dialogs/reference_chart_form.py",
        "WinUx/dialogs/local_folder_form.py",
    ):
        source = _source(relative)
        assert "QGridLayout(" in source
        assert "dpg.table(" not in source
        assert "dpg.table_row(" not in source
        assert "dpg.add_table_column(" not in source


def test_local_file_reuses_base_selection_grid_and_imports_qlabel():
    source = _source("WinUx/dialogs/local_file_form.py")
    assert "from DearUIQt.widgets import QLabel" in source
    assert "self._selection_grid.cell(1, 0)" in source
    assert "self._selection_grid.cell(1, 1)" in source
    assert "dpg.table(" not in source


def test_r82_dearuiqt_version_boundary():
    import DearUIQt
    assert tuple(map(int, DearUIQt.__version__.split("."))) >= (1, 21, 0)


def test_login_uses_dearuiqt_form_row_helper_not_renderer_table_row():
    source = _source("WinUx/dialogs/login_form.py")
    assert "form_layout_editor_row(" in source
    assert "dpg.table_row(" not in source
    framework = _source("DearUIQt/dialogs/qt_dialog.py")
    assert "def form_layout_editor_row(" in framework
