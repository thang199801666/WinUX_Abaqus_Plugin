from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "transfer_center_form.py"


def test_transfer_progress_uses_shared_retained_bar_without_moving_overlay_text():
    source = FORM.read_text(encoding="utf-8")
    assert 'self.progress_bar(0.0, parent=progress_host, overlay="")' in source
    assert 'dpg.set_value(row["percentage"], "{:.1f}%".format(ratio * 100))' in source
    assert 'dpg.configure_item(row["progress"], overlay=' not in source
    assert 'wrapper.setFormat(overlay)' not in source
