from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "transfer_center_form.py"


def test_transfer_progress_is_single_custom_draw_surface():
    source = FORM.read_text(encoding="utf-8")
    assert 'progress_canvas = dpg.add_drawlist(' in source
    assert 'progress_bg = dpg.draw_rectangle(' in source
    assert 'progress_fill = dpg.draw_rectangle(' in source
    assert 'progress_text = dpg.draw_text(' in source
    assert 'def _paint_progress(self, row_id, retry=0):' in source
    assert 'x = max(0, int(round((width - text_w) * 0.5)))' in source
    assert 'dpg.configure_item(label, pos=(x, y), text=text, color=text_color)' in source
    assert 'self.progress_bar(0.0, parent=progress_host' not in source
    assert 'dpg.set_value(row["progress"], values["ratio"])' not in source
