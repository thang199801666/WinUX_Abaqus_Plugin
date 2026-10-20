from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "transfer_center_form.py"


def test_transfer_percentage_uses_fixed_center_overlay_logic_not_progress_overlay():
    source = FORM.read_text(encoding="utf-8")
    assert 'self._pending_progress_recenter = set()' in source
    assert 'self._progress_recenter_scheduled = False' in source
    assert 'def _schedule_progress_recenter(self, row_id):' in source
    assert 'def _flush_progress_recenter(self):' in source
    assert 'def _recenter_progress_text(self, row):' in source
    assert 'dpg.set_item_pos(row["percentage"], (x, y))' in source
    assert 'wrapper.setFormat(overlay)' not in source
