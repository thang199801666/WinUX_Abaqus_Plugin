from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_qtablewidget_row_removal_disposes_owned_cell_widgets():
    from tests.test_dearuiqt_modelview_r79 import FakeBackend
    from DearUIQt.modelview import QTableWidget
    from DearUIQt.widgets import QWidget

    backend = FakeBackend()
    table = QTableWidget(1, 1, backend=backend)
    editor = QWidget(parent=table, backend=backend)
    native = editor.tag
    table.setCellWidget(0, 0, editor)
    assert backend.does_item_exist(native)
    assert table.setRowCount(0) is table
    assert editor._deleted
    assert not backend.does_item_exist(native)
    assert table.rowCount() == 0


def test_job_manager_and_schedule_use_qtablewidget_not_renderer_tables():
    for relative in ("WinUx/dialogs/job_manager_form.py", "WinUx/dialogs/job_schedule_form.py"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "QTableWidget(" in source
        assert "dpg.table(" not in source
        assert "dpg.table_row(" not in source
        assert "dpg.add_table_column(" not in source


def test_layout_only_surfaces_route_through_qgridlayout():
    expected = {
        "WinUx/dialogs/settings_form.py": "QGridLayout(",
        "WinUx/dialogs/folder_browser_address.py": "QGridLayout(",
        "WinUx/dialogs/odb_extract_form.py": "QGridLayout(",
        "WinUx/dialogs/transfer_center_form.py": "QGridLayout(",
        "WinUx/ui/components/toolbar.py": "QGridLayout(",
    }
    for relative, token in expected.items():
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert token in source
        assert "dpg.add_table(" not in source


def test_r81_version_and_semantic_table_boundary():
    import DearUIQt

    assert tuple(map(int, DearUIQt.__version__.split("."))) >= (1, 20, 0)
    architecture = (ROOT / "DearUIQt/ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "data table" in architecture.lower()
    assert "layout-only" in architecture.lower()
