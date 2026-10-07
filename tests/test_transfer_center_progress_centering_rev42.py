from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "transfer_center_form.py"


def test_transfer_progress_centering_is_deferred_and_retried():
    source = FORM.read_text(encoding="utf-8")
    assert '_pending_progress_recenter = set()' in source
    assert 'def _schedule_progress_text_center(self, row_id, retries=3):' in source
    assert 'self.view.after(0, lambda _row_id=row_id, _retry=retries: self._center_progress_text(_row_id, _retry))' in source
    assert 'if width <= 8:' in source
    assert 'self.view.after(16, lambda _row_id=row_id, _retry=retry - 1: self._center_progress_text(_row_id, _retry))' in source
    assert 'self._schedule_progress_text_center(row_id, retries=4)' in source
    assert 'callback=lambda *_args, _row_id=row_id: self._schedule_progress_text_center(_row_id)' in source
