import ast
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from DearUIQt.backends import use_backend
from DearUIQt.runtime import QGuiRuntime
from DearUIQt.widgets import QRetainedItem, QViewportCanvas


class FakeBackend:
    def __init__(self):
        self.items = {
            10: {"show": False, "state": {"rect_min": (3, 4), "rect_size": (20, 10)}},
            11: {"show": True},
            12: {"show": True},
        }
        self.children = {10: [11, 12]}
        self._next = 100
        self.bound_font = None
        self.deleted = []
        self.configured = []
        self.mouse = (40, 50)

    def does_item_exist(self, tag):
        return tag in self.items

    def is_item_shown(self, tag):
        return bool(self.items[tag].get("show", True))

    def configure_item(self, tag, **values):
        self.configured.append((tag, dict(values)))
        self.items[tag].update(values)

    def get_item_configuration(self, tag):
        return dict(self.items[tag])

    def get_item_state(self, tag):
        return dict(self.items[tag].get("state", {}))

    def get_item_children(self, tag, slot=1):
        return list(self.children.get(tag, ()))

    def get_item_rect_min(self, tag):
        return self.items[tag].get("state", {}).get("rect_min", (0, 0))

    def get_item_rect_size(self, tag):
        return self.items[tag].get("state", {}).get("rect_size", (0, 0))

    def delete_item(self, tag, children_only=False):
        if children_only:
            return
        self.deleted.append(tag)
        self.items.pop(tag, None)

    def bind_font(self, native):
        self.bound_font = native

    def add_viewport_drawlist(self, front=True, tag=None):
        native = tag or self._allocate()
        self.items[native] = {"show": True, "front": front}
        return native

    def _allocate(self):
        self._next += 1
        return self._next

    def draw_rectangle(self, p1, p2, parent=None, **kwargs):
        native = self._allocate()
        self.items[native] = {"pmin": p1, "pmax": p2, "parent": parent, **kwargs}
        return native

    def draw_text(self, pos, text, parent=None, **kwargs):
        native = self._allocate()
        self.items[native] = {"pos": pos, "text": text, "parent": parent, **kwargs}
        return native

    def bind_item_font(self, tag, font):
        self.items[tag]["font"] = font

    def get_text_size(self, text, **kwargs):
        return (max(1, len(str(text))) * 7, 15)

    def get_mouse_pos(self, local=False):
        return self.mouse


class FakeFont:
    def nativeId(self):
        return 77


def test_retained_existing_visibility_state_is_not_coalesced_away_and_children_are_owned_by_boundary():
    backend = FakeBackend()
    item = QRetainedItem(10, backend=backend)
    assert item.isVisible() is False
    item.show()
    assert backend.items[10]["show"] is True
    assert any(tag == 10 and values.get("show") is True for tag, values in backend.configured)
    assert item.nativeState()["rect_min"] == (3, 4)
    assert item.childIds() == (11, 12)
    assert [child.tag for child in item.childItems()] == [11, 12]


def test_runtime_binds_qfont_objects_without_exposing_backend_font_api():
    backend = FakeBackend()
    runtime = QGuiRuntime(backend)
    font = FakeFont()
    assert runtime.setApplicationFont(font)
    assert backend.bound_font == 77
    assert runtime.applicationFont() is font


def test_viewport_canvas_owns_overlay_surface_and_drag_preview_uses_public_dearuiqt():
    backend = FakeBackend()
    with use_backend(backend):
        canvas = QViewportCanvas(front=True, tag="overlay")
        assert canvas.exists()
        assert backend.items["overlay"]["front"] is True
        native = canvas.tag
        canvas.delete()
        assert native in backend.deleted

        from WinUx.ui.components.explorer_drag_preview import DragPreviewHelper
        helper = DragPreviewHelper("preview")
        helper.begin([SimpleNamespace(name="file.txt")])
        assert helper._canvas is not None and helper._canvas.exists()
        helper.update(True, "Target")
        panel = QRetainedItem(helper._parts["panel"], backend=backend)
        assert panel.isVisible()
        helper.end()
        assert not panel.isVisible()
        helper.destroy()



def test_explorer_hit_testing_consumes_retained_geometry_and_qcursor():
    from WinUx.ui.components.explorer_hit_testing import ExplorerHitTestingMixin

    backend = FakeBackend()
    backend.mouse = (10, 8)
    with use_backend(backend):
        class View(ExplorerHitTestingMixin):
            body_window = 10
            body_canvas = 10
            window_tag = 10
            pinned_canvas = 12
            HEADER_HEIGHT = 20
            SCROLLBAR_HIT_SIZE = 12
            _pinned_item = None
            _scroller_arrow_overlay = None

        view = View()
        assert view._safe_item_rect(10) == (3.0, 4.0, 23.0, 14.0)
        assert view._mouse_in_item(10)
        assert view._body_viewport_rect() == (3.0, 4.0, 23.0, 14.0)
        assert view._body_local_pos() == (7.0, 4.0)

def test_r92_migrated_modules_do_not_import_backend_or_call_dpg_directly():
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "WinUx/dialogs/transfer_center_form.py",
        root / "WinUx/ui/behaviors/console_docking.py",
        root / "WinUx/ui/components/console_renderer.py",
        root / "WinUx/view.py",
        root / "WinUx/ui/components/explorer_list_view.py",
        root / "WinUx/ui/components/explorer_hit_testing.py",
        root / "WinUx/ui/components/explorer_drag_preview.py",
    ]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        direct = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "dpg"
        ]
        backend_imports = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and (node.module or "").startswith("DearUIQt.backends")
        ]
        assert not direct, path
        assert not backend_imports, path


def test_r92_global_backend_boundary_is_below_300_calls_and_30_files():
    root = Path(__file__).resolve().parents[1]
    total = 0
    files = 0
    for path in (root / "WinUx").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        count = sum(
            1 for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "dpg"
        )
        if count:
            total += count
            files += 1
    assert total <= 282
    assert files <= 29
