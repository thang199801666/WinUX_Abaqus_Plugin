from pathlib import Path
import importlib.util
import ast
from contextlib import contextmanager
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
VIRTUALIZATION = ROOT / "WinUx" / "ui" / "components" / "explorer_virtualization.py"
REGISTRY = ROOT / "WinUx" / "ui" / "components" / "explorer_row_registry.py"
RENDERING = ROOT / "WinUx" / "ui" / "components" / "explorer_rendering.py"
LAYOUT = ROOT / "WinUx" / "ui" / "components" / "explorer_layout.py"
RENAME = ROOT / "WinUx" / "ui" / "components" / "explorer_rename.py"


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
    assert "self._sync_virtual_rows()" in layout
    assert "rendered_row = self._row_for_index(index)" in rename
    # A full-item row creation loop would defeat virtualization.
    assert "for idx, item in enumerate(self.items):" not in rendering


def test_scroll_does_not_rematerialize_rows():
    layout = LAYOUT.read_text(encoding="utf-8")
    assert "def _layout_materialized_rows" in layout
    branch = "if self._sync_virtual_rows():\n                    self._layout_materialized_rows()"
    assert branch not in layout
    assert "if self._sync_virtual_rows():\n                    self._layout_all()" not in layout


def test_each_pane_renders_all_rows_independently_of_scrolling():
    """All rows exist before scrolling, even if frame callbacks are replaced."""
    handlers = {}
    bindings = {}
    scroll = {"left": 0, "right": 0}
    frame_callbacks = {}
    active_registry = None

    @contextmanager
    def registry(tag):
        nonlocal active_registry
        active_registry = tag
        handlers[tag] = []
        yield tag
        active_registry = None

    def add_visible(callback, parent=None):
        handlers[parent or active_registry].append(callback)

    backend = SimpleNamespace(
        does_item_exist=lambda tag: True,
        item_handler_registry=registry,
        add_item_visible_handler=add_visible,
        bind_item_handler_registry=lambda item, tag: bindings.update({item: tag}),
        get_y_scroll=lambda item: scroll[item],
        get_item_rect_size=lambda item: (640, 480),
        get_text_size=lambda *args, **kwargs: (0, 0),
        get_frame_count=lambda: 1,
        set_frame_callback=lambda frame, callback: frame_callbacks.update({frame: callback}),
    )
    namespace = {"dpg": backend, "compute_render_window": _load_math_module().compute_render_window}
    # Load the actual mixins without requiring the native Windows DPG extension.
    for path in (LAYOUT, REGISTRY):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        tree.body = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        exec(compile(tree, str(path), "exec"), namespace)

    class View(namespace["ExplorerLayoutMixin"], namespace["ExplorerRowRegistryMixin"]):
        ROW_HEIGHT = 24

        def __init__(self, uid):
            self.uid = self.body_window = uid
            self.window_tag = uid + "_pane"
            self.header_canvas = uid + "_header"
            self.items = list(range(10_000))
            self._fonts = {}
            self._native_cursor_hook_active = True
            self.auto_width_enabled = False
            self._last_available_width = 640
            self._resize_key = None
            self.positions = {}
            self.created = 0
            self._reset_row_registry()
            self._sync_virtual_rows(force=True)
            self._layout_materialized_rows()
            self._install_auto_width_geometry_handlers()
            self._install_layout_watch()

        def _available_width(self):
            return 640

        def _create_body_row(self, index):
            self.created += 1
            return {"index": index}

        def _bind_body_row(self, row, index):
            row["index"] = index

        def _destroy_body_row(self, row):
            pass

        def _layout_materialized_rows(self):
            self.positions = {row["index"]: row["index"] * self.ROW_HEIGHT
                              for row in self._row_items}

    for method in (
        "_update_header_hover_state", "_update_resize_cursor", "_update_drag_cursor",
        "_maybe_handoff_drag_to_windows_shell", "_update_hover_state",
        "_process_inline_rename_focus", "_process_pending_slow_rename",
        "_drain_pending_external_drops",
    ):
        setattr(View, method, lambda self: None)

    views = [View("left"), View("right")]

    def render_frame():
        for view in views:
            for callback in handlers[bindings[view.body_window]]:
                callback(None, None, None)

    render_frame()
    assert all(0 in view.positions for view in views)
    # A resize/sort elsewhere can replace this slot on every frame.
    backend.set_frame_callback(2, lambda: None)
    for left_y, right_y in ((24_000, 48_000), (239_520, 96_000), (0, 0)):
        scroll.update(left=left_y, right=right_y)
        render_frame()
        for view in views:
            start, end = view._row_render_window()
            assert (start, end) == (0, 10_000)
            assert view._row_virtualization_active() is False
            assert set(view.positions) == set(range(start, end))
            assert set(view._row_registry) == set(range(10_000))
            first_visible = scroll[view.uid] // view.ROW_HEIGHT
            assert view.positions[first_visible] == scroll[view.uid]
            assert view.created == 10_000
