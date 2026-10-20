from tests.test_dearuiqt_modelview_r79 import FakeBackend


def test_set_column_count_can_shrink_and_disposes_removed_column_contents():
    from DearUIQt.modelview import QTableWidget, QTableWidgetItem
    from DearUIQt.widgets import QWidget

    backend = FakeBackend()
    table = QTableWidget(1, 3, backend=backend)
    table.setHorizontalHeaderLabels(["A", "B", "C"])
    keep = QTableWidgetItem("keep")
    removed = QTableWidgetItem("removed")
    table.setItem(0, 0, keep)
    table.setItem(0, 2, removed)
    editor = QWidget(parent=table, backend=backend)
    editor_native = editor.tag
    table.setCellWidget(0, 1, editor)

    table.setColumnCount(1)

    assert table.columnCount() == 1
    assert table.item(0, 0) is keep
    assert keep.tableWidget() is table and (keep.row(), keep.column()) == (0, 0)
    assert removed.tableWidget() is None and (removed.row(), removed.column()) == (-1, -1)
    assert editor._deleted
    assert not backend.does_item_exist(editor_native)
    assert table._headers == ["A"]


def test_remove_column_reindexes_surviving_items_and_current_cell():
    from DearUIQt.modelview import QTableWidget, QTableWidgetItem

    backend = FakeBackend()
    table = QTableWidget(1, 3, backend=backend)
    item = QTableWidgetItem("right")
    table.setItem(0, 2, item)
    table.setCurrentCell(0, 2)
    events = []
    table.currentCellChanged.connect(lambda row, col, old_row, old_col: events.append(
        (row, col, old_row, old_col)))

    assert table.removeColumn(1)
    assert table.columnCount() == 2
    assert table.item(0, 1) is item
    assert (item.row(), item.column()) == (0, 1)
    assert (table.currentRow(), table.currentColumn()) == (0, 1)
    assert events[-1] == (0, 1, 0, 2)


def test_row_structure_keeps_current_cell_on_same_logical_row():
    from DearUIQt.modelview import QTableWidget

    backend = FakeBackend()
    table = QTableWidget(3, 1, backend=backend)
    table.setCurrentCell(2, 0)
    table.insertRow(1)
    assert (table.currentRow(), table.currentColumn()) == (3, 0)
    assert table.removeRow(0)
    assert (table.currentRow(), table.currentColumn()) == (2, 0)
    assert table.removeRow(2)
    assert (table.currentRow(), table.currentColumn()) == (-1, -1)


def test_reusing_cell_widget_transfers_table_mapping_without_duplicate_ownership():
    from DearUIQt.modelview import QTableWidget
    from DearUIQt.widgets import QWidget

    backend = FakeBackend()
    table = QTableWidget(1, 2, backend=backend)
    editor = QWidget(parent=table, backend=backend)
    table.setCellWidget(0, 0, editor)
    table.setCellWidget(0, 1, editor)

    assert table.cellWidget(0, 0) is None
    assert table.cellWidget(0, 1) is editor
    assert list(table._cell_widgets.values()) == [editor]
    assert not editor._deleted


def test_cell_widget_lookup_does_not_scan_every_existing_editor():
    from DearUIQt.modelview import QTableWidget
    from DearUIQt.widgets import QWidget

    class NoLinearScan(dict):
        def items(self):
            raise AssertionError("setCellWidget must use its reverse index, not scan all editors")

    backend = FakeBackend()
    table = QTableWidget(1, 2, backend=backend)
    editor = QWidget(parent=table, backend=backend)
    table.setCellWidget(0, 0, editor)
    table._cell_widgets = NoLinearScan(table._cell_widgets)
    table.setCellWidget(0, 1, editor)
    assert table.cellWidget(0, 0) is None
    assert table.cellWidget(0, 1) is editor


def test_item_flags_update_native_enabled_state_and_table_delete_detaches_items():
    from DearUIQt.core import Qt
    from DearUIQt.modelview import QTableWidget, QTableWidgetItem

    backend = FakeBackend()
    table = QTableWidget(1, 1, backend=backend)
    item = QTableWidgetItem("value")
    table.setItem(0, 0, item)
    native = table.nativeItem(0, 0)

    item.setFlags(Qt.ItemIsSelectable)
    assert backend.config[native]["enabled"] is False

    table.delete()
    assert item.tableWidget() is None
    assert (item.row(), item.column()) == (-1, -1)
    assert table.rowCount() == 0 and table.columnCount() == 0


def test_clear_resets_contents_and_headers_but_keeps_table_shape():
    from DearUIQt.modelview import QTableWidget, QTableWidgetItem

    backend = FakeBackend()
    table = QTableWidget(2, 2, backend=backend)
    table.setHorizontalHeaderLabels(["A", "B"])
    item = QTableWidgetItem("value")
    table.setItem(1, 1, item)

    assert table.clear() is table
    assert table.rowCount() == 2 and table.columnCount() == 2
    assert table.item(1, 1) is None
    assert item.tableWidget() is None
    assert table._headers == ["", ""]
    assert [backend.config[tag].get("label") for tag in table._column_tags] == ["", ""]


def test_r82_version_and_architecture_document_table_ownership():
    from pathlib import Path
    import DearUIQt

    root = Path(__file__).resolve().parents[1]
    assert tuple(map(int, DearUIQt.__version__.split("."))) >= (1, 21, 0)
    architecture = (root / "DearUIQt/ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "qtablewidget" in architecture.casefold()
    assert "detach item ownership" in architecture.casefold()


def test_appending_rows_does_not_reindex_existing_table_contents():
    from DearUIQt.modelview import QTableWidget, QTableWidgetItem

    backend = FakeBackend()
    table = QTableWidget(0, 2, backend=backend)
    calls = []
    original = table._reindex_after_row_change
    table._reindex_after_row_change = lambda row, delta: calls.append((row, delta)) or original(row, delta)
    for index in range(100):
        row = table.insertRow(table.rowCount())
        table.setItem(row, 0, QTableWidgetItem(str(index)))
    assert table.rowCount() == 100
    assert calls == []


def test_cell_widget_temporarily_replaces_item_renderer_and_item_returns_on_remove():
    from DearUIQt.modelview import QTableWidget, QTableWidgetItem
    from DearUIQt.widgets import QWidget

    backend = FakeBackend()
    table = QTableWidget(1, 3, backend=backend)
    left = QTableWidgetItem("#")
    value = QTableWidgetItem("42")
    right = QTableWidgetItem("84")
    table.setItem(0, 0, left)
    table.setItem(0, 1, value)
    table.setItem(0, 2, right)
    old_native = table.nativeItem(0, 1)
    editor = QWidget(parent=table, backend=backend)

    table.setCellWidget(0, 1, editor)
    assert table.item(0, 1) is value
    assert table.nativeItem(0, 1) is None
    assert not backend.does_item_exist(old_native)

    editor.delete()
    assert table.removeCellWidget(0, 1) is editor
    assert table.nativeItem(0, 1) is not None
    assert table.item(0, 1).text() == "42"
