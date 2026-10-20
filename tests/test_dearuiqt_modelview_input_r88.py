from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InputBackend:
    mvMouseButton_Left = 1
    mvMouseButton_Right = 2
    mvMouseButton_Middle = 3
    mvKey_A = 65
    mvKey_Delete = 127

    def __init__(self):
        self.next = 10
        self.items = set()
        self.bound_item = None
        self.global_handlers = []
        self.item_handlers = []
        self.deleted = []

    def _new(self):
        value = self.next
        self.next += 1
        self.items.add(value)
        return value

    @contextmanager
    def item_handler_registry(self):
        yield self._new()

    @contextmanager
    def handler_registry(self):
        yield self._new()

    def bind_item_handler_registry(self, target, registry):
        self.bound_item = (target, registry)

    def add_item_clicked_handler(self, **kwargs): self.item_handlers.append(("click", kwargs))
    def add_item_hover_handler(self, **kwargs): self.item_handlers.append(("hover", kwargs))
    def add_item_focus_handler(self, **kwargs): self.item_handlers.append(("focus", kwargs))
    def add_item_activated_handler(self, **kwargs): self.item_handlers.append(("activated", kwargs))
    def add_item_deactivated_handler(self, **kwargs): self.item_handlers.append(("deactivated", kwargs))
    def add_item_resize_handler(self, **kwargs): self.item_handlers.append(("resize", kwargs))
    def add_item_visible_handler(self, **kwargs): self.item_handlers.append(("visible", kwargs))

    def add_key_press_handler(self, **kwargs): self.global_handlers.append(("key", kwargs))
    def add_mouse_move_handler(self, **kwargs): self.global_handlers.append(("move", kwargs))
    def add_mouse_click_handler(self, **kwargs): self.global_handlers.append(("click", kwargs))
    def add_mouse_release_handler(self, **kwargs): self.global_handlers.append(("release", kwargs))
    def add_mouse_drag_handler(self, **kwargs): self.global_handlers.append(("drag", kwargs))
    def add_mouse_wheel_handler(self, **kwargs): self.global_handlers.append(("wheel", kwargs))

    def does_item_exist(self, item):
        return item in self.items

    def delete_item(self, item):
        self.deleted.append(item)
        self.items.discard(item)


class ThemeBackend:
    def __init__(self):
        self.next = 100
        self.items = set()
        self.colors = []
        self.styles = []
        self.bound_theme = None

    def __getattr__(self, name):
        if name.startswith("mv"):
            # Stable, non-None stand-in for renderer symbols.
            return name
        raise AttributeError(name)

    @contextmanager
    def theme(self, **kwargs):
        tag = kwargs.get("tag") or self.next
        self.next += 1
        self.items.add(tag)
        yield tag

    @contextmanager
    def theme_component(self, target, **kwargs):
        yield (target, kwargs)

    def add_theme_color(self, role, value):
        self.colors.append((role, value))

    def add_theme_style(self, role, *values):
        self.styles.append((role, values))

    def does_item_exist(self, item):
        return item in self.items

    def bind_theme(self, item):
        self.bound_theme = item


class ScrollBackend:
    def __init__(self):
        self.y = 0.0
        self.x = 0.0

    def get_y_scroll(self, _tag): return self.y
    def set_y_scroll(self, _tag, value): self.y = float(value)
    def get_x_scroll(self, _tag): return self.x
    def set_x_scroll(self, _tag, value): self.x = float(value)


def test_item_input_binding_owns_extended_item_lifecycle_handlers():
    from DearUIQt import QItemInputBinding, Qt

    backend = InputBackend()
    callback = lambda *_args, **_kwargs: None
    binding = (QItemInputBinding(123, backend=backend)
               .onClick(Qt.LeftButton, callback)
               .onHover(callback)
               .onFocus(callback)
               .onActivated(callback)
               .onDeactivated(callback)
               .onResize(callback)
               .onVisible(callback)
               .activate())

    assert backend.bound_item and backend.bound_item[0] == 123
    assert {kind for kind, _ in backend.item_handlers} == {
        "click", "hover", "focus", "activated", "deactivated", "resize", "visible"
    }
    registry = backend.bound_item[1]
    binding.delete()
    assert registry in backend.deleted


def test_global_input_binding_supports_mouse_move_and_native_key_roundtrip():
    from DearUIQt import QGlobalInputBinding, Qt

    backend = InputBackend()
    callback = lambda *_args, **_kwargs: None
    binding = (QGlobalInputBinding(backend=backend)
               .onMouseMove(callback)
               .onMouseClick(Qt.RightButton, callback)
               .onKeyPress(Qt.Key_A, callback)
               .activate())

    assert {kind for kind, _ in backend.global_handlers} == {"move", "click", "key"}
    assert QGlobalInputBinding.nativeKeyFor(Qt.Key_A, backend) == backend.mvKey_A
    assert QGlobalInputBinding.qtKeyForNative(backend.mvKey_A, backend) == Qt.Key_A
    binding.delete()


