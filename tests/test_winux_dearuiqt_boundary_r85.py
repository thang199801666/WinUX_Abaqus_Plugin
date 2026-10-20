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


def test_folder_address_bar_is_now_backend_free_composite_widget():
    source = _source("WinUx/dialogs/folder_browser_address.py")
    assert "DearUIQt.backends" not in source
    assert "dpg." not in source
    for api in ("QImageView", "QFontMetrics", "QHBoxLayout", "line_edit_widget"):
        assert api in source


def test_folder_browser_and_splitter_reduce_backend_leakage_from_r84():
    assert _dpg_calls(_source("WinUx/dialogs/local_folder_form.py")) <= 95
    assert _dpg_calls(_source("WinUx/ui/behaviors/splitter_behavior.py")) <= 64
    splitter = _source("WinUx/ui/behaviors/splitter_behavior.py")
    for raw in ("dpg.get_mouse_pos", "dpg.get_mouse_drag_delta", "dpg.set_mouse_cursor",
                "dpg.get_viewport_client_width", "dpg.get_viewport_client_height"):
        assert raw not in splitter


def test_r85_global_backend_boundary_moves_toward_pure_dearuiqt():
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
    assert calls <= 1520
    assert files <= 51


def test_main_view_and_plot_digitizer_use_dearuiqt_system_runtime_boundaries():
    view = _source("WinUx/view.py")
    for raw in ("dpg.create_context", "dpg.create_viewport", "dpg.setup_dearpygui",
                "dpg.render_dearpygui_frame", "dpg.destroy_context",
                "dpg.mvThemeCol_TitleBg", "dpg.mvStyleVar_WindowPadding"):
        assert raw not in view
    assert "QGuiRuntime" in view
    assert "compact_layout_surface_theme" in view
    assert "floating_window_theme" in view

    plot = _source("WinUx/plotdigitizer/ui/dialog.py")
    for raw in ("dpg.get_mouse_pos", "dpg.get_frame_count",
                "dpg.get_viewport_width", "dpg.get_viewport_height",
                "dpg.is_key_down"):
        assert raw not in plot
    assert "QCursor" in plot and "QKeyboard" in plot
