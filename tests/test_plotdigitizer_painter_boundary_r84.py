from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_marker_renderer_uses_dearuiqt_qpainter_not_backend():
    source = (ROOT / "WinUx/plotdigitizer/ui/markers.py").read_text(encoding="utf-8")
    assert "from DearUIQt.gui import QPainter" in source
    assert "DearUIQt.backends" not in source
    assert "dpg." not in source
    for method in ("drawEllipse", "drawRect", "drawTriangle", "drawQuad", "drawLine", "drawPolygon"):
        assert method in source
