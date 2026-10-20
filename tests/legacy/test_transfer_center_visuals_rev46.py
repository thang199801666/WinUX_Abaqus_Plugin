from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "transfer_center_form.py"
LOGIC = ROOT / "WinUx" / "dialogs" / "logic" / "transfer.py"
STYLE = ROOT / "DearUIQt" / "qt" / "style.py"


def test_transfer_center_uses_compact_list_theme_and_semantic_visual_state():
    source = FORM.read_text(encoding="utf-8")
    assert "transfer_list_theme" in source
    assert "transfer_status_text_theme" in source
    assert "progress_theme" in source
    assert 'dpg.bind_item_theme(self.rows_host, transfer_list_theme())' in source
    assert 'self._set_row_status_visuals(self.row_widgets[row_id], "queued", "Queued")' in source
    assert 'dpg.bind_item_theme(row["progress"], progress_theme(state=self._progress_theme_state(state)))' in source
    assert 'transfer_status_text_theme(state=self._text_theme_state(state))' in source


def test_transfer_center_uses_plain_text_titles_and_bulk_summary_refresh():
    source = FORM.read_text(encoding="utf-8")
    assert 'return "{}: {}".format(operation, name)' in source
    for codepoint in (0x2191, 0x2193, 0x2194, 0x21C4, 0x25CB, 0x21BB, 0x2713, 0x26A0, 0x2715, 0x2026, 0x2014):
        assert chr(codepoint) not in source
    assert 'ROWS_PER_TURN = 40' in source
    assert 'PROGRESS_HEIGHT = DialogMetrics.BUTTON_HEIGHT' in source
    assert 'transfer_progress_text_theme' in source
    assert 'self._summary_refresh_scheduled = False' in source
    assert 'def _schedule_summary_refresh(self):' in source
    assert 'summary += " - " + ", ".join(parts)' in source


def test_transfer_logic_emits_explicit_state_updates_for_row_visuals():
    source = LOGIC.read_text(encoding="utf-8")
    assert 'status=str(label), state=self.state' in source
    assert 'state="finalizing" if ratio >= 1.0 else "running"' in source
    assert 'state="completed"' in source
    assert 'state="failed"' in source
    assert 'state="cancelling"' in source
    assert 'state="cancelled"' in source
    assert 'state="skipped"' in source


def test_transfer_style_supports_dense_rows_and_semantic_status_colours():
    source = STYLE.read_text(encoding="utf-8")
    assert 'def transfer_list_theme(backend):' in source
    assert 'backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 0, 4)' in source
    assert 'backend.add_theme_style(backend.mvStyleVar_WindowPadding, 6, 4)' in source
    assert 'backend.add_theme_style(backend.mvStyleVar_ItemSpacing, 4, 2)' in source
    assert 'backend.add_theme_style(backend.mvStyleVar_CellPadding, 0, 0)' in source
    assert 'def transfer_status_text_theme(backend, *, state="normal"):' in source
    assert '"running": p.HIGHLIGHT' in source
    assert '"success": (26, 127, 55, 255)' in source
    assert '"error": p.DANGER' in source
    assert '"warning": (205, 132, 0, 255)' in source
