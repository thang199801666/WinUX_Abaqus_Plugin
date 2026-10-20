from contextlib import contextmanager
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


class FakeBackend:
    mvTable_SizingStretchProp = 1
    mvTable_SizingFixedFit = 2
    mvMouseButton_Left = 0
    mvKey_LControl = 10
    mvKey_RControl = 11
    mvKey_LShift = 12
    mvKey_RShift = 13
    mvKey_A = 14
    mvKey_Spacebar = 15
    mvKey_Up = 16
    mvKey_Down = 17
    mvKey_Home = 18
    mvKey_End = 19
    mvKey_Prior = 20
    mvKey_Next = 21

    def __init__(self):
        self.next = 100
        self.config = {}
        self.values = {}
        self.parents = {}
        self.children = {}
        self.slots = {}

    def _new(self, slot=1, **kwargs):
        tag = self.next
        self.next += 1
        parent = kwargs.get("parent")
        self.config[tag] = dict(kwargs)
        self.values[tag] = kwargs.get("default_value")
        self.parents[tag] = parent
        self.children.setdefault(tag, [])
        self.slots.setdefault(tag, {0: [], 1: []})
        if parent is not None:
            self.children.setdefault(parent, []).append(tag)
            self.slots.setdefault(parent, {0: [], 1: []})[slot].append(tag)
        return tag

    def add_table(self, **kwargs): return self._new(**kwargs)
    def add_table_column(self, **kwargs): return self._new(slot=0, **kwargs)
    def add_table_row(self, **kwargs): return self._new(slot=1, **kwargs)
    def add_selectable(self, **kwargs): return self._new(**kwargs)
    def add_text(self, value="", **kwargs):
        kwargs["default_value"] = str(value)
        return self._new(**kwargs)
    def add_child_window(self, **kwargs): return self._new(**kwargs)
    def add_window(self, **kwargs): return self._new(**kwargs)
    def add_input_text(self, **kwargs): return self._new(**kwargs)
    def does_item_exist(self, tag): return tag in self.config
    def configure_item(self, tag, **kwargs): self.config.setdefault(tag, {}).update(kwargs)
    def get_item_configuration(self, tag): return self.config.get(tag, {})
    def get_item_user_data(self, tag): return self.config.get(tag, {}).get("user_data")
    def get_item_children(self, tag, slot=1): return list(self.slots.get(tag, {}).get(slot, ()))
    def get_item_state(self, tag): return {}
    def get_item_rect_min(self, tag): return (0, 0)
    def get_item_rect_size(self, tag): return (400, 240)
    def get_mouse_pos(self, local=False): return (0, 0)
    def delete_item(self, tag):
        for child in list(self.children.get(tag, ())): self.delete_item(child)
        parent = self.parents.pop(tag, None)
        if parent is not None:
            if tag in self.children.get(parent, []): self.children[parent].remove(tag)
            for values in self.slots.get(parent, {}).values():
                if tag in values: values.remove(tag)
        self.children.pop(tag, None); self.slots.pop(tag, None)
        self.config.pop(tag, None); self.values.pop(tag, None)
    def set_value(self, tag, value): self.values[tag] = value
    def get_value(self, tag): return self.values.get(tag)
    def move_item(self, tag, parent=None, before=None, **kwargs):
        old = self.parents.get(tag)
        if old is not None and tag in self.children.get(old, []):
            self.children[old].remove(tag)
        if parent is not None:
            self.parents[tag] = parent
            self.children.setdefault(parent, []).append(tag)
        self.config.setdefault(tag, {}).update(kwargs)
    def bind_item_theme(self, *args, **kwargs): pass
    def focus_item(self, tag): pass
    def get_y_scroll(self, tag): return 0
    def set_y_scroll(self, tag, value): pass
    def get_x_scroll(self, tag): return 0
    def set_x_scroll(self, tag, value): pass
    def is_key_down(self, key): return False
    def is_mouse_button_double_clicked(self, button): return False
    def highlight_table_row(self, *args, **kwargs): pass
    def unhighlight_table_row(self, *args, **kwargs): pass

    @contextmanager
    def handler_registry(self):
        yield self._new()

    def add_mouse_click_handler(self, **kwargs): return self._new(**kwargs)


class SimpleModel:
    pass


def make_model():
    from DearUIQt.core import QAbstractTableModel, QModelIndex, Qt

    class Model(QAbstractTableModel):
        def __init__(self):
            super().__init__()
            self.rows = [["alpha", 1], ["beta", 2]]
            self.headers = ["Name", "Value"]

        def rowCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else len(self.rows)

        def columnCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else len(self.headers)

        def data(self, index, role=Qt.DisplayRole):
            if not index.isValid(): return None
            value = self.rows[index.row()][index.column()]
            if role in (Qt.DisplayRole, Qt.EditRole): return value
            return None

        def setData(self, index, value, role=Qt.EditRole):
            if not index.isValid() or role not in (Qt.EditRole, Qt.DisplayRole): return False
            self.rows[index.row()][index.column()] = value
            self.dataChanged.emit(index, index, [role])
            return True

        def headerData(self, section, orientation, role=Qt.DisplayRole):
            if role == Qt.DisplayRole and orientation == Qt.Horizontal:
                return self.headers[int(section)]
            return None

        def flags(self, index):
            if not index.isValid(): return Qt.NoItemFlags
            return Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable

    return Model()


