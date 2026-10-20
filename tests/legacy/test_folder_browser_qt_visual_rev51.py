from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"


def test_sidebar_uses_distinct_alignment_for_sections_and_items():
    source = FORM.read_text(encoding="utf-8")
    assert "def _sidebar_section_text_y" in source
    assert "def _sidebar_item_text_y" in source
    assert "self._sidebar_section_text_y(title)" in source
    assert "self._sidebar_item_text_y(display_label)" in source


def test_sidebar_item_text_has_extra_upward_bias():
    source = FORM.read_text(encoding="utf-8")
    assert "return max(0, int(round((METRICS.sidebar_row_height - height) * 0.5)) - 2)" in source
    assert "return 2" in source
