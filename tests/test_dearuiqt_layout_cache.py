"""Layout snapshots, value semantics, lifecycle invalidation and activation."""
import gc
import itertools
from pathlib import Path
import sys
import unittest
import weakref
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt.core import QObject, QSize, QSizePolicy
from DearUIQt.layouts import QVBoxLayout, QHBoxLayout, QGridLayout
from DearUIQt.widgets import QWidget, QApplication
from DearUIQt.runtime import StandaloneUiHost


class Backend:
    mvTable_SizingStretchProp = 0

    def __init__(self):
        self.sequence = itertools.count(1)
        self.items = {}

    def add_group(self, **options):
        tag = next(self.sequence)
        self.items[tag] = dict(options)
        return tag

    add_table = add_table_row = add_table_column = add_group

    def get_item_parent(self, tag):
        return self.items[tag].get('parent')

    def get_item_configuration(self, tag):
        return dict(self.items[tag])

    def does_item_exist(self, tag):
        return tag in self.items

    def configure_item(self, tag, **options):
        self.items[tag].update(options)

    def move_item(self, tag, *, parent, **options):
        self.items[tag]['parent'] = parent

    def delete_item(self, tag):
        self.items.pop(tag, None)


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()
        self.roots = []

    def tearDown(self):
        for root in reversed(self.roots):
            root.delete()

    def box(self, cls=QVBoxLayout, **options):
        layout = cls(backend=self.backend, **options)
        self.roots.append(layout)
        return layout

    def grid(self):
        layout = QGridLayout(2, backend=self.backend)
        self.roots.append(layout)
        return layout

    def widget(self, parent, width=10, height=20):
        widget = QWidget(self.backend.add_group(parent=parent.tag), parent=parent, backend=self.backend)
        widget.setFixedSize(width, height)
        return widget

    def test_direct_child_construction_and_delete_refresh_size_hints(self):
        box = self.box(spacing=0)
        self.assertEqual(box.sizeHint(), QSize(0, 0))
        widget = self.widget(box)
        self.assertEqual(box.sizeHint(), QSize(10, 20))
        self.assertEqual(box.count(), 1)
        widget.delete()
        self.assertEqual(box.sizeHint(), QSize(0, 0))
        self.assertEqual(box.count(), 0)

    def test_cached_inspection_reuses_snapshot(self):
        box = self.box()
        widgets = [self.widget(box) for _ in range(20)]
        snapshot = box._items()
        for _ in range(3):
            self.assertEqual(box.count(), 20)
            for index, widget in enumerate(widgets):
                self.assertIs(box.itemAt(index).widget(), widget)
            self.assertIs(box._items(), snapshot)
        QObject(parent=box)  # A non-widget helper is not a layout item.
        self.assertIs(box._items(), snapshot)

    def test_same_parent_reorder_invalidates_membership_snapshot(self):
        box = self.box()
        first, second = self.widget(box), self.widget(box)
        box._items()
        box.insertWidget(0, second)
        self.assertIs(box.itemAt(0).widget(), second)
        self.assertIs(box.itemAt(1).widget(), first)
        self.assertEqual(box.indexOf(first), 1)
        self.assertEqual(box.indexOf(object()), -1)

    def test_reparent_and_take_refresh_both_layouts(self):
        outer = self.box()
        left, right = self.box(parent=outer), self.box(parent=outer)
        widget = self.widget(left)
        self.assertEqual((left.count(), right.count()), (1, 0))
        right.addWidget(widget)
        self.assertEqual((left.count(), right.count()), (0, 1))
        self.assertIs(right.takeAt(0).widget(), widget)
        self.assertEqual(right.count(), 0)
        self.assertIs(widget.parent, outer)

    def test_grid_cell_lifecycle_invalidates_flattened_entries(self):
        grid = self.grid()
        cell = grid.cell(0, 0)
        self.assertEqual(grid.count(), 0)
        widget = self.widget(cell)
        self.assertEqual(grid.count(), 1)
        self.assertEqual(grid.getItemPosition(0), (0, 0, 1, 1))
        self.assertEqual(grid.sizeHint(), QSize(10, 20))
        snapshot = grid._entries()
        self.assertIs(grid._entries(), snapshot)
        widget.delete()
        self.assertEqual(grid.count(), 0)
        self.assertEqual(grid.sizeHint(), QSize(0, 0))

    def test_grid_new_rows_and_nested_reordering_refresh_cache(self):
        grid = self.grid()
        cell = grid.cell(0, 1)
        first, second = self.widget(cell), self.widget(cell)
        self.assertEqual(grid.count(), 2)
        cell.insertWidget(0, second)
        self.assertIs(grid.itemAt(0).widget(), second)
        third = self.widget(grid.cell(2, 0))
        self.assertEqual(grid.count(), 3)
        self.assertIs(grid.itemAt(2).widget(), third)
        self.assertEqual(grid.getItemPosition(2), (2, 0, 1, 1))

    def test_size_hint_returns_independent_values(self):
        for layout in (self.box(), self.grid()):
            parent = layout.cell(0, 0) if isinstance(layout, QGridLayout) else layout
            self.widget(parent)
            size, minimum = layout.sizeHint(), layout.minimumSize()
            size.setWidth(999)
            minimum.setHeight(999)
            self.assertEqual(layout.sizeHint(), QSize(10, 20))
            self.assertEqual(layout.minimumSize(), QSize(10, 20))

    def test_nested_cached_hints_invalidate_after_child_geometry_changes(self):
        outer = self.box(spacing=0)
        inner = self.box(parent=outer, spacing=0)
        widget = self.widget(inner)
        self.assertEqual(outer.sizeHint(), QSize(10, 20))
        widget.setFixedSize(50, 60)
        self.assertEqual(outer.sizeHint(), QSize(50, 60))
        self.widget(inner, 20, 10)
        self.assertEqual(outer.sizeHint(), QSize(50, 70))

    def test_hidden_and_ignored_size_policies_and_margins(self):
        box = self.box(QHBoxLayout, spacing=3)
        box.setContentsMargins(1, 2, 3, 4)
        first, second = self.widget(box, 10, 20), self.widget(box, 30, 40)
        self.assertEqual(box.sizeHint(), QSize(47, 46))
        second.hide()
        self.assertEqual(box.sizeHint(), QSize(14, 26))
        policy = second.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        second.setSizePolicy(policy)
        self.assertEqual(box.sizeHint(), QSize(47, 46))
        first.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.assertEqual(box.sizeHint(), QSize(37, 46))

    def test_activation_preserves_invalidation_from_polish(self):
        for layout in (self.box(), self.grid()):
            parent = layout.cell(0, 0) if isinstance(layout, QGridLayout) else layout
            widget = self.widget(parent)
            widget.polishEvent = lambda event: layout.invalidate()
            self.assertTrue(layout.activate())
            self.assertTrue(layout._layout_dirty)
            self.assertTrue(layout.activate())
            self.assertFalse(layout._layout_dirty)
            self.assertFalse(layout.activate())

    def test_activation_failure_remains_dirty(self):
        box = self.box()
        widget = self.widget(box)
        widget.ensurePolished = Mock(side_effect=ValueError('expected'))
        with self.assertRaises(ValueError):
            box.activate()
        self.assertTrue(box._layout_dirty)

    def test_deleted_layout_cache_does_not_retain_widgets(self):
        for layout in (self.box(), self.grid()):
            parent = layout.cell(0, 0) if isinstance(layout, QGridLayout) else layout
            widget = self.widget(parent)
            ref = weakref.ref(widget)
            layout.count()
            layout.sizeHint()
            layout.delete()
            del widget, parent
            gc.collect()
            self.assertIsNone(ref())
            self.assertEqual(layout.count(), 0)

    def test_many_geometry_changes_post_one_root_activation(self):
        host = StandaloneUiHost(backend=self.backend)
        application = QApplication(after=host.after)
        root = QWidget(self.backend.add_group(), after=host.after, backend=self.backend)
        try:
            layout = QVBoxLayout(backend=self.backend)
            root.setLayout(layout)
            widget = self.widget(layout)
            while host.dispatcher.hasPendingEvents():
                host.pump()
            layout.activate = Mock(wraps=layout.activate)
            for width in range(1, 101):
                widget.setMinimumWidth(width)
            self.assertEqual(host.dispatcher.pendingCount(), 1)
            host.pump()
            layout.activate.assert_called_once()
            self.assertFalse(layout._layout_dirty)
        finally:
            root.delete()
            application.delete()
            host.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
