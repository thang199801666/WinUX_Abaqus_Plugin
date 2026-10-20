from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "transfer_center_form.py"


def test_transfer_progress_and_cancel_button_share_a_single_visual_height_contract():
    source = FORM.read_text(encoding="utf-8")
    assert 'from DearUIQt.dialogs.theme import DialogMetrics' in source
    assert 'PROGRESS_HEIGHT = DialogMetrics.BUTTON_HEIGHT' in source
    assert 'height=self.PROGRESS_HEIGHT, border=False,' in source
    assert 'dpg.configure_item(progress, width=-1, height=self.PROGRESS_HEIGHT)' in source
    assert 'width=self.ACTION_WIDTH, height=self.PROGRESS_HEIGHT' in source


def test_transfer_progress_percentage_is_kept_fixed_in_the_visual_center():
    source = FORM.read_text(encoding="utf-8")
    assert 'def _safe_rect_size(item):' in source
    assert 'host_width, host_height = self._safe_rect_size(row["progress_host"])' in source
    assert 'measured = dpg.get_text_size(value)' in source
    assert 'x = max(0, (host_width - text_width) // 2)' in source
    assert 'PROGRESS_TEXT_Y_OFFSET = -2' in source
    assert 'y = max(0, (host_height - text_height) // 2 + self.PROGRESS_TEXT_Y_OFFSET)' in source
    assert 'dpg.set_item_pos(row["percentage"], (x, y))' in source
