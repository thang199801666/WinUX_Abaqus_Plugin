from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FakeBackend:
    mvMouseButton_Left = 0

    def __init__(self):
        self.next = 100
        self.config = {}
        self.values = {}
        self.children = {}
        self.parents = {}
        self.handlers = {}
        self.draws = {}

    def _new(self, **kwargs):
        tag = self.next
        self.next += 1
        parent = kwargs.get("parent")
        self.config[tag] = dict(kwargs)
        self.values[tag] = kwargs.get("default_value")
        self.children.setdefault(tag, [])
        self.parents[tag] = parent
        if parent is not None:
            self.children.setdefault(parent, []).append(tag)
        return tag

    def add_child_window(self, **kwargs): return self._new(**kwargs)
    def add_group(self, **kwargs): return self._new(**kwargs)
    def add_selectable(self, **kwargs): return self._new(**kwargs)
    def add_drawlist(self, *args, **kwargs): return self._new(**kwargs)
    def draw_triangle(self, *args, **kwargs): return self._new(**kwargs)
    def draw_text(self, pos, text, **kwargs): return self._new(pos=pos, text=text, **kwargs)
    def get_text_size(self, text): return (len(text) * 7, 13)
    def draw_image(self, *args, **kwargs):
        tag = self._new(**kwargs)
        self.draws[tag] = dict(kwargs)
        return tag
    def add_item_handler_registry(self): return self._new()
    def add_item_clicked_handler(self, **kwargs): return self._new(**kwargs)
    def bind_item_handler_registry(self, item, registry): self.handlers[item] = registry
    def bind_item_theme(self, item, theme): self.config.setdefault(item, {})["theme"] = theme
    def does_item_exist(self, tag): return tag in self.config
    def get_item_children(self, tag, slot=1): return list(self.children.get(tag, ()))
    def delete_item(self, tag, children_only=False):
        if children_only:
            for child in list(self.children.get(tag, ())):
                self.delete_item(child)
            self.children[tag] = []
            return
        for child in list(self.children.get(tag, ())):
            self.delete_item(child)
        parent = self.parents.pop(tag, None)
        if parent in self.children and tag in self.children[parent]:
            self.children[parent].remove(tag)
        self.children.pop(tag, None)
        self.config.pop(tag, None)
        self.values.pop(tag, None)
    def set_value(self, tag, value): self.values[tag] = value
    def get_value(self, tag): return self.values.get(tag)
    def configure_item(self, tag, **kwargs): self.config.setdefault(tag, {}).update(kwargs)
    def get_item_rect_size(self, tag): return (220, 24)
    def get_item_rect_min(self, tag):
        parent = self.parents.get(tag)
        if parent is None:
            return (0, 0)
        siblings = self.children.get(self.parents.get(parent), [])
        try:
            row = siblings.index(parent)
        except ValueError:
            row = 0
        return (0, row * 24)
    def is_mouse_button_double_clicked(self, button): return False
    def get_y_scroll(self, tag): return 0
    def set_y_scroll(self, tag, value): pass
    def move_item(self, tag, **kwargs): self.config.setdefault(tag, {}).update(kwargs)
    def focus_item(self, tag): pass
    def get_item_state(self, tag): return {}
    def is_key_down(self, key): return False


def test_qtreewidget_flat_places_preserves_group_model_and_visible_walk():
    from DearUIQt.modelview import QTreeWidget, QTreeWidgetItem

    ui = FakeBackend()
    tree = QTreeWidget(backend=ui)
    section = QTreeWidgetItem(tree, ['Computer'])
    drive = QTreeWidgetItem(section, ['C:'])
    section.setExpanded(True)
    tree.setRootSectionsVisible(False)
    assert tree.nativeItem(section) is None
    assert tree.nativeItem(drive) is not None
    assert tree._walk() == [(drive, 0)]
    assert tree._walk(all_items=True) == [(section, 0), (drive, 1)]
    tree.setRootSectionsVisible(True)
    assert tree.nativeItem(section) is not None
    assert drive.parent() is section


