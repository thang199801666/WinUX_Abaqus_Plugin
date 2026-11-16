"""M6f: QTreeView and flat item views share one retained interaction policy."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import DearUIQt
from DearUIQt.core import Qt
from DearUIQt.gui import QStandardItem, QStandardItemModel
from DearUIQt.modelview import QTreeView
from DearUIQt.modelview.base import QAbstractItemView
from DearUIQt.modelview.policy import QItemViewPolicyMixin
from test_dearuiqt_tree_data_updates import Backend


class ItemViewPolicyUnificationTests(unittest.TestCase):
    def test_release_version(self):
        self.assertGreaterEqual(tuple(map(int, DearUIQt.__version__.split('.'))), (1, 114, 0))

    def create_tree(self):
        backend = Backend()
        model = QStandardItemModel()
        root = QStandardItem('Root')
        child = QStandardItem('Child')
        root.appendRow(child)
        model.appendRow(root)
        view = QTreeView(backend=backend)
        view.setModel(model)
        self.addCleanup(view.delete)
        self.addCleanup(model.delete)
        return view, root, child

    def test_flat_and_tree_views_share_policy_contract(self):
        self.assertTrue(issubclass(QAbstractItemView, QItemViewPolicyMixin))
        self.assertTrue(issubclass(QTreeView, QItemViewPolicyMixin))
        self.assertEqual(QTreeView.EditKeyPressed, QAbstractItemView.EditKeyPressed)
        self.assertEqual(QTreeView.MovePageDown, QAbstractItemView.MovePageDown)
        self.assertEqual(QTreeView.EnsureVisible, QAbstractItemView.EnsureVisible)

    def test_tree_uses_shared_default_edit_trigger_policy(self):
        view, root, _ = self.create_tree()
        edits = []
        view.edit = lambda index: edits.append(index) or object()
        view.setCurrentIndex(root.index())
        self.assertEqual(view.editTriggers(), view.DoubleClicked | view.EditKeyPressed)
        self.assertTrue(view.navigate(Qt.Key_F2))
        self.assertEqual(edits, [root.index()])

    def test_tree_current_changed_trigger_uses_shared_policy(self):
        view, root, child = self.create_tree()
        edits = []
        view.edit = lambda index: edits.append(index) or object()
        view.expand(view._key_for_index(root.index()))
        view.setCurrentIndex(root.index())
        view.setEditTriggers(view.CurrentChanged)
        self.assertTrue(view.navigate(Qt.Key_Down))
        self.assertEqual(view.currentIndex(), child.index())
        self.assertEqual(edits, [child.index()])

    def test_tree_cursor_application_updates_selection_model_once(self):
        view, root, child = self.create_tree()
        view.expand(view._key_for_index(root.index()))
        view.setCurrentIndex(root.index())
        changes = []
        view.currentChanged.connect(changes.append)
        self.assertTrue(view.navigate(Qt.Key_Down))
        self.assertEqual(view.selectionModel().currentIndex(), child.index())
        self.assertEqual(view.currentIndex(), child.index())
        self.assertEqual(changes, [view._key_for_index(child.index())])

    def test_tree_any_key_trigger_uses_same_edit_path(self):
        view, root, _ = self.create_tree()
        edits = []
        view.edit = lambda index: edits.append(index) or object()
        view.setCurrentIndex(root.index())
        view.setEditTriggers(view.AnyKeyPressed)
        # Direct trigger verifies QTreeView no longer needs a private trigger implementation.
        self.assertIsNotNone(view._edit_from_trigger(view.AnyKeyPressed, root.index()))
        self.assertEqual(edits, [root.index()])


if __name__ == '__main__':
    unittest.main(verbosity=2)
