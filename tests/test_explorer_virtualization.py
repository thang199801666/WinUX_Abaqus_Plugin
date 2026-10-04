from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
VIRTUALIZATION = ROOT / "WinUx" / "components" / "explorer_virtualization.py"
REGISTRY = ROOT / "WinUx" / "components" / "explorer_row_registry.py"
RENDERING = ROOT / "WinUx" / "components" / "explorer_rendering.py"
LAYOUT = ROOT / "WinUx" / "components" / "explorer_layout.py"
RENAME = ROOT / "WinUx" / "components" / "explorer_rename.py"


def _load_math_module():
    spec = importlib.util.spec_from_file_location("explorer_virtualization_math", VIRTUALIZATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_small_lists_keep_full_render_behavior():
    compute = _load_math_module().compute_render_window
    assert compute(120, 24, 0, 480, threshold=240, overscan=8) == (0, 120)


def test_large_lists_render_viewport_plus_overscan():
    compute = _load_math_module().compute_render_window
    assert compute(10_000, 24, 0, 480, threshold=240, overscan=8) == (0, 28)
    assert compute(10_000, 24, 24_000, 480, threshold=240, overscan=8) == (992, 1028)


def test_virtual_window_is_clamped_at_end_and_during_startup():
    compute = _load_math_module().compute_render_window
    assert compute(10_000, 24, 10**9, 480, threshold=240, overscan=8) == (9991, 10000)
    assert compute(10_000, 24, 0, 0, threshold=240, fallback_rows=64) == (0, 64)


def test_registry_reuses_rows_and_keeps_logical_index_lookup_contract():
    source = REGISTRY.read_text(encoding="utf-8")
    assert "reusable = list(old.values())" in source
    assert "self._bind_body_row(row, index)" in source
    assert "self._row_registry.get(int(index))" in source
    assert "self._destroy_body_row(row)" in source


def test_render_layout_and_rename_use_virtual_registry():
    rendering = RENDERING.read_text(encoding="utf-8")
    layout = LAYOUT.read_text(encoding="utf-8")
    rename = RENAME.read_text(encoding="utf-8")
    assert "self._sync_virtual_rows(force=True)" in rendering
    assert "row = self._row_for_index(index)" in rendering
    assert "if self._sync_virtual_rows():" in layout
    assert "rendered_row = self._row_for_index(index)" in rename
    # A full-item row creation loop would defeat virtualization.
    assert "for idx, item in enumerate(self.items):" not in rendering


def test_virtual_scroll_uses_row_only_layout_hot_path():
    layout = LAYOUT.read_text(encoding="utf-8")
    assert "def _layout_materialized_rows" in layout
    branch = "if self._sync_virtual_rows():\n                    self._layout_materialized_rows()"
    assert branch in layout
    assert "if self._sync_virtual_rows():\n                    self._layout_all()" not in layout
