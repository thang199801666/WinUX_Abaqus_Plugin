from contextlib import contextmanager
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


class FakeBackend:
    mvTable_SizingStretchProp = 1
    mvMouseButton_Left = 0
    mvKey_LControl = 10; mvKey_RControl = 11; mvKey_LShift = 12; mvKey_RShift = 13
    mvKey_A = 14; mvKey_Spacebar = 15; mvKey_Up = 16; mvKey_Down = 17
    mvKey_Home = 18; mvKey_End = 19; mvKey_Prior = 20; mvKey_Next = 21

    def __init__(self):
        self.next = 100
        self.config = {}; self.values = {}; self.parents = {}; self.children = {}; self.slots = {}
    def _new(self, slot=1, **kwargs):
        tag=self.next; self.next += 1
        parent=kwargs.get('parent'); self.config[tag]=dict(kwargs); self.values[tag]=kwargs.get('default_value')
        self.parents[tag]=parent; self.children.setdefault(tag, []); self.slots.setdefault(tag,{0:[],1:[]})
        if parent is not None:
            self.children.setdefault(parent, []).append(tag); self.slots.setdefault(parent,{0:[],1:[]})[slot].append(tag)
        return tag
    def add_table(self, **kw): return self._new(**kw)
    def add_table_column(self, **kw): return self._new(slot=0, **kw)
    def add_table_row(self, **kw): return self._new(slot=1, **kw)
    def add_selectable(self, **kw): return self._new(**kw)
    def add_text(self, value='', **kw): kw['default_value']=str(value); return self._new(**kw)
    def add_child_window(self, **kw): return self._new(**kw)
    def add_window(self, **kw): return self._new(**kw)
    def add_input_text(self, **kw): return self._new(**kw)
    def add_tree_node(self, **kw): return self._new(**kw)
    def add_item_handler_registry(self, **kw): return self._new(**kw)
    def add_item_clicked_handler(self, **kw): return self._new(**kw)
    def configure_item(self, tag, **kw): self.config.setdefault(tag,{}).update(kw)
    def get_item_configuration(self, tag): return self.config.get(tag,{})
    def get_item_children(self, tag, slot=1): return list(self.slots.get(tag,{}).get(slot,()))
    def get_item_user_data(self, tag): return self.config.get(tag,{}).get('user_data')
    def does_item_exist(self, tag): return tag in self.config
    def set_value(self, tag, value): self.values[tag]=value
    def get_value(self, tag): return self.values.get(tag)
    def get_item_state(self, tag): return {}
    def get_item_rect_min(self, tag): return (0,0)
    def get_item_rect_size(self, tag): return (400,240)
    def get_mouse_pos(self, local=False): return (0,0)
    def get_y_scroll(self, tag): return 0
    def set_y_scroll(self, tag, value): pass
    def get_x_scroll(self, tag): return 0
    def set_x_scroll(self, tag, value): pass
    def is_key_down(self, key): return False
    def is_mouse_button_double_clicked(self, button): return False
    def focus_item(self, tag): pass
    def bind_item_theme(self, *a, **kw): pass
    def bind_item_handler_registry(self, *a, **kw): pass
    def highlight_table_row(self, *a, **kw): pass
    def unhighlight_table_row(self, *a, **kw): pass
    def delete_item(self, tag, children_only=False):
        if children_only:
            for child in list(self.children.get(tag,())): self.delete_item(child)
            return
        for child in list(self.children.get(tag,())): self.delete_item(child)
        parent=self.parents.pop(tag,None)
        if parent is not None:
            if tag in self.children.get(parent,[]): self.children[parent].remove(tag)
            for values in self.slots.get(parent,{}).values():
                if tag in values: values.remove(tag)
        self.children.pop(tag,None); self.slots.pop(tag,None); self.config.pop(tag,None); self.values.pop(tag,None)
    def move_item(self, tag, parent=None, before=None, **kw):
        old=self.parents.get(tag)
        if old is not None:
            if tag in self.children.get(old,[]): self.children[old].remove(tag)
            for values in self.slots.get(old,{}).values():
                if tag in values: values.remove(tag)
        if parent is None and before is not None: parent=self.parents.get(before)
        if parent is not None:
            self.parents[tag]=parent; children=self.children.setdefault(parent,[])
            if before in children: children.insert(children.index(before),tag)
            else: children.append(tag)
            slot=self.slots.setdefault(parent,{0:[],1:[]})[1]
            if before in slot: slot.insert(slot.index(before),tag)
            else: slot.append(tag)
        self.config.setdefault(tag,{}).update(kw)
    @contextmanager
    def handler_registry(self): yield self._new()
    @contextmanager
    def item_handler_registry(self): yield self._new()
    def add_mouse_click_handler(self, **kw): return self._new(**kw)


