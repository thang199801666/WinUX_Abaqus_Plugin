from contextlib import contextmanager
from pathlib import Path

from DearUIQt.gui import QFontDatabase, QPaintLayer, QTextureRegistry
from DearUIQt.widgets import QRetainedItem, QToolTip


class FakeBackend:
    def __init__(self):
        self.items = {
            10: {"pos": (12, 34), "size": (120, 48), "show": True,
                 "value": "old", "parent": 1, "type": "mvAppItemType::mvInputText",
                 "yscroll": 15.0, "ymax": 90.0},
            20: {"pos": (0, 0), "size": (200, 100), "show": True},
        }
        self.focused = 10
        self.deleted = []
        self._next = 100

    def _id(self):
        self._next += 1
        return self._next

    def does_item_exist(self, tag):
        return tag in self.items

    def get_focused_item(self):
        return self.focused

    def get_item_rect_min(self, tag):
        return self.items[tag].get("pos", (0, 0))

    def get_item_rect_size(self, tag):
        return self.items[tag].get("size", (0, 0))

    def is_item_shown(self, tag):
        return self.items[tag].get("show", True)

    def is_item_hovered(self, tag):
        return False

    def is_item_active(self, tag):
        return False

    def configure_item(self, tag, **values):
        self.items[tag].update(values)
        if "width" in values or "height" in values:
            width, height = self.items[tag].get("size", (0, 0))
            self.items[tag]["size"] = (
                values.get("width", width), values.get("height", height))

    def set_value(self, tag, value):
        self.items[tag]["value"] = value

    def get_value(self, tag):
        return self.items[tag].get("value")

    def get_y_scroll(self, tag):
        return self.items[tag].get("yscroll", 0)

    def get_y_scroll_max(self, tag):
        return self.items[tag].get("ymax", 0)

    def set_y_scroll(self, tag, value):
        self.items[tag]["yscroll"] = value

    def get_x_scroll(self, tag):
        return 0

    def get_x_scroll_max(self, tag):
        return 0

    def set_x_scroll(self, tag, value):
        pass

    def get_item_parent(self, tag):
        return self.items[tag].get("parent")

    def get_item_info(self, tag):
        return {"type": self.items[tag].get("type", "")}

    def delete_item(self, tag, children_only=False):
        if children_only:
            return
        self.deleted.append(tag)
        self.items.pop(tag, None)

    @contextmanager
    def font_registry(self):
        tag = self._id()
        self.items[tag] = {}
        yield tag

    def add_font(self, path, size, parent=None):
        tag = self._id()
        self.items[tag] = {"path": path, "size": size, "parent": parent}
        return tag

    @contextmanager
    def texture_registry(self, show=False):
        tag = self._id()
        self.items[tag] = {"show": show}
        yield tag

    def add_static_texture(self, width, height, data, parent=None, tag=None):
        native = tag if tag is not None else self._id()
        self.items[native] = {"size": (width, height), "data": data, "parent": parent}
        return native

    @contextmanager
    def draw_layer(self, parent=None, after=None):
        tag = self._id()
        self.items[tag] = {"parent": parent, "after": after}
        yield tag

    @contextmanager
    def tooltip(self, target, **kwargs):
        tag = self._id()
        self.items[tag] = {"target": target, **kwargs}
        yield tag


def test_retained_item_focus_geometry_value_and_scroll_are_backend_neutral():
    backend = FakeBackend()
    item = QRetainedItem.focusedItem(backend=backend)
    assert item is not None and item.tag == 10
    rect = item.globalGeometry()
    assert (rect.x(), rect.y(), rect.width(), rect.height()) == (12, 34, 120, 48)
    assert item.itemType().endswith("mvInputText")
    assert item.parentItem() == 1
    assert item.value() == "old"
    item.setValue("new")
    assert backend.items[10]["value"] == "new"
    assert item.verticalScrollValue() == 15.0
    assert item.verticalScrollMaximum() == 90.0
    item.setVerticalScrollValue(27)
    assert backend.items[10]["yscroll"] == 27.0
    item.delete()
    assert 10 in backend.items, "non-owning retained adapters must not delete host items"


def test_owned_font_texture_layer_and_tooltip_resources_cleanup(tmp_path):
    backend = FakeBackend()
    font_path = tmp_path / "test.ttf"
    font_path.write_bytes(b"font")

    fonts = QFontDatabase(backend=backend)
    font = fonts.addApplicationFont(font_path, 14)
    assert font is not None and font.exists()
    font_id = font.nativeId()
    font.delete()
    assert font_id in backend.deleted
    fonts.delete()

    textures = QTextureRegistry(backend=backend)
    texture = textures.addStaticTexture(1, 1, [1.0, 1.0, 1.0, 1.0])
    assert texture.exists()
    texture_id = texture.nativeId()
    texture.delete()
    assert texture_id in backend.deleted
    textures.delete()

    layer = QPaintLayer(20, backend=backend)
    layer_id = layer.nativeId()
    assert layer.exists()
    layer.delete()
    assert layer_id in backend.deleted

    tooltip = QToolTip(20, backend=backend, show=False)
    tooltip_id = tooltip.tag
    assert tooltip.target() == 20
    tooltip.delete()
    assert tooltip_id in backend.deleted


def test_file_panel_hit_testing_uses_retained_geometry_without_renderer_calls():
    from DearUIQt.backends import use_backend
    from WinUx.ui.components.file_panel import FilePanel

    backend = FakeBackend()
    with use_backend(backend):
        assert FilePanel._point_in_item(10, 12, 34)
        assert FilePanel._point_in_item(10, 131, 81)
        assert not FilePanel._point_in_item(10, 132, 82)
        panel = FilePanel.__new__(FilePanel)
        panel.container = 10
        panel.body = None
        assert panel.screen_rect() == (12, 34, 132, 82)
