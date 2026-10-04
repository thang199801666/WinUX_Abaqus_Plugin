"""Architecture guards for the decomposed ExplorerListView facade."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "WinUx" / "components"
FACADE = COMPONENTS / "explorer_list_view.py"
OWNERS = {
    "ExplorerColumnsMixin": COMPONENTS / "explorer_columns.py",
    "ExplorerRenameMixin": COMPONENTS / "explorer_rename.py",
    "ExplorerFileOperationsMixin": COMPONENTS / "explorer_file_operations.py",
    "ExplorerSelectionMixin": COMPONENTS / "explorer_selection.py",
    "ExplorerContextMenuMixin": COMPONENTS / "explorer_context_menu.py",
    "ExplorerDataViewMixin": COMPONENTS / "explorer_data_view.py",
    "ExplorerPointerCaptureMixin": COMPONENTS / "explorer_pointer_capture.py",
    "ExplorerRubberBandMixin": COMPONENTS / "explorer_rubber_band.py",
    "ExplorerDragDropMixin": COMPONENTS / "explorer_drag_drop.py",
    "ExplorerHitTestingMixin": COMPONENTS / "explorer_hit_testing.py",
    "ExplorerPointerDispatchMixin": COMPONENTS / "explorer_pointer_dispatch.py",
    "ExplorerLayoutMixin": COMPONENTS / "explorer_layout.py",
    "ExplorerRenderingMixin": COMPONENTS / "explorer_rendering.py",
}

def _methods(path, class_name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return {
        node.name for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

def test_explorer_facade_composes_behavior_mixins():
    source = FACADE.read_text(encoding="utf-8")
    for class_name in OWNERS:
        assert class_name in source
    assert "class ExplorerListView(" in source

def test_extracted_explorer_methods_have_single_owner():
    seen = {}
    for class_name, path in OWNERS.items():
        methods = _methods(path, class_name)
        assert methods, class_name
        for method in methods:
            assert method not in seen, f"{method}: {seen.get(method)} / {class_name}"
            seen[method] = class_name
    facade_methods = _methods(FACADE, "ExplorerListView")
    overlap = facade_methods & set(seen)
    assert not overlap, f"facade duplicates extracted methods: {sorted(overlap)}"

def test_rename_and_columns_are_owned_outside_facade():
    facade = FACADE.read_text(encoding="utf-8")
    assert "def begin_inline_rename" not in facade
    assert "def _auto_size_column_to_contents" not in facade
    assert "def begin_inline_rename" in OWNERS["ExplorerRenameMixin"].read_text(encoding="utf-8")
    assert "def _auto_size_column_to_contents" in OWNERS["ExplorerColumnsMixin"].read_text(encoding="utf-8")
    assert "def _on_context_menu_key" in OWNERS["ExplorerContextMenuMixin"].read_text(encoding="utf-8")
    assert "def _refresh_row_content" in OWNERS["ExplorerDataViewMixin"].read_text(encoding="utf-8")
    assert "def cancel_pointer_gesture" in OWNERS["ExplorerPointerCaptureMixin"].read_text(encoding="utf-8")
    assert "def _start_rubberband" in OWNERS["ExplorerRubberBandMixin"].read_text(encoding="utf-8")
    assert "def _maybe_handoff_drag_to_windows_shell" in OWNERS["ExplorerDragDropMixin"].read_text(encoding="utf-8")
    assert "def header_pointer_hit_test" in OWNERS["ExplorerHitTestingMixin"].read_text(encoding="utf-8")
    assert "def _on_left_down" in OWNERS["ExplorerPointerDispatchMixin"].read_text(encoding="utf-8")
    assert "def _on_left_down" not in facade
    assert "def _body_viewport_rect" not in facade
    assert "def _layout_all" in OWNERS["ExplorerLayoutMixin"].read_text(encoding="utf-8")
    assert "def _rebuild_draw_items" in OWNERS["ExplorerRenderingMixin"].read_text(encoding="utf-8")
    assert "def _layout_all" not in facade
    assert "def _rebuild_draw_items" not in facade


def test_keyboard_controller_is_composed_instead_of_inherited():
    tree = ast.parse(FACADE.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ExplorerListView")
    assert "ExplorerKeyboardController" not in {ast.unparse(base) for base in cls.bases}
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "_on_navigation_key")
    assert len(method.body) == 1
    assert ast.unparse(method.body[0]).startswith("return self._keyboard._on_navigation_key(")
    controller = (COMPONENTS / "explorer_keyboard.py").read_text(encoding="utf-8")
    assert "import dearpygui" not in controller
