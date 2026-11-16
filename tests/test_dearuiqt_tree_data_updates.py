"""Model-bound tree data updates preserve native IDs/expanded state."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt.core import Qt, QAbstractTableModel
from DearUIQt.gui import QStandardItem, QStandardItemModel
from DearUIQt.modelview import QTreeView
from test_dearuiqt_tree_batches import Backend as TreeBackend


class Backend(TreeBackend):
    def add_item_toggled_open_handler(self, **options):
        if not options.get('two_way'):
            raise ValueError('tree expansion tracking must include close events')
        return self.add_group(**options)

    def add_tree_node(self, **options):
        if 'callback' in options:
            raise TypeError('modern tree nodes use toggled-open handlers, not callback')
        return self.add_group(**options)

    def __init__(self):
        super().__init__()
        self.configurations = []

    def configure_item(self, tag, **options):
        super().configure_item(tag, **options)
        self.configurations.append((tag, options))

    def get_value(self, tag):
        item = self.items[tag]
        return item.get('value', item.get('default_open', item.get('default_value')))


class TreeDataUpdateTests(unittest.TestCase):
    def create(self):
        backend = Backend()
        model = QStandardItemModel()
        parent = QStandardItem('parent')
        children = [QStandardItem('child ' + str(i)) for i in range(100)]
        parent.appendRows(children)
        model.appendRow(parent)
        view = QTreeView(backend=backend)
        view.setModel(model)
        self.addCleanup(model.delete)
        self.addCleanup(view.delete)
        return backend, model, parent, children, view

    def test_single_label_update_preserves_ids_current_and_expansion(self):
        backend, model, parent, children, view = self.create()
        parent_key = view._key_for_index(parent.index())
        child_key = view._key_for_index(children[50].index())
        view.expand(parent_key)
        view.setCurrentKey(child_key)
        native = dict(view._native_by_key)
        backend.configurations.clear()
        children[50].setText('renamed')
        self.assertEqual(view._native_by_key, native)
        self.assertTrue(view.isExpanded(parent_key))
        self.assertEqual(view.currentKey(), child_key)
        self.assertEqual(backend.configurations, [(native[child_key], {'label': 'renamed'})])

    def test_payload_change_avoids_native_writes_and_enabled_change_is_local(self):
        backend, model, parent, children, view = self.create()
        key = view._key_for_index(children[2].index())
        native = dict(view._native_by_key)
        backend.configurations.clear()
        payload = object()
        children[2].setData(payload, Qt.UserRole)
        self.assertIs(view._item_by_key[key].data, payload)
        self.assertFalse(backend.configurations)
        children[2].setEnabled(False)
        self.assertEqual(backend.configurations, [(native[key], {'enabled': False})])
        self.assertEqual(view._native_by_key, native)
        view._selected(native[key], True, key)
        self.assertIsNone(view.currentItem())

    def test_same_parent_range_updates_only_changed_rows(self):
        backend, model, parent, children, view = self.create()
        native = dict(view._native_by_key)
        # Mutate role data without individual notifications, then emit a range.
        for child in children[20:30]:
            child._data[Qt.DisplayRole] = 'updated ' + child.text()
        backend.configurations.clear()
        model.dataChanged.emit(children[20].index(), children[29].index(), [Qt.DisplayRole])
        self.assertEqual(len(backend.configurations), 10)
        self.assertEqual(view._native_by_key, native)
        backend.configurations.clear()
        model.dataChanged.emit(children[20].index(), children[29].index(), [])
        self.assertFalse(backend.configurations)

    def test_key_role_change_falls_back_to_structural_rebuild(self):
        _, model, parent, children, view = self.create()
        children[0].setData('old key', Qt.UserRole)
        view.setKeyRole(Qt.UserRole)
        native = view._native_by_key['old key']
        children[0].setData('new key', Qt.UserRole)
        self.assertNotIn('old key', view._native_by_key)
        self.assertNotEqual(view._native_by_key['new key'], native)

    def test_old_leaf_branch_click_and_toggle_callbacks_are_rejected(self):
        _, model, parent, children, view = self.create()
        parent_key = view._key_for_index(parent.index())
        child_key = view._key_for_index(children[0].index())
        leaf = view._native_by_key[child_key]
        branch = view._native_by_key[parent_key]
        handler = view._selection_handler_by_key[parent_key]
        model.layoutChanged.emit()
        view._selected(leaf, True, child_key)
        view._selected(handler, None, parent_key)
        view._node_toggled(branch, True, parent_key)
        self.assertIsNone(view.currentItem())
        self.assertFalse(view.isExpanded(parent_key))
        view._selected(view._selection_handler_by_key[parent_key], None, parent_key)
        self.assertEqual(view.currentKey(), parent_key)

    def test_failed_native_update_uses_authoritative_rebuild(self):
        backend, model, parent, children, view = self.create()
        native = dict(view._native_by_key)
        with patch.object(backend, 'configure_item', side_effect=RuntimeError('native write failed')):
            children[0].setText('retry from model')
        self.assertNotEqual(view._native_by_key, native)
        key = view._key_for_index(children[0].index())
        self.assertEqual(view._item_by_key[key].text, 'retry from model')

    def test_pointerless_model_uses_full_path_keys(self):
        class FlatModel(QAbstractTableModel):
            text = 'before'
            def rowCount(self, parent=None):
                return 0 if parent is not None and parent.isValid() else 2
            def columnCount(self, parent=None): return 1
            def data(self, index, role=Qt.DisplayRole):
                return self.text if role == Qt.DisplayRole else None
        model, backend = FlatModel(), Backend()
        view = QTreeView(backend=backend)
        self.addCleanup(view.delete)
        self.addCleanup(model.delete)
        view.setModel(model)
        native = dict(view._native_by_key)
        model.text = 'after'
        model.dataChanged.emit(model.index(0, 0), model.index(1, 0), [])
        self.assertEqual(view._native_by_key, native)
        self.assertEqual(view._item_by_key[('model-path', (1,))].text, 'after')

    def test_fresh_toggle_handler_and_non_displayed_columns(self):
        backend, model, parent, children, view = self.create()
        parent_key = view._key_for_index(parent.index())
        native = dict(view._native_by_key)
        backend.set_value(native[parent_key], True)
        view._node_toggled(view._toggle_handler_by_key[parent_key], None, parent_key)
        self.assertTrue(view.isExpanded(parent_key))
        # QTreeView exposes only column zero; sibling-column display updates
        # must not recreate the branch or discard its open state.
        parent.setChild(0, 1, QStandardItem('second column'))
        view.expand(parent_key)
        native = dict(view._native_by_key)
        backend.configurations.clear()
        parent.child(0, 1).setText('changed second column')
        self.assertEqual(view._native_by_key, native)
        self.assertFalse(backend.configurations)
        self.assertTrue(view.isExpanded(parent_key))


if __name__ == '__main__':
    unittest.main(verbosity=2)
