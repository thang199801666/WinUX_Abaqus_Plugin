from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "transfer_center_form.py"


def test_progress_text_is_recentered_after_layout_and_ratio_updates():
    source = FORM.read_text(encoding="utf-8")
    assert 'for row_id, row in self.row_widgets.items():' in source
    assert 'self._schedule_progress_recenter(row_id)' in source
    assert 'dpg.set_value(row["percentage"], "{:.1f}%".format(ratio * 100))' in source
    assert 'self._pending_progress_recenter.add(row_id)' in source
    assert 'self.view.after(0, self._flush_progress_recenter)' in source


def test_progress_text_cleanup_respects_removed_rows_and_dialog_destroy():
    source = FORM.read_text(encoding="utf-8")
    assert 'self._pending_progress_recenter.discard(args[0])' in source
    assert 'self._pending_progress_recenter.clear()' in source
    assert 'self._progress_recenter_scheduled = False' in source
