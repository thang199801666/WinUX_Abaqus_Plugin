from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "transfer_center_form.py"


def test_transfer_center_has_auto_balanced_window_height_contract():
    source = FORM.read_text(encoding="utf-8")
    assert 'DEFAULT_HEIGHT = 320' in source
    assert 'MIN_WINDOW_HEIGHT = 240' in source
    assert 'MAX_WINDOW_HEIGHT = 520' in source
    assert 'EMPTY_ROWS_HEIGHT = 40' in source
    assert 'ROW_HEIGHT_HINT = 86' in source
    assert 'CHROME_HEIGHT = 174' in source
    assert 'MAX_VISIBLE_ROWS = 4' in source
    assert 'self._window_balance_scheduled = False' in source
    assert 'self._last_auto_height = None' in source
    assert 'QtDialog.__init__(self, view, "Transfer Center", self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT, modal=False)' in source
    assert 'dpg.configure_item(self.tag, min_size=(620, self.MIN_WINDOW_HEIGHT))' in source


def test_transfer_center_recomputes_height_from_row_count_and_resizes_on_show_and_mutation():
    source = FORM.read_text(encoding="utf-8")
    assert 'def _target_window_height(self):' in source
    assert 'total_rows = len(self.row_widgets) + len(self._pending_row_creations)' in source
    assert 'rows_height = self.EMPTY_ROWS_HEIGHT' in source
    assert 'rows_height = min(total_rows, self.MAX_VISIBLE_ROWS) * self.ROW_HEIGHT_HINT' in source
    assert 'min(self.MAX_WINDOW_HEIGHT, self.CHROME_HEIGHT + rows_height)' in source
    assert 'def _schedule_window_balance(self):' in source
    assert 'self.view.after(0, self._flush_window_balance)' in source
    assert 'def _flush_window_balance(self):' in source
    assert 'self.height = target_height' in source
    assert 'self.resize(self.width, target_height)' in source
    assert 'self._schedule_window_balance()' in source.split('self._set_row_status_visuals(self.row_widgets[row_id], "queued", "Queued")', 1)[1]
    assert 'self._schedule_window_balance()' in source.split('dpg.delete_item(row["group"])', 1)[1]
    assert 'shown = super().show()' in source
    assert 'self._schedule_window_balance()' in source.split('shown = super().show()', 1)[1]
