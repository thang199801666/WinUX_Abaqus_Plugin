"""Qt item-model contract and sparse backing for Reference Chart."""
from DearUIQt.core import Qt, QModelIndex, QPersistentModelIndex
from WinUx.services.reference_charts import ReferenceTableModel
from WinUx.ui.components.reference_qt_model import ReferenceWorksheetQtModel


def test_adapter_exposes_qt_table_roles_headers_and_edit_signals():
    data = ReferenceTableModel(rows=2)
    adapter = ReferenceWorksheetQtModel(data)
    assert adapter.worksheet is data
    assert adapter.rowCount() == 2 and adapter.columnCount() == 2
    assert adapter.rowCount(adapter.index(0, 0)) == 0
    assert adapter.columnCount(adapter.index(0, 0)) == 0
    assert adapter.headerData(0, Qt.Horizontal) == 'X'
    assert adapter.headerData(1, Qt.Horizontal) == 'Y'
    assert adapter.headerData(0, Qt.Vertical) == '1'
    index = adapter.index(0, 1)
    assert index.isValid() and adapter.data(index) == ''
    assert adapter.flags(index) & Qt.ItemIsEditable
    assert adapter.data(QModelIndex()) is None
    assert adapter.flags(QModelIndex()) == Qt.NoItemFlags

    events = []
    adapter.dataChanged.connect(lambda a, b, roles: events.append((a, b, roles)))
    assert adapter.setData(index, '12.5')
    assert data.cell_text(0, 1) == '12.5'
    assert adapter.data(index, Qt.EditRole) == '12.5'
    assert len(events) == 1 and events[0][0] == index
    assert not adapter.setData(index, '12.5')
    assert not adapter.setData(index, 'other', Qt.DisplayRole)
    assert len(events) == 1


def test_model_paste_growth_signals_are_bounded_and_snapshot_is_not_copied():
    source_points = [[float(i), float(i * 2)] for i in range(50_000)]
    sheet = ReferenceTableModel()
    sheet.load_series([{'name': 'Large', 'points': source_points}])
    adapter = ReferenceWorksheetQtModel(sheet)
    assert sheet._source_points is source_points
    assert adapter.rowCount() == 50_000
    assert adapter.data(adapter.index(49_999, 1)) == '99998'
    assert sheet._overrides == {}

    insertions = []
    adapter.rowsAboutToBeInserted.connect(
        lambda _parent, first, last: insertions.append(('before', first, last, adapter.rowCount())))
    adapter.rowsInserted.connect(
        lambda _parent, first, last: insertions.append(('after', first, last, adapter.rowCount())))
    sheet.ensure_size(50_010)
    assert adapter.rowCount() == 50_000
    assert adapter.synchronize_row_count()
    assert insertions == [('before', 50_000, 50_009, 50_000),
                          ('after', 50_000, 50_009, 50_010)]
    assert not adapter.synchronize_row_count()
    assert sheet._overrides == {}


def test_model_reset_invalidates_persistent_indexes_and_rebinds_source():
    sheet = ReferenceTableModel()
    adapter = ReferenceWorksheetQtModel(sheet)
    old_index = QPersistentModelIndex(adapter.index(0, 0))
    events = []
    adapter.modelReset.connect(lambda: events.append('reset'))
    replacement = ReferenceTableModel(rows=4)
    replacement.paste('1\t2\n3\t4')
    adapter.reset_worksheet(replacement)
    assert events == ['reset']
    assert not old_index.isValid()
    assert adapter.worksheet is replacement
    assert adapter.rowCount() == 4
    assert adapter.data(adapter.index(1, 1)) == '4'


def test_model_notifies_sparse_clear_and_shrink_without_materializing_rows():
    sheet = ReferenceTableModel(rows=120)
    adapter = ReferenceWorksheetQtModel(sheet)
    events = []
    adapter.dataChanged.connect(lambda first, last, _roles: events.append((first.row(), last.row())))
    assert adapter.notify_cells_changed(20, 90)
    assert events == [(20, 90)]
    assert not sheet._overrides
    assert not adapter.notify_cells_changed(150, 200)
    assert events == [(20, 90)]
    # The model can also publish removals for a source whose row count shrinks.
    removed = []
    adapter.rowsRemoved.connect(lambda _parent, first, last: removed.append((first, last)))
    sheet._row_count = 20
    assert adapter.synchronize_row_count()
    assert removed == [(20, 119)]
    assert adapter.rowCount() == 20
