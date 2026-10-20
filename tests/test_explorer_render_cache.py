"""Regression guard for the low-risk Explorer render caches.

The native Dear PyGui extension is intentionally not imported in portable CI.
These source contracts ensure polling/selection paths retain their skip logic;
feature-surface and interaction tests protect the externally visible behavior.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "WinUx" / "ui" / "components"


def test_metadata_refresh_skips_unchanged_native_updates():
    source = (ROOT / "explorer_rendering.py").read_text(encoding="utf-8")
    assert 'cached_values = row.setdefault("values", {})' in source
    assert 'if cached_values.get(key) != value:' in source
    assert 'if row.get("icon_texture") != texture:' in source


def test_row_visual_refresh_is_split_into_background_and_text_caches():
    source = (ROOT / "explorer_rendering.py").read_text(encoding="utf-8")
    assert '"values": {}' in source
    assert '"visual_signature": None' in source
    assert 'background_signature = (fill, draw_border, draw_thickness)' in source
    assert 'row.get("visual_background_signature") != background_signature' in source
    assert 'row.get("visual_text_color") != text_color' in source
    assert 'selected.symmetric_difference(previous_selected)' in source