def test_qtreewidget_owns_hierarchy_roles_selection_and_expand_state():
    from DearUIQt.core import Qt
    from DearUIQt.modelview import QTreeWidget, QTreeWidgetItem

    ui = FakeBackend()
    tree = QTreeWidget(backend=ui, row_height=24)
    root = QTreeWidgetItem(tree, ["Quick access"])
    home = QTreeWidgetItem(root, ["Home"])
    home.setData(0, Qt.UserRole, "/home/user")
    home.setIcon(0, "folder-texture")
    root.setExpanded(True)

    assert tree.topLevelItemCount() == 1
    assert root.childCount() == 1 and root.child(0) is home
    assert home.parent() is root and home.treeWidget() is tree
    assert home.data(0, Qt.UserRole) == "/home/user"
    assert tree.nativeItem(home) is not None
    assert ui.config[tree.nativeItem(home)]["user_data"] == "/home/user"

    changes = []
    tree.currentItemChanged.connect(lambda current, previous: changes.append((current, previous)))
    assert tree.setCurrentItem(home)
    assert tree.currentItem() is home and home.isSelected()
    assert changes[-1][0] is home

    tree.collapseItem(root)
    assert not root.isExpanded()
    assert tree.nativeItem(home) is None
    tree.expandItem(root)
    assert root.isExpanded() and tree.nativeItem(home) is not None


def test_qtreewidget_updates_existing_icon_and_text_without_losing_item_identity():
    from DearUIQt.modelview import QTreeWidget, QTreeWidgetItem

    ui = FakeBackend()
    tree = QTreeWidget(backend=ui)
    item = QTreeWidgetItem(tree, ["C:\\"])
    item.setIcon(0, "drive-a")
    native = tree.nativeItem(item)
    visual = tree._rendered[item]
    image = visual["icon"]
    item.setText(0, "System (C:)")
    item.setIcon(0, "drive-b")
    assert tree.nativeItem(item) == native
    assert "System (C:)" in ui.config[native]["label"]
    assert ui.config[image]["texture_tag"] == "drive-b"


def test_qlistwidget_supports_transient_item_widget_editor():
    from DearUIQt.modelview import QListWidget, QListWidgetItem
    from DearUIQt.widgets import QLineEdit

    ui = FakeBackend()
    # Minimal native editor surface needed by QLineEdit.
    ui.add_input_text = lambda **kwargs: ui._new(**kwargs)
    ui.add_item_handler_registry = lambda: ui._new()
    ui.add_item_focus_handler = lambda **kwargs: ui._new(**kwargs)
    ui.add_item_activated_handler = lambda **kwargs: ui._new(**kwargs)
    ui.add_item_deactivated_handler = lambda **kwargs: ui._new(**kwargs)

    view = QListWidget(backend=ui)
    one = QListWidgetItem("One", view)
    two = QListWidgetItem("Two", view)
    editor = QLineEdit("One", parent=view, backend=ui)
    view.setItemWidget(one, editor)
    assert view.itemWidget(one) is editor
    assert ui.config[view.items[one.key]]["show"] is False
    assert view.removeItemWidget(one) is editor
    assert ui.config[view.items[one.key]]["show"] is True
    assert two is view.item(1)


def test_r78_winux_uses_tree_and_list_widgets_without_raw_selectables():
    local = (ROOT / "WinUx/dialogs/local_folder_form.py").read_text(encoding="utf-8")
    reference = (ROOT / "WinUx/dialogs/reference_chart_form.py").read_text(encoding="utf-8")
    view = (ROOT / "WinUx/view.py").read_text(encoding="utf-8")
    all_winux = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (ROOT / "WinUx").rglob("*.py")
    )
    assert "QTreeWidget(" in local and "QTreeWidgetItem(" in local
    assert "self._saved_list_view = self.own_widget(QListWidget(" in reference
    assert "setItemWidget(rename_item" in reference
    assert "dpg.add_selectable(" not in all_winux
    assert "QToolButton(" in view


def test_r78_public_exports_roles_and_version():
    import DearUIQt
    from DearUIQt import QAbstractItemDelegate, QStyledItemDelegate, QTreeWidget, QTreeWidgetItem
    from DearUIQt.QtWidgets import QTreeWidget as QtWidgetsTree
    from DearUIQt.core import Qt

    assert tuple(map(int, DearUIQt.__version__.split("."))) >= (1, 17, 0)
    assert QtWidgetsTree is QTreeWidget
    assert QTreeWidgetItem is not None
    assert issubclass(QStyledItemDelegate, QAbstractItemDelegate)
    assert Qt.DecorationRole == 1
    assert Qt.ToolTipRole == 3
    assert Qt.CheckStateRole == 10
