"""M6g: item views share retained focus and selection visual state."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import DearUIQt
from DearUIQt.gui import QStandardItem, QStandardItemModel
from DearUIQt.modelview import QTreeView
from DearUIQt.modelview.base import QAbstractItemView
from DearUIQt.modelview.policy import QItemViewPolicyMixin
from test_dearuiqt_tree_data_updates import Backend


class ItemViewFocusVisualPolicyTests(unittest.TestCase):
    def test_release_version(self):
        self.assertGreaterEqual(tuple(map(int, DearUIQt.__version__.split('.'))), (1, 115, 0))

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

    def test_flat_and_tree_share_focus_policy_methods(self):
        self.assertIs(QAbstractItemView.hasFocus, QItemViewPolicyMixin.hasFocus)
        self.assertIs(QAbstractItemView.setFocus, QItemViewPolicyMixin.setFocus)
        self.assertIs(QTreeView.hasFocus, QItemViewPolicyMixin.hasFocus)
        self.assertIs(QTreeView.setFocus, QItemViewPolicyMixin.setFocus)

    def test_tree_focus_signal_and_visual_state_are_retained(self):
        view, root, _ = self.create_tree()
        view.setCurrentIndex(root.index())
        events = []
        view.focusChanged.connect(events.append)
        self.assertFalse(view.hasFocus())
        self.assertTrue(view._set_view_focus(True))
        self.assertTrue(view.hasFocus())
        self.assertEqual(events, [True])
        selected, disabled, current, active = view._item_visual_state(
            selected=True, disabled=False, current=True)
        self.assertEqual((selected, disabled, current, active), (True, False, True, True))
        self.assertTrue(view._set_view_focus(False))
        self.assertEqual(events, [True, False])
        self.assertEqual(view._item_visual_state(
            selected=True, disabled=False, current=True), (True, False, True, False))

    def test_focus_change_does_not_change_tree_current_or_selection(self):
        view, root, _ = self.create_tree()
        view.setCurrentIndex(root.index())
        current = view.selectionModel().currentIndex()
        selected = list(view.selectionModel().selectedIndexes())
        view._set_view_focus(True)
        view._set_view_focus(False)
        self.assertEqual(view.selectionModel().currentIndex(), current)
        self.assertEqual(view.selectionModel().selectedIndexes(), selected)

    def test_tree_visual_cache_tracks_active_inactive_transition(self):
        view, root, _ = self.create_tree()
        view.setCurrentIndex(root.index())
        key = view._key_for_index(root.index())
        view._set_view_focus(True)
        self.assertEqual(view._visual_state_by_key.get(key), (True, False, True, True))
        view._set_view_focus(False)
        self.assertEqual(view._visual_state_by_key.get(key), (True, False, True, False))

    def test_policy_cleanup_releases_global_focus_binding(self):
        view, _, _ = self.create_tree()
        binding = view._focus_input_binding
        view._delete_item_view_policy()
        self.assertIsNone(view._focus_input_binding)
        if binding is not None:
            self.assertTrue(getattr(binding, '_deleted', True))


if __name__ == '__main__':
    unittest.main(verbosity=2)
