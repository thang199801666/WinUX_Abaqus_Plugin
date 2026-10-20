"""Native navigation updates only occur when their state changes."""
from tests.test_reference_virtual_scroll_r103 import _deferred_sheet
from WinUx.ui.components.reference_data_table import ReferenceDataTable


class _Control:
    def __init__(self):
        self.calls = []

    def setEnabled(self, value):
        self.calls.append(bool(value))

    def setText(self, value):
        self.calls.append(str(value))


def test_population_navigation_does_not_reconfigure_every_batch():
    sheet, pending = _deferred_sheet(100, batch=8)
    controls = [_Control() for _ in range(4)]
    sheet._first_page, sheet._previous_page, sheet._next_page, sheet._last_page = controls
    sheet._page_label = _Control()
    sheet._population_label_text = None
    sheet._update_population_label = lambda: ReferenceDataTable._update_population_label(sheet)
    sheet._navigation_enabled = None
    sheet._populate_batch(1)
    assert all(control.calls == [True] for control in controls)
    while pending:
        callback, args = pending.pop(0)
        callback(*args)
    assert all(control.calls == [True] for control in controls)
    assert sheet.population_complete
    assert sheet._page_label.calls[-1] == "100 rows"


def test_navigation_reconfigures_on_empty_to_nonempty_and_back():
    sheet, _pending = _deferred_sheet(0)
    controls = [_Control() for _ in range(4)]
    sheet._first_page, sheet._previous_page, sheet._next_page, sheet._last_page = controls
    sheet._page_label = _Control()
    sheet._population_label_text = None
    sheet._update_population_label = lambda: ReferenceDataTable._update_population_label(sheet)
    sheet._navigation_enabled = None
    sheet._update_population_label()
    sheet._update_population_label()
    assert all(control.calls == [False] for control in controls)
    sheet._table_widget.insertRow(0)
    sheet._update_population_label()
    sheet._update_population_label()
    assert all(control.calls == [False, True] for control in controls)
    sheet._table_widget.removeRow(0)
    sheet._update_population_label()
    assert all(control.calls == [False, True, False] for control in controls)
