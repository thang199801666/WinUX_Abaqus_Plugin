from contextlib import contextmanager
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


class FakeBackend:
    mvMouseButton_Left = 0
    mvMouseButton_Right = 1
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
        self.children = {}
        self.focused = None

    def _new(self, **kwargs):
        tag = self.next
        self.next += 1
        parent = kwargs.get("parent")
        self.config[tag] = dict(kwargs)
        self.values[tag] = kwargs.get("default_value")
        self.children.setdefault(tag, [])
        if parent is not None:
            self.children.setdefault(parent, []).append(tag)
        return tag

    def add_child_window(self, **kwargs): return self._new(**kwargs)
    def add_window(self, **kwargs): return self._new(**kwargs)
    def add_combo(self, items=(), **kwargs):
        tag = self._new(**kwargs)
        self.config[tag]["items"] = list(items)
        return tag
    def add_selectable(self, **kwargs): return self._new(**kwargs)
    def add_checkbox(self, **kwargs): return self._new(**kwargs)
    def does_item_exist(self, tag): return tag in self.config
    def configure_item(self, tag, **kwargs): self.config.setdefault(tag, {}).update(kwargs)
    def get_item_configuration(self, tag): return self.config.get(tag, {})
    def get_item_state(self, tag): return {}
    def delete_item(self, tag):
        self.config.pop(tag, None)
        self.values.pop(tag, None)
    def set_value(self, tag, value): self.values[tag] = value
    def get_value(self, tag): return self.values.get(tag)
    def get_item_children(self, tag, slot=1): return list(self.children.get(tag, ()))
    def get_y_scroll(self, tag): return 0
    def set_y_scroll(self, tag, value): pass
    def bind_item_theme(self, *args, **kwargs): pass
    def focus_item(self, tag): self.focused = tag
    def move_item(self, tag, **kwargs):
        self.config.setdefault(tag, {}).update(kwargs)
    def is_key_down(self, key): return False
    def is_mouse_button_double_clicked(self, button): return False

    @contextmanager
    def handler_registry(self):
        yield self._new()

    def add_mouse_click_handler(self, **kwargs): return self._new(**kwargs)


def test_qdialog_is_standard_result_surface_without_changing_legacy_qtdialog():
    for name in list(sys.modules):
        if name.startswith("dearpygui"):
            sys.modules.pop(name, None)
    from DearUIQt.dialogs import DialogCode, QDialog, QtDialog

    assert QDialog is not QtDialog
    assert QDialog.Accepted == 1 and QDialog.Rejected == 0
    assert DialogCode.Accepted == 1 and DialogCode.Rejected == 0
    assert QDialog._coerce_result(DialogCode.Accepted) == 1
    assert QDialog._coerce_result(9) == 9
    assert "dearpygui.dearpygui" not in sys.modules



def test_qdialog_done_emits_standard_signals_once_without_legacy_default_action():
    from DearUIQt.core import Signal
    from DearUIQt.dialogs import QDialog

    dialog = object.__new__(QDialog)
    dialog._dialog_done = False
    dialog._dialog_result = QDialog.Rejected
    dialog.accepted = Signal()
    dialog.rejected = Signal()
    dialog.finished = Signal()
    dialog.isVisible = lambda: False
    dialog.testAttribute = lambda _attribute: False
    dialog.deleteLater = lambda: None
    events = []
    dialog.accepted.connect(lambda: events.append("accepted"))
    dialog.rejected.connect(lambda: events.append("rejected"))
    dialog.finished.connect(lambda code: events.append(("finished", code)))

    assert dialog.accept() is True
    assert dialog.result() == QDialog.Accepted
    assert events == ["accepted", ("finished", QDialog.Accepted)]
    assert dialog.accept() is False
    assert events == ["accepted", ("finished", QDialog.Accepted)]

def test_qcombobox_is_qwidget_and_owns_item_data_on_fake_backend():
    from DearUIQt.core import Qt
    from DearUIQt.widgets import QComboBox, QWidget

    backend = FakeBackend()
    combo = QComboBox(["A", "B"], current="B", backend=backend)
    assert isinstance(combo, QWidget)
    assert combo.count() == 2
    assert combo.currentIndex() == 1
    combo.setItemData(1, {"id": 7})
    assert combo.currentData() == {"id": 7}
    combo.addItem("C", 99)
    assert combo.itemText(2) == "C"
    assert combo.itemData(2, Qt.UserRole) == 99
    combo.setCurrentIndex(2)
    assert combo.currentText() == "C"
    combo.removeItem(1)
    assert [combo.itemText(i) for i in range(combo.count())] == ["A", "C"]


def test_qlistwidget_owns_items_current_row_and_user_data():
    from DearUIQt.core import Qt
    from DearUIQt.modelview import QListWidget, QListWidgetItem

    backend = FakeBackend()
    view = QListWidget(backend=backend, visible_rows=3)
    items = []
    for key, label in (("one", "One"), ("two", "Two"), ("three", "Three")):
        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, key)
        view.addItem(item)
        items.append(item)
    assert view.count() == 3
    assert view.setCurrentRow(1)
    assert view.currentItem() is items[1]
    assert view.currentItem().data(Qt.UserRole) == "two"
    assert view.currentRow() == 1
    removed = view.takeItem(1)
    assert removed is items[1] and removed._owner is None
    assert view.count() == 2
    items[0].setText("First")
    assert view.item(0).text() == "First"


def test_settings_navigation_uses_qlistwidget_not_raw_selectables():
    source = (ROOT / "WinUx/dialogs/settings_form.py").read_text(encoding="utf-8")
    init = source.split("def __init__", 1)[1].split("def _set_status", 1)[0]
    assert "QListWidget(" in init
    assert "QListWidgetItem(" in init
    assert "dpg.add_selectable(" not in init
    assert "itemClicked.connect" in init
    reference = (ROOT / "WinUx/dialogs/reference_chart_form.py").read_text(encoding="utf-8")
    assert "_formula_functions_view = self.own_widget(QListWidget(" in reference


def test_r77_public_exports_and_version():
    import DearUIQt
    from DearUIQt import DialogCode, QComboBox, QDialog, QListWidget, QListWidgetItem
    from DearUIQt.QtWidgets import QComboBox as QtWidgetsCombo, QListWidget as QtWidgetsList

    assert tuple(map(int, DearUIQt.__version__.split("."))) >= (1, 16, 0)
    assert QDialog.Accepted == int(DialogCode.Accepted)
    assert QtWidgetsCombo is QComboBox
    assert QtWidgetsList is QListWidget
    assert QListWidgetItem is not None
