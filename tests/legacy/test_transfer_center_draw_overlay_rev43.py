from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "transfer_center_form.py"


def test_transfer_center_percentage_is_a_real_text_widget_inside_progress_host():
    source = FORM.read_text(encoding="utf-8")
    assert 'progress = self.progress_bar(0.0, parent=progress_host, overlay="")' in source
    assert 'percentage = dpg.add_text("0.0%", parent=progress_host)' in source
    assert 'dpg.bind_item_theme(percentage, transfer_progress_text_theme(light=False))' in source
    assert 'dpg.set_value(row["percentage"], "{:.1f}%".format(ratio * 100))' in source
