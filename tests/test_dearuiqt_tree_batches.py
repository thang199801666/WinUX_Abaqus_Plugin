"""Tree bulk ownership, nested batches and stale native callback safety."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt.core import Qt
from DearUIQt.modelview import QTreeWidget, QTreeWidgetItem
from test_dearuiqt_list_updates import Backend as ListBackend


class Backend(ListBackend):
    mvMouseButton_Left = 0

    def __init__(self):
        super().__init__()
        self.materialized_rows = 0

    def add_child_window(self, **options):
        self.materialized_rows += 1
        return self.add_group(**options)

    add_item_handler_registry = add_item_clicked_handler = ListBackend.add_group

    def add_drawlist(self, width, height, **options):
        return self.add_group(width=width, height=height, **options)

    def draw_triangle(self, *points, **options):
        return self.add_group(**options)

    draw_image = draw_text = draw_triangle

    def bind_item_handler_registry(self, item, registry): pass
    def get_item_rect_size(self, tag): return (300, 24)

    def delete_item(self, tag, *, children_only=False):
        children = {}
        for key, options in self.items.items():
            children.setdefault(options.get('parent'), []).append(key)
        pending = list(children.get(tag, ())) if children_only else [tag]
        while pending:
            current = pending.pop()
            pending.extend(children.get(current, ()))
            self.items.pop(current, None)


class TreeBatchTests(unittest.TestCase):
    def tree(self, backend=None):
        tree = QTreeWidget(backend=backend or Backend())
        self.addCleanup(tree.delete)
        return tree

    def test_bulk_add_materializes_each_row_once(self):
        tree = self.tree()
        layouts = []
        tree.layoutChanged.connect(lambda: layouts.append(True))
        items = [QTreeWidgetItem('node ' + str(i)) for i in range(100)]
        before = tree.backend.materialized_rows
        self.assertEqual(tree.addTopLevelItems(items), items)
        self.assertEqual(len(layouts), 1)
        self.assertEqual(tree.backend.materialized_rows - before, 100)
        self.assertEqual(len(tree._rendered), 100)
        self.assertTrue(all(item.treeWidget() is tree for item in items))

    def test_nested_batches_defer_native_updates_and_include_item_edits(self):
        tree = self.tree()
        layouts = []
        tree.layoutChanged.connect(lambda: layouts.append(True))
        with tree.batchUpdate():
            root = QTreeWidgetItem(tree, ['root'])
            root.setExpanded(True)
            with tree.batchUpdate():
                root.addChildren([QTreeWidgetItem('a'), QTreeWidgetItem('b')])
                root.child(0).setText(0, 'renamed')
                tree.setCurrentItem(root.child(1))
            self.assertFalse(tree._rendered)
            self.assertFalse(layouts)
        self.assertEqual(len(layouts), 1)
        self.assertEqual(len(tree._rendered), 3)
        self.assertEqual(tree.backend.items[tree.nativeItem(root.child(0))]['label'].strip(), 'renamed')
        self.assertEqual(tree.selectedItems(), [root.child(1)])

    def test_exception_flushes_partial_changes_and_empty_batch_does_nothing(self):
        tree = self.tree()
        layouts = []
        tree.layoutChanged.connect(lambda: layouts.append(True))
        with tree.batchUpdate(): pass
        self.assertFalse(layouts)
        with self.assertRaisesRegex(ValueError, 'caller'):
            with tree.batchUpdate():
                tree.addTopLevelItem(QTreeWidgetItem('kept'))
                raise ValueError('caller')
        self.assertEqual(len(tree._rendered), 1)
        self.assertEqual(tree._batch_depth, 0)
        self.assertFalse(tree._rebuild_pending)

    def test_bulk_move_rebuilds_each_source_once_and_clears_foreign_current(self):
        backend = Backend()
        source, target = self.tree(backend), self.tree(backend)
        items = [QTreeWidgetItem(str(i)) for i in range(10)]
        source.addTopLevelItems(items)
        source.setCurrentItem(items[3])
        source_layouts, target_layouts = [], []
        source.layoutChanged.connect(lambda: source_layouts.append(True))
        target.layoutChanged.connect(lambda: target_layouts.append(True))
        target.addTopLevelItems(items)
        self.assertEqual((len(source_layouts), len(target_layouts)), (1, 1))
        self.assertIsNone(source.currentItem())
        self.assertFalse(source.selectedItems())
        self.assertEqual(source.topLevelItemCount(), 0)
        self.assertTrue(all(item.treeWidget() is target for item in items))

    def test_deleted_tree_is_not_recreated_on_batch_exit(self):
        tree = self.tree()
        before = tree.backend.materialized_rows
        with tree.batchUpdate():
            item = QTreeWidgetItem(tree, ['pending'])
            tree.delete()
        self.assertIsNone(item.treeWidget())
        self.assertEqual(tree.backend.materialized_rows, before)
        self.assertFalse(tree.backend.does_item_exist(tree.tag))
        with self.assertRaises(RuntimeError):
            with tree.batchUpdate(): pass

    def test_invalid_bulk_inputs_are_checked_before_mutation(self):
        tree = self.tree()
        item = QTreeWidgetItem('untouched')
        with self.assertRaises(TypeError):
            tree.addTopLevelItems([item, object()])
        self.assertIsNone(item.treeWidget())
        root = QTreeWidgetItem(tree, ['root'])
        child = QTreeWidgetItem(root, ['child'])
        with self.assertRaises(ValueError):
            child.addChildren([item, root])
        self.assertIsNone(item.parent())
        self.assertIsNone(item.treeWidget())

    def test_bulk_children_move_out_of_expanded_source_branch(self):
        backend = Backend()
        source, target = self.tree(backend), self.tree(backend)
        source_root, target_root = QTreeWidgetItem('source'), QTreeWidgetItem('target')
        source.addTopLevelItem(source_root)
        target.addTopLevelItem(target_root)
        source_root.setExpanded(True)
        target_root.setExpanded(True)
        children = [QTreeWidgetItem(str(i)) for i in range(10)]
        source_root.addChildren(children)
        source.setCurrentItem(children[0])
        events = []
        source.layoutChanged.connect(lambda: events.append('source'))
        target.layoutChanged.connect(lambda: events.append('target'))
        target_root.addChildren(children)
        self.assertEqual(sorted(events), ['source', 'target'])
        self.assertEqual(source_root.childCount(), 0)
        self.assertEqual(target_root.childCount(), 10)
        self.assertIsNone(source.currentItem())
        self.assertTrue(all(item.parent() is target_root and item.treeWidget() is target
                            for item in children))

    def test_native_and_overlay_callbacks_cannot_retarget_after_rebuild(self):
        tree = self.tree()
        a, b = QTreeWidgetItem('a'), QTreeWidgetItem('b')
        # Duplicate UserRole values must not make an overlay choose row a.
        a.setData(0, Qt.UserRole, 'shared')
        b.setData(0, Qt.UserRole, 'shared')
        tree.addTopLevelItems([a, b])
        native = tree.nativeItem(b)
        handler = next(key for key, item in tree._item_by_overlay_handler.items() if item is b)
        tree._overlay_clicked(handler, None, 'shared')
        self.assertIs(tree.currentItem(), b)
        tree.setCurrentItem(a)
        tree.setIndentation(25)
        tree._native_clicked(native, True, 'shared')
        tree._overlay_clicked(handler, None, 'shared')
        self.assertIs(tree.currentItem(), a)
        with tree.batchUpdate():
            tree.addTopLevelItem(QTreeWidgetItem('new'))
            tree._native_clicked(tree.nativeItem(b), True, 'shared')
            self.assertIs(tree.currentItem(), a)


if __name__ == '__main__':
    unittest.main(verbosity=2)
