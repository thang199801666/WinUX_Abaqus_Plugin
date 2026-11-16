"""Static/portable contract for shared form-control polish."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = (ROOT / "DearUIQt" / "gui" / "style.py").read_text(encoding="utf-8")
EDITORS = (ROOT / "DearUIQt" / "widgets" / "editors.py").read_text(encoding="utf-8")


def test_checkbox_uses_soft_hover_and_small_rounding():
    assert "hover = p.HIGHLIGHT_HOVER" in STYLE
    assert "active = p.HIGHLIGHT_SOFT" in STYLE
    assert "mvStyleVar_FrameRounding, 2" in STYLE
    assert "mvStyleVar_ItemInnerSpacing, 7, 3" in STYLE


def test_radio_spacing_matches_checkbox_caption_lane():
    assert "mvStyleVar_ItemInnerSpacing, 7, 4" in STYLE
    assert "dearuiqt.qt.radio.{}{}" in STYLE


def test_spin_shell_uses_shared_rounding_and_backend_metrics():
    assert "mvStyleVar_ChildRounding, metrics.frame_rounding" in STYLE
    assert "metrics = metrics_for_backend(backend)" in EDITORS
    assert '"height": metrics.control_height' in EDITORS
