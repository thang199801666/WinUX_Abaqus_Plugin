from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "job_schedule_form.py"


def test_job_schedule_header_is_owned_by_qtablewidget():
    source = FORM.read_text(encoding="utf-8")
    assert 'self.table_widget = self.own_widget(QTableWidget(' in source
    assert 'header_row=True' in source
    assert 'self.table_widget.setHorizontalHeaderLabels' in source
    assert 'with dpg.table_row(parent=self.table)' not in source
    assert 'dpg.add_table_column' not in source


def test_job_schedule_no_longer_requires_dialog_local_header_recenter_pass():
    source = FORM.read_text(encoding="utf-8")
    assert 'def _schedule_header_recenter(self):' in source
    assert 'self._header_recenter_scheduled = False' in source
    block = source[source.index('    def _schedule_header_recenter'):source.index('    def _target_window_height')]
    assert 'self.view.after(0, self._flush_header_recenter)' not in block
    assert 'dpg.set_item_pos' not in block


def test_job_schedule_rebuilds_only_qtablewidget_data_rows():
    source = FORM.read_text(encoding="utf-8")
    assert 'self.table_widget.setRowCount(0)' in source
    assert 'self.table_widget.insertRow(row_index)' in source
