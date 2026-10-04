"""Regression guard for the low-risk Explorer render caches.

The native Dear PyGui extension is intentionally not imported in portable CI.
These source contracts ensure polling/selection paths retain their skip logic;
feature-surface and interaction tests protect the externally visible behavior.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "WinUx" / "components"


def test_metadata_refresh_skips_unchanged_native_updates():
    source = (ROOT / "explorer_rendering.py").read_text(encoding="utf-8")
    assert 'cached_values = row.setdefault("values", {})' in source
    assert 'if cached_values.get(key) != value:' in source
    assert 'if row.get("icon_texture") != texture:' in source


def test_row_visual_refresh_is_signature_cached():
    source = (ROOT / "explorer_rendering.py").read_text(encoding="utf-8")
    assert '"values": {}' in source
    assert '"visual_signature": None' in source
    assert 'signature = (fill, border, float(thickness), text_color)' in source
    assert 'if row.get("visual_signature") == signature:' in source
