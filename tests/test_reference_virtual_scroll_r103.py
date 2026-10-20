"""Reference worksheet full-row population stays off the dialog's first frame."""
from WinUx.services.reference_charts import ReferenceTableModel
from WinUx.ui.components.reference_data_table import ReferenceDataTable


class _FakeTable:
    def __init__(self):
        self.rows = []

    def rowCount(self):
        return len(self.rows)

    def insertRow(self, row):
        assert row == len(self.rows)
        self.rows.append([None, None, None])
        return row

    def removeRow(self, row):
        assert row == len(self.rows) - 1
        self.rows.pop()
        return True

    def item(self, row, column):
        return self.rows[row][column]

    def setItem(self, row, column, item):
        self.rows[row][column] = item
        return item


def _deferred_sheet(count=1000, batch=8):
    sheet = ReferenceDataTable.__new__(ReferenceDataTable)
    sheet._closed = False
    sheet._disposed = False
    sheet.model = ReferenceTableModel()
    sheet.model.load_series([{
        "name": "Large",
        "points": [[index, index * 2] for index in range(count)],
    }])
    sheet._table_widget = _FakeTable()
    sheet._active_position = None
    sheet._active_editor = None
    sheet._population_generation = 1
    sheet._population_cursor = 0
    sheet._population_target = count
    sheet._population_scheduled = True
    sheet._population_complete = False
    sheet._population_batch_hint = batch
    sheet._pending_focus = None
    sheet._scroll_to_end_when_ready = False
    sheet._update_population_label = lambda: None
    pending = []
    sheet.after = lambda _delay, callback, *args: pending.append((callback, args))
    return sheet, pending


def test_first_population_turn_is_bounded_not_full_dataset_build():
    sheet, pending = _deferred_sheet(10_000, batch=8)
    sheet._populate_batch(1)
    assert 0 < sheet.materialized_row_count() <= sheet.POPULATE_MAX_BATCH
    assert sheet.materialized_row_count() < sheet.model.row_count
    assert pending, "remaining native rows must be deferred to a later event-loop turn"


def test_deferred_population_eventually_materializes_every_model_row():
    sheet, pending = _deferred_sheet(1373, batch=32)
    sheet._populate_batch(1)
    turns = 1
    while pending:
        callback, args = pending.pop(0)
        callback(*args)
        turns += 1
        assert turns < 1000
    assert sheet.population_complete
    assert sheet.materialized_row_count() == 1373
    assert sheet._table_widget.item(0, 0).text() == "1"
    assert sheet._table_widget.item(1372, 0).text() == "1373"
    assert sheet._table_widget.item(1372, 1).text() == "1372"
    assert sheet._table_widget.item(1372, 2).text() == "2744"


def test_reference_table_uses_native_full_scroll_and_no_virtual_50_row_pool():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] /
              'WinUx/ui/components/reference_data_table.py').read_text(encoding='utf-8')
    assert 'QTableWidget(\n            0, 3' in source
    assert 'scroll_y=True' in source
    assert 'POPULATE_BUDGET_MS' in source
    assert 'self.after(1, self._populate_batch, generation)' in source
    assert 'QScrollBar' not in source
    assert '_editor_pool' not in source
