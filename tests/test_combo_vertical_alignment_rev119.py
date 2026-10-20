"""Regression: editable QComboBox text is optically centered in its 26 px shell."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_combo_preview_has_dedicated_vertical_padding_metric():
    style = (ROOT / "DearUIQt/gui/style.py").read_text(encoding="utf-8")
    field = (ROOT / "DearUIQt/widgets/combo_field.py").read_text(encoding="utf-8")
    legacy = (ROOT / "DearUIQt/widgets/combo_box.py").read_text(encoding="utf-8")

    assert "combo_editor_frame_pad_y: int = 2" in style
    assert "mvStyleVar_FramePadding, 7, METRICS.combo_editor_frame_pad_y" in field
    assert "height=self.height - 2" in field
    assert "height=max(1, height - 2)" in field
    assert "METRICS.combo_editor_frame_pad_y" in legacy
    assert "height=self.CONTROL_HEIGHT - 2 * METRICS.border_size" in legacy


def test_bundled_combo_sources_stay_identical_to_canonical_package():
    for name in ("combo_field.py", "combo_box.py"):
        assert (ROOT / "DearUIQt/widgets" / name).read_bytes() == (
            ROOT / "WinUx/DearUIQt/widgets" / name
        ).read_bytes()
