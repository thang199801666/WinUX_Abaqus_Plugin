import itertools
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))

from DearUIQt.core import QSize, QSizePolicy
from DearUIQt.layouts import QVBoxLayout, QHBoxLayout, QGridLayout
from DearUIQt.widgets import QWidget


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


class ResponsiveWidget(QWidget):
    def __init__(self, backend, parent, *, hint=(80, 20), minimum=(20, 10),
                 height_divisor=None, width_divisor=None, stretch=0):
        super().__init__(backend.add_group(parent=parent.tag), parent=parent, backend=backend)
        self._hint = QSize(*hint)
        self._min_hint = QSize(*minimum)
        self._height_divisor = height_divisor
        self._width_divisor = width_divisor
        self.hfw_calls = 0
        self.wfh_calls = 0
        policy = self.sizePolicy()
        if height_divisor:
            policy.setHeightForWidth(True)
        if width_divisor:
            policy.setWidthForHeight(True)
        if stretch:
            policy.setHorizontalStretch(stretch)
            policy.setVerticalStretch(stretch)
        self.setSizePolicy(policy)

    def sizeHint(self):
        return QSize(self._hint.width(), self._hint.height())

    def minimumSizeHint(self):
        return QSize(self._min_hint.width(), self._min_hint.height())

    def heightForWidth(self, width):
        self.hfw_calls += 1
        return -1 if not self._height_divisor else max(1, int(width) // self._height_divisor)

    def widthForHeight(self, height):
        self.wfh_calls += 1
        return -1 if not self._width_divisor else max(1, int(height) // self._width_divisor)


class DependentLayoutTests(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()
        self.roots = []

    def tearDown(self):
        for root in reversed(self.roots):
            root.delete()

    def layout(self, cls, **kwargs):
        value = cls(backend=self.backend, **kwargs)
        self.roots.append(value)
        return value

    def test_vertical_box_sums_height_for_shared_width(self):
        layout = self.layout(QVBoxLayout, spacing=5)
        first = ResponsiveWidget(self.backend, layout, height_divisor=2)
        second = ResponsiveWidget(self.backend, layout, height_divisor=4)
        self.assertTrue(layout.hasHeightForWidth())
        self.assertEqual(layout.heightForWidth(100), 80)  # 50 + 25 + 5
        self.assertEqual(layout.minimumHeightForWidth(100), 80)

    def test_horizontal_box_allocates_width_by_stretch_before_hfw(self):
        layout = self.layout(QHBoxLayout, spacing=0)
        first = ResponsiveWidget(self.backend, layout, height_divisor=2, stretch=1)
        second = ResponsiveWidget(self.backend, layout, height_divisor=4, stretch=3)
        # 160 px of hints + 40 extra => 90 / 110 by stretch 1:3.
        self.assertEqual(layout.heightForWidth(200), 45)
        self.assertGreater(first.hfw_calls, 0)
        self.assertGreater(second.hfw_calls, 0)

    def test_dependent_query_cache_is_invalidated_by_layout_change(self):
        layout = self.layout(QVBoxLayout, spacing=0)
        child = ResponsiveWidget(self.backend, layout, height_divisor=2)
        self.assertEqual(layout.heightForWidth(120), 60)
        calls = child.hfw_calls
        self.assertEqual(layout.heightForWidth(120), 60)
        self.assertEqual(child.hfw_calls, calls)
        layout.setContentsMargins(10, 0, 10, 0)
        self.assertEqual(layout.heightForWidth(120), 50)
        self.assertGreater(child.hfw_calls, calls)

    def test_width_for_height_is_reciprocal_extension(self):
        layout = self.layout(QHBoxLayout, spacing=4)
        first = ResponsiveWidget(self.backend, layout, width_divisor=2)
        second = ResponsiveWidget(self.backend, layout, width_divisor=4)
        self.assertTrue(layout.hasWidthForHeight())
        self.assertEqual(layout.widthForHeight(100), 79)  # 50 + 25 + 4

    def test_grid_uses_column_widths_for_row_height(self):
        grid = self.layout(QGridLayout, columns=2)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(3)
        first = ResponsiveWidget(self.backend, grid.cell(0, 0), hint=(60, 20), height_divisor=2)
        second = ResponsiveWidget(self.backend, grid.cell(0, 1), hint=(60, 20), height_divisor=4)
        third = ResponsiveWidget(self.backend, grid.cell(1, 0), hint=(60, 20), height_divisor=5)
        grid.addWidget(first, 0, 0)
        grid.addWidget(second, 0, 1)
        grid.addWidget(third, 1, 0)
        # 196 content px split across two growable columns => 98 each.
        # Row heights are max(49,24)=49 and 19; plus 3 spacing.
        self.assertTrue(grid.hasHeightForWidth())
        self.assertEqual(grid.heightForWidth(200), 71)

    def test_widget_propagates_installed_layout_dependency_to_outer_layout(self):
        outer = self.layout(QVBoxLayout, spacing=0)
        host = QWidget(self.backend.add_group(parent=outer.tag), parent=outer, backend=self.backend)
        inner = QVBoxLayout(backend=self.backend, spacing=0)
        host.setLayout(inner)
        ResponsiveWidget(self.backend, inner, height_divisor=2)
        self.assertTrue(host.hasHeightForWidth())
        self.assertEqual(host.heightForWidth(120), 60)
        self.assertTrue(outer.hasHeightForWidth())
        self.assertEqual(outer.heightForWidth(120), 60)

    def test_hidden_child_does_not_participate_unless_retained(self):
        layout = self.layout(QVBoxLayout, spacing=7)
        visible = ResponsiveWidget(self.backend, layout, height_divisor=2)
        hidden = ResponsiveWidget(self.backend, layout, height_divisor=4)
        hidden.hide()
        self.assertEqual(layout.heightForWidth(100), 50)
        policy = hidden.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        hidden.setSizePolicy(policy)
        self.assertEqual(layout.heightForWidth(100), 82)  # 50 + 25 + 7


if __name__ == '__main__':
    unittest.main(verbosity=2)