def test_qstandarditemmodel_hierarchy_roles_headers_sort_and_index_mapping_are_backend_neutral():
    for name in list(sys.modules):
        if name.startswith('dearpygui'): sys.modules.pop(name, None)
    from DearUIQt.core import Qt
    from DearUIQt.gui import QStandardItem, QStandardItemModel

    model=QStandardItemModel(0,3)
    model.setHorizontalHeaderLabels(['Name','Date modified','Type'])
    folder=QStandardItem('zeta'); folder.setData('/tmp/zeta',Qt.UserRole); folder.setIcon('folder-texture')
    folder.setEditable(False)
    child=QStandardItem('child'); folder.appendRow(child)
    model.appendRow([folder,QStandardItem('2026-10-17'),QStandardItem('Folder')])
    model.appendRow([QStandardItem('alpha'),QStandardItem('2026-10-16'),QStandardItem('Folder')])
    index=model.index(0,0); child_index=model.index(0,0,index)
    assert model.itemFromIndex(index) is folder and model.indexFromItem(folder)==index
    assert child_index.parent()==index and child_index.data()=='child'
    assert index.data(Qt.DecorationRole)=='folder-texture'
    assert not (index.flags() & Qt.ItemIsEditable)
    assert model.headerData(1,Qt.Horizontal)=='Date modified'
    model.sort(0,Qt.AscendingOrder)
    assert model.item(0,0).text()=='alpha'
    assert 'dearpygui.dearpygui' not in sys.modules


def test_qtableview_persistent_editor_commits_through_delegate_and_restores_cell():
    from DearUIQt.core import Qt
    from DearUIQt.gui import QStandardItem, QStandardItemModel
    from DearUIQt.modelview import QTableView

    backend=FakeBackend(); model=QStandardItemModel(0,2); model.setHorizontalHeaderLabels(['Name','Type'])
    name=QStandardItem('old'); name.setData('stable-key',Qt.UserRole)
    model.appendRow([name,QStandardItem('Folder')])
    view=QTableView(backend=backend); view.setRowKeyRole(Qt.UserRole); view.setModel(model)
    index=model.index(0,0); native=view._native_item_for_index(index)
    editor=view.openPersistentEditor(index)
    assert editor is not None and view.isPersistentEditorOpen(index)
    assert editor.text()=='old' and backend.get_item_configuration(native).get('show') is False
    editor.setText('renamed')
    assert view.closePersistentEditor(index,commit=True)
    assert model.data(index,Qt.DisplayRole)=='renamed'
    assert backend.get_item_configuration(native).get('show') is True


def test_local_folder_details_table_uses_qtablewidget_not_raw_table_constructors():
    source=(ROOT/'WinUx/dialogs/local_folder_form.py').read_text(encoding='utf-8')
    block=source.split('class FolderListView',1)[1].split('class LocalFolderDialog',1)[0]
    set_items=block.split('def setItems',1)[1].split('def _sync_selection_visuals',1)[0]
    assert 'QTableWidget(' in set_items and 'QTableWidgetItem(' in set_items
    assert 'dpg.add_table(' not in set_items
    assert 'dpg.add_table_row(' not in set_items
    assert 'dpg.add_table_column(' not in set_items


def test_r80_public_exports_and_version():
    import DearUIQt
    from DearUIQt import QStandardItem, QStandardItemModel
    from DearUIQt.QtGui import QStandardItemModel as QtGuiModel
    assert tuple(map(int,DearUIQt.__version__.split('.'))) >= (1,19,0)
    assert QtGuiModel is QStandardItemModel and QStandardItem is not None

def test_qtreeview_consumes_qstandarditemmodel_without_breaking_qtreeitem_mode():
    from DearUIQt.core import Qt
    from DearUIQt.gui import QStandardItem, QStandardItemModel
    from DearUIQt.modelview import QTreeView

    backend=FakeBackend(); model=QStandardItemModel(0,1)
    root=QStandardItem('root'); root.setData('root-key',Qt.UserRole)
    child=QStandardItem('child'); child.setData('child-key',Qt.UserRole)
    root.appendRow(child); model.appendRow(root)
    view=QTreeView(backend=backend); view.setKeyRole(Qt.UserRole); view.setModel(model)
    assert len(view.items())==1 and view.items()[0].text=='root'
    assert view.items()[0].children[0].text=='child'
    assert view.setCurrentKey('child-key')
    assert view.currentIndex()==model.index(0,0,model.index(0,0))
    editor=view.edit(model.index(0,0))
    assert editor is not None and editor.text()=='root'
    editor.setText('renamed-root')
    assert view.commitEditor(editor,model.index(0,0))
    assert model.item(0,0).text()=='renamed-root'

def test_persistent_model_index_tracks_qstandarditem_across_sort():
    from DearUIQt.core import QPersistentModelIndex, Qt
    from DearUIQt.gui import QStandardItem, QStandardItemModel
    model=QStandardItemModel(0,1)
    z=QStandardItem('z'); a=QStandardItem('a')
    model.appendRow(z); model.appendRow(a)
    persistent=QPersistentModelIndex(model.indexFromItem(z))
    assert persistent.row()==0 and persistent.data()=='z'
    model.sort(0,Qt.AscendingOrder)
    assert persistent.isValid() and persistent.row()==1 and persistent.data()=='z'
