"""Dirty-row tree selection, repeated-click repair and reference cleanup."""
import gc
from pathlib import Path
import sys
import unittest
import weakref
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_dearuiqt_tree_batches import Backend, QTreeWidget, QTreeWidgetItem


class NoScanDict(dict):
    def __iter__(self):
        raise AssertionError('ordinary selection must not scan rendered rows')

    def items(self):
        raise AssertionError('ordinary selection must not scan rendered rows')


class TreeSelectionTests(unittest.TestCase):
    def tree(self, count=10):
        tree = QTreeWidget(backend=Backend())
        self.addCleanup(tree.delete)
        tree.addTopLevelItems([QTreeWidgetItem(str(i)) for i in range(count)])
        return tree

    def test_selection_updates_only_previous_and_current_without_scanning(self):
        tree = self.tree(1000)
        first, second = tree.topLevelItem(997), tree.topLevelItem(998)
        tree.setCurrentItem(first)
        tree._rendered = NoScanDict(tree._rendered)
        tree.backend.writes.clear()
        tree.setCurrentItem(second)
        self.assertEqual(set(tree.backend.writes), {tree.nativeItem(first), tree.nativeItem(second)})
        self.assertFalse(first.isSelected())
        self.assertTrue(second.isSelected())
        tree.backend.writes.clear()
        tree._sync_selection()
        tree.setCurrentItem(second)
        self.assertFalse(tree.backend.writes)
        tree.setCurrentItem(None)
        self.assertEqual(tree.backend.writes, [tree.nativeItem(second)])
        self.assertFalse(second.isSelected())

    def test_repeated_native_click_repairs_toggle_without_duplicate_change_signal(self):
        tree = self.tree()
        item = tree.topLevelItem(3)
        tree.setCurrentItem(item)
        changes = []
        tree.currentItemChanged.connect(lambda *args: changes.append(args))
        native = tree.nativeItem(item)
        tree.backend.set_value(native, False)
        tree.backend.writes.clear()
        tree._native_clicked(native, False, item.key)
        self.assertTrue(tree.backend.items[native]['value'])
        self.assertEqual(tree.backend.writes, [native])
        self.assertFalse(changes)

    def test_failed_native_write_retries_only_that_row(self):
        tree = self.tree()
        first, second = tree.topLevelItem(1), tree.topLevelItem(2)
        tree.setCurrentItem(first)
        original = tree.backend.set_value
        def fail_once(native, value):
            if native == tree.nativeItem(second):
                raise RuntimeError('temporary renderer failure')
            original(native, value)
        with patch.object(tree.backend, 'set_value', side_effect=fail_once):
            tree.setCurrentItem(second)
        self.assertEqual(tree._selection_visual_retry, {second})
        tree.backend.writes.clear()
        tree._sync_selection()
        self.assertEqual(tree.backend.writes, [tree.nativeItem(second)])
        self.assertFalse(tree._selection_visual_retry)

    def test_collapse_hide_and_rebuild_restore_selected_native_value(self):
        tree = self.tree(1)
        root = tree.topLevelItem(0)
        child = QTreeWidgetItem(root, ['child'])
        root.setExpanded(True)
        tree.setCurrentItem(child)
        root.setExpanded(False)
        self.assertIsNone(tree.nativeItem(child))
        self.assertIs(tree.currentItem(), child)
        root.setExpanded(True)
        self.assertTrue(tree.backend.items[tree.nativeItem(child)]['value'])
        child.setHidden(True)
        child.setHidden(False)
        self.assertTrue(tree.backend.items[tree.nativeItem(child)]['value'])

    def test_batched_selection_paints_only_final_model_on_exit(self):
        tree = self.tree()
        tree.backend.writes.clear()
        with tree.batchUpdate():
            tree.setCurrentItem(tree.topLevelItem(1))
            tree.setCurrentItem(tree.topLevelItem(2))
            self.assertFalse(tree.backend.writes)
        self.assertEqual(len(tree.backend.writes), 10)
        for item, visual in tree._rendered.items():
            self.assertEqual(tree.backend.items[visual['selectable']]['value'], item is tree.currentItem())

    def test_clear_and_delete_release_selected_item_references(self):
        for operation in ('clear', 'delete'):
            with self.subTest(operation=operation):
                tree = self.tree(1)
                item = tree.topLevelItem(0)
                tree.setCurrentItem(item)
                reference = weakref.ref(item)
                getattr(tree, operation)()
                self.assertFalse(item.isSelected())
                self.assertIsNone(tree.currentItem())
                del item
                gc.collect()
                self.assertIsNone(reference())


if __name__ == '__main__':
    unittest.main(verbosity=2)
