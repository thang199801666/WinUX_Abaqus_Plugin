"""Tail-shrink complexity and ownership regression for Reference Chart tables."""
from tests.test_dearuiqt_modelview_r79 import FakeBackend


def test_tail_removal_does_not_scan_every_cell_widget():
    from DearUIQt.modelview import QTableWidget, QTableWidgetItem
    from DearUIQt.widgets import QWidget

    class IndexedOnly(dict):
        def items(self):
            raise AssertionError("tail row removal must not scan all cell widgets")

    backend = FakeBackend()
    table = QTableWidget(4, 3, backend=backend)
    editor = QWidget(parent=table, backend=backend)
    table.setCellWidget(3, 1, editor)
    removed = QTableWidgetItem("tail")
    table.setItem(3, 2, removed)
    kept = QTableWidgetItem("keep")
    table.setItem(0, 0, kept)
    table._cell_widgets = IndexedOnly(table._cell_widgets)
    assert table.removeRow(3)
    assert editor._deleted
    assert removed.tableWidget() is None
    assert kept.tableWidget() is table
    assert table.rowCount() == 3


def test_shrink_thousands_of_rows_retains_early_items():
    from DearUIQt.modelview import QTableWidget, QTableWidgetItem

    backend = FakeBackend()
    table = QTableWidget(0, 2, backend=backend)
    first = QTableWidgetItem("first")
    for row in range(300):
        table.insertRow(row)
    table.setItem(0, 0, first)
    table.setRowCount(2)
    assert table.rowCount() == 2
    assert table.item(0, 0) is first
    assert first.tableWidget() is table
