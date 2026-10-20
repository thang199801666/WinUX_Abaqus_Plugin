"""Backend-independent tests for Qt-style table viewport hit testing."""
from tests.test_dearuiqt_modelview_r79 import FakeBackend

from DearUIQt.gui.palette import QtFusionMetrics
from DearUIQt.modelview import QTableWidget
from WinUx.ui.components.reference_data_table import ReferenceDataTable


class GeometryBackend(FakeBackend):
    TOP = 60.0
    HEIGHT = 260.0

    def __init__(self, *, scroll=0, row_height=24):
        super().__init__()
        self.scroll = float(scroll)
        self.row_height = float(row_height)
        self.table_tag = None
        self.row_numbers = {}
        self.row_probes = 0

    def get_item_rect_min(self, tag):
        if tag == self.table_tag:
            return (40.0, self.TOP)
        if tag in self.row_numbers:
            self.row_probes += 1
            position = self.row_numbers[tag]
            header = float(QtFusionMetrics.HEADER_HEIGHT)
            return (40.0, self.TOP + header + position * self.row_height - self.scroll)
        return (0.0, 0.0)

    def get_item_rect_size(self, tag):
        if tag == self.table_tag:
            return (440.0, self.HEIGHT)
        if tag in self.row_numbers:
            return (440.0, self.row_height)
        return (0.0, 0.0)

    def get_y_scroll(self, tag):
        return self.scroll


def _table(rows=80, scroll=0, row_height=24):
    backend = GeometryBackend(scroll=scroll, row_height=row_height)
    table = QTableWidget(rows, 3, backend=backend)
    backend.table_tag = table.tag
    backend.row_numbers = {tag: index for index, tag in enumerate(table._row_tags)}
    return table, backend


def test_qt_row_at_uses_viewport_coordinates_and_global_hit_testing():
    table, backend = _table(scroll=12 * 24)
    assert table.rowAt(12) == 12
    assert table.rowAtGlobal(backend.TOP + QtFusionMetrics.HEADER_HEIGHT + 12) == 12
    assert backend.row_probes == 2, "one native row probe per ordinary hit"
    assert table.rowAt(24 + 12) == 13
    assert table.rowAtGlobal(backend.TOP + QtFusionMetrics.HEADER_HEIGHT - 1) == -1
    assert table.rowAt(-1) == -1
    assert table.rowAtGlobal(backend.TOP + backend.HEIGHT) == -1
    assert table.rowAt(backend.HEIGHT) == -1


def test_hit_test_tries_neighbours_when_native_row_height_is_not_estimate():
    table, backend = _table(rows=60, scroll=20 * 25, row_height=25)
    # The height estimate puts y in row 25; the actual native row is 24.
    y = (24 - 20) * 25 + 8
    assert table.rowAt(y) == 24
    assert backend.row_probes < 8


def test_hit_test_does_not_scan_all_rows_for_background_or_hidden_table():
    table, backend = _table(rows=200)
    assert table.rowAt(100) == 4
    assert backend.row_probes < 3
    before = backend.row_probes
    backend.HEIGHT = 0
    assert table.rowAt(0) == -1
    assert backend.row_probes == before


def test_reference_sheet_delegates_pointer_lookup_to_shared_qt_view():
    table, backend = _table(rows=80, scroll=8 * 24)
    sheet = ReferenceDataTable.__new__(ReferenceDataTable)
    sheet._table_widget = table
    assert sheet._row_at_pointer(backend.TOP + QtFusionMetrics.HEADER_HEIGHT + 13) == 8
    assert sheet._row_at_pointer(backend.TOP - 1) is None
