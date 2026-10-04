"""Behavior/feature surface guard for incremental WinUx refactors.

This gate intentionally works from source AST rather than importing GUI/native
modules, so it also runs on non-Windows CI.  It protects the callable surface
that existed in v1.6.3 while allowing implementations to move between facade
classes and mixins/controllers.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "WinUx"
CONTRACT = json.loads(
    (Path(__file__).with_name("feature_surface_v1_6_3.json")).read_text(encoding="utf-8")
)


def _class_index():
    index = {}
    for path in PACKAGE.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                index[node.name] = (path, node)
    return index


def _signature(node):
    args = node.args
    return {
        "async": isinstance(node, ast.AsyncFunctionDef),
        "positional": [
            arg.arg for arg in list(args.posonlyargs) + list(args.args)
        ],
        "kwonly": [arg.arg for arg in args.kwonlyargs],
        "vararg": args.vararg.arg if args.vararg else None,
        "kwarg": args.kwarg.arg if args.kwarg else None,
    }


def _effective_methods(index, class_name, seen=None):
    if seen is None:
        seen = set()
    if class_name in seen or class_name not in index:
        return {}
    seen = set(seen)
    seen.add(class_name)
    _path, cls = index[class_name]
    methods = {}
    # Source-order base traversal mirrors normal mixin composition sufficiently
    # for a surface contract; class-local methods then override inherited ones.
    for base in cls.bases:
        if isinstance(base, ast.Name):
            methods.update(_effective_methods(index, base.id, seen))
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods[node.name] = _signature(node)
    return methods


def test_v163_callable_feature_surface_is_preserved():
    index = _class_index()
    for class_name, spec in CONTRACT["classes"].items():
        assert class_name in index, f"feature owner disappeared: {class_name}"
        current = _effective_methods(index, class_name)
        for method_name, signature in spec["methods"].items():
            assert method_name in current, f"{class_name}.{method_name} was lost"
            assert current[method_name] == signature, (
                f"{class_name}.{method_name} signature changed: "
                f"{signature!r} -> {current[method_name]!r}"
            )


def test_critical_feature_modules_still_exist():
    required = (
        "controllers/connection.py",
        "controllers/job_polling.py",
        "controllers/job_schedule.py",
        "controllers/schedule_manifest.py",
        "controllers/job_plot.py",
        "controllers/transfer.py",
        "services/odb_check.py",
        "services/odb_extract.py",
        "services/odb_history_live.py",
        "dialogs/floating_dialog.py",
        "platform/native_dialog_host.py",
        "services/server_notepad_process.py",
        "services/server_notepad_windowing.py",
        "services/server_notepad_state.py",
        "services/server_notepad_background.py",
        "services/server_notepad_loading.py",
        "services/server_notepad_save.py",
        "services/server_text.py",
        "services/remote_odb.py",
        "services/remote_transfer.py",
        "components/job_plots.py",
    )
    missing = [relative for relative in required if not (PACKAGE / relative).is_file()]
    assert not missing, f"critical feature modules missing: {missing}"


def test_explorer_pointer_dispatch_priority_contract():
    source = (PACKAGE / "components" / "explorer_pointer_dispatch.py").read_text(
        encoding="utf-8"
    )
    # These tokens encode the established gesture ownership order.  The exact
    # implementation may evolve, but protected/modal surfaces must resolve
    # before context/rename/header/body drag paths.
    ordered = (
        "if pointer_input_is_blocked(self):",
        "if _modal_input_is_blocked():",
        "if self._context_menu_is_visible():",
        "if _overlay_window_owns_input():",
        "if self._rename_active:",
        "if self._mouse_in_pinned_row():",
        "inside_header, local_x = self._header_mouse_position()",
        "body_pos = self._body_local_pos()",
        "idx = self._row_at_mouse()",
    )
    positions = [source.index(token) for token in ordered]
    assert positions == sorted(positions), "Explorer gesture priority changed"
    assert "if self._drag_origin_on_item:" in source
    assert "self._start_item_drag()" in source
    assert "self._start_rubberband()" in source


def test_font_bootstrap_and_modal_compatibility_exports_remain_available():
    facade = (PACKAGE / "components" / "explorer_list_view.py").read_text(encoding="utf-8")
    state = (PACKAGE / "components" / "explorer_input_state.py").read_text(encoding="utf-8")
    assert "def apply_windows_font(font_size=15):" in facade
    assert "register_modal_window, unregister_modal_window" in facade
    assert "def register_modal_window(tag):" in state
    assert "def unregister_modal_window(tag):" in state
