from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRANSFER = ROOT / "WinUx" / "dialogs" / "transfer_center_form.py"
DIALOG = ROOT / "DearUIQt" / "dialogs" / "qt_dialog.py"
STYLE = ROOT / "DearUIQt" / "qt" / "style.py"
THEME = ROOT / "DearUIQt" / "dialogs" / "theme.py"


def test_transfer_center_has_roomier_button_spacing():
    source = TRANSFER.read_text(encoding="utf-8")
    assert "button_gap=10" in source
    assert "ACTION_WIDTH = 86" in source
    assert "auto_resize_y=True" in source


def test_progressbar_and_cancel_button_share_the_same_height_contract():
    source = TRANSFER.read_text(encoding="utf-8")
    theme = THEME.read_text(encoding="utf-8")
    assert 'PROGRESS_HEIGHT = DialogMetrics.BUTTON_HEIGHT' in source
    assert 'progress = self.progress_bar(0.0, parent=progress_host, overlay="")' in source
    assert 'dpg.configure_item(progress, width=-1, height=self.PROGRESS_HEIGHT)' in source
    assert 'width=self.ACTION_WIDTH, height=self.PROGRESS_HEIGHT' in source
    assert 'BUTTON_HEIGHT = 26' in theme


def test_shared_button_box_accepts_custom_gap_without_changing_default():
    source = DIALOG.read_text(encoding="utf-8")
    assert "button_gap=None" in source
    assert "button_gap = DialogMetrics.BUTTON_GAP if button_gap is None" in source


def test_transfer_progress_overlay_host_and_text_theme_exist():
    source = STYLE.read_text(encoding="utf-8")
    assert "def transfer_progress_host_theme" in source
    assert "def transfer_progress_text_theme" in source
