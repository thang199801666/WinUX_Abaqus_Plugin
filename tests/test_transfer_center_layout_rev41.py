from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRANSFER = ROOT / "WinUx" / "dialogs" / "transfer_center_form.py"
DIALOG = ROOT / "WinUx" / "dialogs" / "qt_dialog.py"
STYLE = ROOT / "WinUx" / "widgets" / "imgui_qt_style.py"


def test_transfer_center_has_roomier_button_spacing():
    source = TRANSFER.read_text(encoding="utf-8")
    assert "button_gap=10" in source
    assert "dpg.add_spacer(parent=row_parent, width=10)" in source
    assert "height=84" in source


def test_percentage_is_separate_centered_overlay():
    source = TRANSFER.read_text(encoding="utf-8")
    assert 'overlay=" "' in source
    assert 'progress_text = dpg.draw_text(' in source
    assert "def _center_progress_text" in source
    assert "dpg.configure_item(label, pos=(x, y), text=text)" in source
    assert "dpg.add_item_resize_handler" in source


def test_shared_button_box_accepts_custom_gap_without_changing_default():
    source = DIALOG.read_text(encoding="utf-8")
    assert "button_gap=None" in source
    assert "button_gap = DialogMetrics.BUTTON_GAP if button_gap is None" in source


def test_transfer_progress_overlay_host_is_transparent():
    source = STYLE.read_text(encoding="utf-8")
    assert "def transfer_progress_host_theme" in source
    assert "def transfer_progress_text_theme" in source
