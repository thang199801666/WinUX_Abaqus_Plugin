from pathlib import Path
import ast
import re

ROOT = Path(__file__).resolve().parents[1]


def _source(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def _dpg_calls(source):
    tree = ast.parse(source)
    return sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "dpg"
        for node in ast.walk(tree)
    )


def test_explorer_and_console_use_public_theme_contracts():
    for relative in ("WinUx/ui/components/explorer_rendering.py", "WinUx/dialogs/console_form.py"):
        source = _source(relative)
        assert "dpg.add_theme_color" not in source
        assert "dpg.add_theme_style" not in source
        assert "dpg.theme_component" not in source


def test_custom_canvas_hotspots_use_qcanvas_and_qpainter_not_raw_draw_primitives():
    files = (
        "WinUx/ui/components/explorer_rendering.py",
        "WinUx/dialogs/console_form.py",
        "WinUx/plotdigitizer/ui/dialog.py",
        "WinUx/plotdigitizer/ui/markers.py",
    )
    joined = "\n".join(_source(path) for path in files)
    assert "QPainter" in joined and "QCanvas" in joined
    for primitive in (
        "draw_rectangle", "draw_circle", "draw_line", "draw_text",
        "draw_image", "draw_triangle", "draw_quad", "draw_polygon",
    ):
        assert f"dpg.{primitive}" not in joined


def test_plot_marker_renderer_has_no_backend_import():
    source = _source("WinUx/plotdigitizer/ui/markers.py")
    assert "DearUIQt.backends" not in source
    assert not re.search(r"\bdpg\.", source)


def test_actual_renderer_leakage_is_lower_than_r83_ast_baseline():
    calls = 0
    files = 0
    direct_imports = []
    for path in (ROOT / "WinUx").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        count = _dpg_calls(source)
        if count:
            calls += count
            files += 1
        if re.search(r"^\s*(?:from|import)\s+dearpygui\b", source, re.MULTILINE):
            direct_imports.append(path)
    assert direct_imports == []
    assert calls <= 1710
    assert files <= 52
