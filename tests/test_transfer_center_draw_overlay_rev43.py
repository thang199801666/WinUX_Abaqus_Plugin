from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "transfer_center_form.py"


def test_transfer_center_percentage_uses_absolute_draw_overlay():
    source = FORM.read_text(encoding="utf-8")
    assert 'overlay=" "' in source
    assert 'progress_overlay = dpg.add_drawlist(' in source
    assert 'progress_text = dpg.draw_text(' in source
    assert '"progress_overlay": progress_overlay' in source
    assert '"progress_text_value": "0.0%"' in source
    assert 'x = max(0, int(round((float(width) - text_w) * 0.5)))' in source
    assert 'dpg.configure_item(label, pos=(x, y), text=text)' in source
    assert 'overlay, width=max(1, int(round(width)))' in source
