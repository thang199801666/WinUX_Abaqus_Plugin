"""QFileDialog polish guards for 1.1.14."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"
STYLE = ROOT / "WinUx" / "dialogs" / "folder_browser_style.py"


def test_details_secondary_cells_follow_qabstractitemview_selection_palette():
    source = FORM.read_text(encoding="utf-8")
    assert "qt_item_text_theme" in source
    assert "self.detail_texts" in source
    assert "def _sync_selection_visuals" in source


def test_sidebar_uses_pixel_based_qfontmetrics_style_elision():
    source = FORM.read_text(encoding="utf-8")
    assert "def _text_width" in source
    assert "dpg.get_text_size" in source
    assert "QFontMetrics::elidedText-like" in source


def test_sidebar_section_spacing_is_centralized_with_browser_metrics():
    source = FORM.read_text(encoding="utf-8")
    style = STYLE.read_text(encoding="utf-8")
    assert "METRICS.sidebar_section_gap" in source
    assert "sidebar_section_gap: int = 8" in style