def test_qabstract_item_view_scroll_facade_uses_renderer_only_inside_dearuiqt():
    from DearUIQt.modelview.base import _QtAbstractItemView

    backend = ScrollBackend()
    view = object.__new__(_QtAbstractItemView)
    view.backend = backend
    view.tag = 77
    assert view.verticalScrollValue() == 0.0
    view.setVerticalScrollValue(12.5)
    assert view.verticalScrollValue() == 12.5
    view.scrollBy(3.0, 7.5)
    assert backend.x == 3.0 and backend.y == 20.0



class GeometryBackend:
    def __init__(self):
        self.rects = {101: ((10, 20), (120, 24)), 102: ((10, 44), (120, 24)), 201: ((2, 20), (16, 16))}
        self.hovered = set()
    def get_item_rect_min(self, item): return self.rects[item][0]
    def get_item_rect_size(self, item): return self.rects[item][1]
    def is_item_hovered(self, item): return item in self.hovered



def test_qtablewidget_column_sort_facade_targets_item_table_columns():
    from tests.test_dearuiqt_modelview_r79 import FakeBackend
    from DearUIQt import QTableWidget

    backend = FakeBackend()
    table = QTableWidget(0, 3, backend=backend)
    assert table.setColumnSortIndicator(1, False, default=True)
    column = table.nativeColumn(1)
    assert backend.config[column]["default_sort"] is True
    assert backend.config[column]["prefer_sort_ascending"] is False
    assert backend.config[column]["prefer_sort_descending"] is True
    assert table.setColumnSortable(2, False)
    assert backend.config[table.nativeColumn(2)]["no_sort"] is True

def test_qlistview_item_geometry_and_key_hit_testing_are_backend_neutral_to_callers():
    from DearUIQt.modelview import QtListView
    from DearUIQt import QPoint

    view = object.__new__(QtListView)
    view.backend = GeometryBackend()
    view.items = {"a": 101, "b": 102}
    view.checkboxes = {"a": 201}

    rect = view.itemGeometry("a")
    assert (rect.x(), rect.y(), rect.width(), rect.height()) == (2, 20, 128, 24)
    assert view.keyAt(QPoint(15, 25)) == "a"
    assert view.keyAt((15, 50)) == "b"
    assert view.keyAt((500, 500)) is None
    view.backend.hovered.add(102)
    assert view.keyAt((15, 50), require_hover=True) == "b"
    assert view.keyAt((15, 25), require_hover=True) is None

def test_fusion_desktop_theme_materializes_and_runtime_owns_application_theme():
    from DearUIQt.runtime import QGuiRuntime
    from DearUIQt.themes import fusion_desktop_theme

    backend = ThemeBackend()
    theme = fusion_desktop_theme(backend=backend, cache=False)
    assert theme in backend.items
    assert backend.colors
    assert backend.styles

    runtime = QGuiRuntime(backend)
    assert runtime.setApplicationTheme(theme)
    assert runtime.applicationTheme() == theme
    assert backend.bound_theme == theme


def test_r88_feature_code_uses_modelview_input_and_theme_boundaries():
    local = (ROOT / "WinUx/dialogs/local_folder_form.py").read_text(encoding="utf-8")
    plot = (ROOT / "WinUx/plotdigitizer/ui/dialog.py").read_text(encoding="utf-8")
    explorer = (ROOT / "WinUx/ui/components/explorer_list_view.py").read_text(encoding="utf-8")

    assert "QGlobalInputBinding" in local and 'getattr(self, "itemGeometry"' in local
    assert "self.setMinimumSize(700, 430)" in local
    assert ".onMouseClick(Qt.LeftButton, self._row_pointer_clicked)" in local
    assert "for binding in self._visual_hit_bindings:" in local
    assert "binding.delete()" in local
    install_keys = local.split("def _install_browser_keys", 1)[1].split("\n    def ", 1)[0]
    assert ".onKeyPress(key, self._browser_key" in install_keys
    assert "Qt.Key_F" in install_keys and "Qt.Key_Up" in install_keys
    assert "dpg.handler_registry" not in install_keys

    install_mouse = plot.split("def _install_mouse_handlers", 1)[1].split("\n    def ", 1)[0]
    assert "QGlobalInputBinding" in install_mouse
    assert "dpg.handler_registry" not in install_mouse

    theme_block = explorer.split("def apply_white_explorer_theme", 1)[1].split("\ndef ", 1)[0]
    assert "fusion_desktop_theme(" in theme_block
    assert "mvThemeCol_" not in theme_block
    assert "mvStyleVar_" not in theme_block


def test_r88_public_version():
    import DearUIQt
    assert tuple(map(int, DearUIQt.__version__.split("."))) >= (1, 27, 0)
