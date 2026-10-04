import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"
SHARED_NAMES = {
    "SharedScrollerMetrics",
    "SharedScrollerPalette",
    "add_dpg_scroller_style",
    "configure_ttk_scroller_styles",
    "make_ttk_scroller",
    "ttk_scroller_style_name",
    "dpg_window_rect",
}


def _imports_from_shared(tree):
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("shared_scroller"):
            imported.update(alias.asname or alias.name for alias in node.names)
    return imported


def _used_names(tree):
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


def test_every_shared_scroller_symbol_is_explicitly_imported_where_used():
    failures = []
    for path in WINUX.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        used = _used_names(tree) & SHARED_NAMES
        if not used:
            continue
        if path.name == "shared_scroller.py":
            continue
        imported = _imports_from_shared(tree)
        missing = used - imported
        if missing:
            failures.append((str(path.relative_to(ROOT)), sorted(missing)))
    assert not failures, failures


def test_explorer_list_view_imports_both_shared_scroller_symbols_used_at_startup():
    path = WINUX / "components" / "explorer_list_view.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported = _imports_from_shared(tree)
    assert "SharedScrollerMetrics" in imported
    assert "add_dpg_scroller_style" in imported
