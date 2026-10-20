from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "transfer_center_form.py"
LOGIC = ROOT / "WinUx" / "dialogs" / "logic" / "transfer.py"


def test_progress_percent_uses_visible_glyph_metrics_and_baseline_correction():
    source = FORM.read_text(encoding="utf-8")
    assert 'PROGRESS_TEXT_Y_OFFSET = -2' in source
    assert 'value = str(dpg.get_value(row["percentage"]) or "0.0%")' in source
    assert 'measured = dpg.get_text_size(value)' in source
    assert '(host_height - text_height) // 2 + self.PROGRESS_TEXT_Y_OFFSET' in source


def test_completed_row_has_only_one_completed_label():
    source = LOGIC.read_text(encoding="utf-8")
    start = source.index("def mark_completed(self):")
    end = source.index("def finish(self, cancelled=False):", start)
    block = source[start:end]
    assert 'status="Completed"' in block
    assert 'statistics=""' in block
    assert 'statistics="Completed"' not in block


def test_empty_completion_statistics_collapses_the_secondary_line():
    source = FORM.read_text(encoding="utf-8")
    assert 'dpg.configure_item(row["stats"], show=bool(row["statistics"]))' in source