def test_qmodelindex_abstract_table_model_and_selection_are_backend_neutral():
    for name in list(sys.modules):
        if name.startswith("dearpygui"):
            sys.modules.pop(name, None)
    from DearUIQt.core import QItemSelectionModel, QModelIndex, Qt

    model = make_model()
    invalid = QModelIndex()
    assert not invalid.isValid()
    index = model.index(1, 0)
    assert index.isValid() and index.row() == 1 and index.column() == 0
    assert index.data() == "beta"
    assert index.parent() == QModelIndex()
    assert index.flags() & Qt.ItemIsEditable

    selection = QItemSelectionModel(model)
    selection.setCurrentIndex(index, QItemSelectionModel.ClearAndSelect)
    assert selection.currentIndex() == index
    assert selection.isSelected(index)
    assert selection.selectedRows() == [model.index(1, 0)]
    assert "dearpygui.dearpygui" not in sys.modules


def test_qstyleditemdelegate_commits_edit_role_through_model():
    from DearUIQt.modelview import QStyledItemDelegate

    class Editor:
        def __init__(self): self.value = ""
        def setText(self, value): self.value = str(value)
        def text(self): return self.value

    model = make_model()
    index = model.index(0, 0)
    delegate = QStyledItemDelegate()
    editor = Editor()
    delegate.setEditorData(editor, index)
    assert editor.text() == "alpha"
    editor.setText("renamed")
    assert delegate.setModelData(editor, model, index)
    assert model.data(index) == "renamed"


def test_qtableview_consumes_qabstractitemmodel_and_refreshes_on_data_changed():
    from DearUIQt.modelview import QTableView

    backend = FakeBackend()
    view = QTableView(backend=backend)
    model = make_model()
    view.setModel(model)
    assert [column.label for column in view.columns] == ["Name", "Value"]
    assert view.rowValues(0) == ("alpha", 1)
    assert view.rowValues(1) == ("beta", 2)
    model.setData(model.index(0, 0), "gamma")
    assert view.rowValues(0) == ("gamma", 1)


def test_qtablewidget_owns_native_table_items_and_cell_widgets():
    from DearUIQt.modelview import QTableWidget, QTableWidgetItem
    from DearUIQt.widgets import QWidget

    backend = FakeBackend()
    table = QTableWidget(2, 2, backend=backend)
    table.setHorizontalHeaderLabels(["A", "B"])
    item = QTableWidgetItem("row-1")
    table.setItem(0, 0, item)
    editor = QWidget(parent=table, backend=backend)
    table.setCellWidget(0, 1, editor)
    assert table.item(0, 0) is item
    assert item.row() == 0 and item.column() == 0
    assert table.cellWidget(0, 1) is editor
    item.setText("renamed")
    native = table._native_items[(0, 0)]
    assert backend.get_value(native) == "renamed"


def test_reference_data_table_uses_qtablewidget_not_renderer_table_constructor():
    source = (ROOT / "WinUx/ui/components/reference_data_table.py").read_text(encoding="utf-8")
    build = source.split("def _create_table", 1)[1].split("def _schedule_population_from", 1)[0]
    population = source.split("def _ensure_native_row", 1)[1].split("def _populate_batch", 1)[0]
    assert "QTableWidget(" in build
    assert "QTableWidgetItem(" in population
    assert "dpg.add_table(" not in build + population
    assert "dpg.add_table_row(" not in build + population
    assert "dpg.add_table_column(" not in build + population


def test_r79_public_exports_and_version():
    import DearUIQt
    from DearUIQt import QAbstractItemModel, QModelIndex, QTableWidget
    from DearUIQt.QtCore import QAbstractTableModel
    from DearUIQt.QtWidgets import QTableWidget as QtWidgetsTableWidget

    assert tuple(map(int, DearUIQt.__version__.split("."))) >= (1, 18, 0)
    assert QAbstractItemModel is not None and QModelIndex is not None
    assert QAbstractTableModel is not None
    assert QtWidgetsTableWidget is QTableWidget

def test_qlistview_consumes_qabstract_list_model_and_syncs_selection_model():
    from DearUIQt.core import QAbstractListModel, QModelIndex, Qt
    from DearUIQt.modelview import QListView

    class ListModel(QAbstractListModel):
        def __init__(self):
            super().__init__()
            self.values = ["one", "two", "three"]
        def rowCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else len(self.values)
        def data(self, index, role=Qt.DisplayRole):
            if role == Qt.DisplayRole: return self.values[index.row()]
            if role == Qt.UserRole: return self.values[index.row()].upper()
            return None

    backend = FakeBackend()
    view = QListView(backend=backend)
    model = ListModel()
    view.setModel(model)
    assert [item.text for item in view._values] == ["one", "two", "three"]
    assert view.setCurrentKey(1)
    assert view.selectionModel().currentIndex() == model.index(1, 0)
    assert view.selectionModel().isSelected(model.index(1, 0))

def test_qabstractitemmodel_keeps_qobject_ownership_without_parent_name_collision():
    from DearUIQt.core import QObject

    owner = QObject()
    model = make_model()
    model.setParent(owner)
    assert model.objectParent() is owner
    assert model in owner.children()
    assert not model.parent(model.index(0, 0)).isValid()
    child = QObject(model)
    assert child in model.children()
    owner.delete()
    assert model._deleted and child._deleted
