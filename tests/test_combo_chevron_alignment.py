from pathlib import Path


def test_combo_chevron_uses_optical_vertical_offset():
    source = (Path(__file__).resolve().parents[1] / "DearUIQt" / "widgets" / "combo_field.py").read_text(encoding="utf-8")
    assert "((self.height - 2) / 2) - 1.0" in source
    assert "((height - 2) / 2) - 1.0" in source
