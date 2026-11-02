"""Ownership/event ordering, bulk detachment and one-pass adapter cleanup."""
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt.core import QObject, QEvent, QTimer, Qt
from DearUIQt.widgets import QWidget, QRetainedItem, QApplication
from DearUIQt.layouts import QVBoxLayout, QGridLayout
from DearUIQt.runtime import StandaloneUiHost
from test_dearuiqt_layout_cache import Backend


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()
        self.roots = []

    def tearDown(self):
        for root in reversed(self.roots):
            root.delete()

    def root(self):
        root = QWidget(self.backend.add_group(), backend=self.backend)
        self.roots.append(root)
        return root

    def widget(self, parent):
        return QWidget(self.backend.add_group(parent=parent.tag), parent=parent, backend=self.backend)

    def test_box_clear_detaches_original_widgets_without_index_rebuilds(self):
        root = self.root()
        box = QVBoxLayout(parent=root)
        widgets = [self.widget(box) for _ in range(40)]
        helper = QObject(parent=box)
        box.takeAt = Mock(side_effect=AssertionError('clear must not repeat itemAt/takeAt lookups'))
        self.assertEqual(box.clear(delete=False), 40)
        self.assertEqual(box.count(), 0)
        self.assertIs(helper.parent, box)
        self.assertTrue(all(widget.parent is root and not widget._deleted for widget in widgets))
        self.assertTrue(all(self.backend.get_item_parent(widget.tag) == root.tag for widget in widgets))
        self.assertEqual(box.clear(delete=False), 0)

    def test_grid_clear_detaches_entries_preserving_internal_cells(self):
        root = self.root()
        grid = QGridLayout(2, parent=root)
        widgets = [self.widget(grid.cell(index // 2, index % 2)) for index in range(20)]
        cells = tuple(grid._cells.values())
        grid.takeAt = Mock(side_effect=AssertionError('clear must not rebuild entries per widget'))
        self.assertEqual(grid.clear(delete=False), 20)
        self.assertEqual(grid.count(), 0)
        self.assertTrue(all(widget.parent is root and not widget._deleted for widget in widgets))
        self.assertTrue(all(not cell._deleted and cell.parent is grid for cell in cells))
        self.assertEqual(grid.rowCount(), 10)

    def test_clear_uses_snapshot_and_leaves_reentrant_new_widgets(self):
        root = self.root()
        box = QVBoxLayout(parent=root)
        originals = [self.widget(box) for _ in range(3)]
        added = []
        child_event = box.childEvent
        def observe(event):
            child_event(event)
            if event.removed() and not added:
                extra = self.widget(root)
                added.append(extra)
                box.insertWidget(0, extra)
        box.childEvent = observe
        self.assertEqual(box.clear(delete=False), 3)
        self.assertEqual(box.count(), 1)
        self.assertIs(box.itemAt(0).widget(), added[0])
        self.assertTrue(all(widget.parent is root for widget in originals))

    def test_clear_does_not_steal_a_widget_moved_by_callback(self):
        root = self.root()
        box, other = QVBoxLayout(parent=root), QVBoxLayout(parent=root)
        originals = [self.widget(box) for _ in range(3)]
        moved = []
        child_event = box.childEvent
        def observe(event):
            child_event(event)
            if event.removed() and not moved:
                moved.append(originals[0])
                other.addWidget(originals[0])
        box.childEvent = observe
        box.clear(delete=False)
        self.assertEqual(box.count(), 0)
        self.assertIs(originals[0].parent, other)
        self.assertEqual(other.count(), 1)

    def test_delete_true_keeps_reverse_order_and_disposes_owned_widgets(self):
        root = self.root()
        box = QVBoxLayout(parent=root)
        widgets = [self.widget(box) for _ in range(4)]
        destroyed = []
        for index, widget in enumerate(widgets):
            widget.destroyed.connect(lambda obj, index=index: destroyed.append(index))
        self.assertEqual(box.clear(), 4)
        self.assertEqual(destroyed, [3, 2, 1, 0])
        self.assertFalse(box.count())
        self.assertTrue(all(widget._deleted and not self.backend.does_item_exist(widget.tag) for widget in widgets))

    def test_tail_reparent_keeps_sibling_order_and_child_removed_state(self):
        parent, other = QObject(), QObject()
        self.roots.extend((parent, other))
        first, second, third = (QObject(parent=parent) for _ in range(3))
        observed = []
        parent.childEvent = lambda event: observed.append((event.child().parent, tuple(parent.children())))
        third.setParent(other)
        self.assertEqual(parent.children(), [first, second])
        self.assertEqual(observed, [(None, (first, second))])
        first.delete()  # Interior/head fallback also preserves the order.
        self.assertEqual(parent.children(), [second])

    def test_recursive_parent_deletion_preserves_child_destroyed_order(self):
        parent = QObject()
        self.roots.append(parent)
        children = [QObject(parent=parent) for _ in range(4)]
        observed = []
        for index, child in enumerate(children):
            child.destroyed.connect(lambda obj, index=index: observed.append((index, obj.parent)))
        parent.delete()
        self.assertEqual(observed, [(0, None), (1, None), (2, None), (3, None)])

    def test_adapter_tree_purges_once_and_keeps_unrelated_work(self):
        host = StandaloneUiHost(backend=self.backend)
        app = QApplication(after=host.after)
        root = QObject(after=host.after)
        unrelated = QWidget(self.backend.add_group(), after=host.after, backend=self.backend)
        try:
            adapters = [QRetainedItem(self.backend.add_group(), parent=root, backend=self.backend)
                        for _ in range(40)]
            for _ in range(30):
                app.postEvent(unrelated, QEvent(QEvent.User))
            app.postEvent(adapters[0], QEvent(QEvent.User))
            app.queueNativeUpdate(adapters[1], {'enabled': False})
            unrelated.setEnabled(False)
            app.registerPointerTarget(adapters[0])
            self.assertTrue(app.setMouseGrabberObject(adapters[0]))
            app._implicit_grab_buttons = Qt.LeftButton
            app.setFocusObject(adapters[0])
            app._purge_object_subtree_state = Mock(wraps=app._purge_object_subtree_state)
            root.delete()
            app._purge_object_subtree_state.assert_called_once_with(root)
            self.assertEqual(len(app._posted), 30)
            self.assertEqual(len(app._native_updates), 1)
            self.assertFalse(app._deletion_roots)
            self.assertIsNone(app.mouseGrabberObject())
            self.assertEqual(app._implicit_grab_buttons, Qt.NoButton)
            self.assertIsNone(app.focusObject())
            self.assertFalse(app._pointer_targets)
            self.assertTrue(all(self.backend.does_item_exist(adapter.tag) for adapter in adapters))
            host.pump()
            self.assertFalse(self.backend.get_item_configuration(unrelated.tag)['enabled'])
        finally:
            root.delete()
            unrelated.delete()
            app.delete()
            host.close()

    def test_adapter_focus_out_can_still_inspect_its_layout(self):
        host = StandaloneUiHost(backend=self.backend)
        app = QApplication(after=host.after)
        adapter = QRetainedItem(self.backend.add_group(), after=host.after, backend=self.backend)
        try:
            layout = QVBoxLayout(parent=adapter)
            adapter.setLayout(layout)
            seen = []
            adapter.focusOutEvent = lambda event: seen.append(adapter.layout())
            app.setFocusObject(adapter)
            adapter.delete()
            self.assertEqual(seen, [layout])
            self.assertIsNone(adapter._layout_manager)
            self.assertTrue(self.backend.does_item_exist(adapter.tag))
        finally:
            adapter.delete()
            app.delete()
            host.close()

    def test_adapter_worker_delete_is_rejected_before_mutation(self):
        adapter = QRetainedItem(self.backend.add_group(), backend=self.backend)
        errors = []
        def worker():
            try:
                adapter.delete()
            except RuntimeError as error:
                errors.append(error)
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertEqual(len(errors), 1)
        self.assertFalse(adapter._deleted)
        adapter.delete()

    def test_adapter_tree_deletion_cancels_owned_timers(self):
        host = StandaloneUiHost(backend=self.backend)
        root = QObject(after=host.after)
        try:
            adapter = QRetainedItem(self.backend.add_group(), parent=root, backend=self.backend)
            timer = QTimer(adapter)
            timer.start(60000)
            root.delete()
            self.assertTrue(timer._deleted)
            self.assertEqual(host.dispatcher.pendingCount(), 0)
            self.assertTrue(self.backend.does_item_exist(adapter.tag))
        finally:
            root.delete()
            host.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
