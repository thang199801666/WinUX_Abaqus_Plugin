from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "job_schedule_form.py"
ADAPTER = ROOT / "WinUx" / "dialogs" / "floating_adapters.py"


def test_job_schedule_starts_compact_and_has_bounded_adaptive_height():
    source = FORM.read_text(encoding="utf-8")
    assert 'DEFAULT_HEIGHT = 260' in source
    assert 'MIN_WINDOW_HEIGHT = 230' in source
    assert 'MAX_WINDOW_HEIGHT = 500' in source
    assert 'EMPTY_TABLE_HEIGHT = 72' in source
    assert 'ROW_HEIGHT_HINT = 30' in source
    assert 'MAX_VISIBLE_ROWS = 7' in source
    assert 'preferred_size = (DEFAULT_WIDTH, DEFAULT_HEIGHT)' in source
    assert 'dpg.configure_item(self.tag, min_size=(680, self.MIN_WINDOW_HEIGHT))' in source
    assert 'header_row=True' in source
    assert 'QTableWidget(' in source
    assert 'freeze_rows=1' in source


def test_job_schedule_native_adapter_uses_the_compact_initial_height():
    source = ADAPTER.read_text(encoding="utf-8")
    block = source[source.index('class JobScheduleDialog(FloatingDialogController):'):]
    block = block[:block.index('    def refresh(self):')]
    assert 'width=840, height=260' in block


def test_job_schedule_geometry_rebalances_only_when_row_count_changes():
    source = FORM.read_text(encoding="utf-8")
    assert 'self._pending_geometry_row_count = None' in source
    assert 'self._last_geometry_row_count = None' in source
    assert 'def _schedule_geometry_balance(self, row_count):' in source
    assert 'row_count == self._last_geometry_row_count' in source
    assert 'self._pending_geometry_row_count = row_count' in source
    assert 'self.view.after(0, self._flush_geometry_balance)' in source
    assert 'row_count = self._pending_geometry_row_count' in source
    assert 'self._last_geometry_row_count = row_count' in source
    assert 'dpg.set_viewport_height(target + self.VIEWPORT_CHROME_HEIGHT)' in source
    assert 'self._schedule_geometry_balance(len(rows))' in source


def test_job_schedule_empty_state_and_columns_are_compact():
    source = FORM.read_text(encoding="utf-8")
    assert 'self._columns = (("Job", None), ("Action", 86), ("Scheduled time", 156),' in source
    assert '("Remaining", 88), ("Status", 92), ("Commands", 136))' in source
    assert 'width=58' in source
    assert 'width=68' in source
    assert 'No scheduled actions | Updates automatically' in source
    assert '1 scheduled action | Updates automatically' in source
    assert '{} scheduled actions | Updates automatically' in source
