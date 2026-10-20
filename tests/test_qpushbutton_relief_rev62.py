from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "DearUIQt" / "qt" / "style.py"


def test_qpushbutton_raised_face_is_visibly_distinct_from_panel_background():
    source = STYLE.read_text(encoding="utf-8")
    assert 'raised_face = (249, 249, 249, 255)' in source
    assert 'raised_border = (154, 154, 154, 255)' in source
    assert 'raised_hover = (242, 249, 254, 255)' in source
    assert 'raised_active = (218, 235, 248, 255)' in source
    assert 'face, hover, active = raised_face, raised_hover, raised_active' in source


def test_danger_button_keeps_clear_raised_danger_surface():
    source = STYLE.read_text(encoding="utf-8")
    assert 'face, hover, active = (250, 248, 247, 255), (255, 240, 237, 255), (246, 220, 216, 255)' in source
    assert 'border = p.FOCUS if focused else (184, 73, 61, 255)' in source
