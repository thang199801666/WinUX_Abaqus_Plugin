"""Architecture guards for the decomposed WinUXView UI runtime."""
from pathlib import Path
import ast


ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "WinUx" / "view.py"
UI = ROOT / "WinUx" / "ui"
SPLITTER = UI / "splitter_layout.py"
PLOT = UI / "plot_docking.py"
CONSOLE = UI / "console_docking.py"
POINTER = UI / "pointer_routing.py"


def _method_names(path, class_name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return {
        node.name for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_view_facade_composes_ui_behavior_mixins():
    source = VIEW.read_text(encoding="utf-8")
    assert "SplitterLayoutMixin" in source
    assert "PlotDockingMixin" in source
    assert "ConsoleDockingMixin" in source
    assert "PointerRoutingMixin" in source
    assert "class WinUXView(" in source


def test_splitter_layout_owns_splitter_and_geometry_behavior():
    source = SPLITTER.read_text(encoding="utf-8")
    assert "class SplitterLayoutMixin" in source
    assert "def _pre_dispatch_splitter_input" in source
    assert "def _apply_split_layout" in source
    assert "def _drag_job_plot_splitter" in source
    assert "acquire_pointer_input(owner)" in source


def test_plot_and_console_docking_have_separate_owners():
    plot = PLOT.read_text(encoding="utf-8")
    console = CONSOLE.read_text(encoding="utf-8")
    assert "class PlotDockingMixin" in plot
    assert "def undock_job_plots" in plot
    assert "def dock_job_plots" in plot
    assert "class ConsoleDockingMixin" in console
    assert "def undock_console" in console
    assert "def dock_console" in console


def test_pointer_routing_is_separate_from_view_facade():
    view = VIEW.read_text(encoding="utf-8")
    pointer = POINTER.read_text(encoding="utf-8")
    assert "class PointerRoutingMixin" in pointer
    assert "def panel_and_point_at" in pointer
    assert "def panel_at" in pointer
    assert "def panel_and_point_at" not in view


def test_extracted_ui_mixins_do_not_duplicate_method_ownership():
    owners = {
        "SplitterLayoutMixin": SPLITTER,
        "PlotDockingMixin": PLOT,
        "ConsoleDockingMixin": CONSOLE,
        "PointerRoutingMixin": POINTER,
    }
    seen = {}
    for class_name, path in owners.items():
        for method in _method_names(path, class_name):
            assert method not in seen, (
                f"{method} is owned by both {seen[method]} and {class_name}"
            )
            seen[method] = class_name
