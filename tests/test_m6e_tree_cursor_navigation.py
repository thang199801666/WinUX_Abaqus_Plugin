"""M6e: QTreeView cursor navigation follows visible tree order."""
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
from test_dearuiqt_tree_data_updates import Backend


class TreeCursorNavigationTests(unittest.TestCase):
    def test_release_version(self):
        self.assertGreaterEqual(tuple(map(int, DearUIQt.__version__.split("."))), (1, 113, 0))

    def create(self):
        backend = Backend()
        model = QStandardItemModel()
        a = QStandardItem('A')
        a1 = QStandardItem('A1')
        a1a = QStandardItem('A1a')
        a1.appendRow(a1a)
        a2 = QStandardItem('A2')
        a.appendRows([a1, a2])
        b = QStandardItem('B')
        b1 = QStandardItem('B1')
        b.appendRow(b1)
        model.appendRow(a)
        model.appendRow(b)
        view = QTreeView(backend=backend)
        view.setModel(model)
        self.addCleanup(view.delete)
        self.addCleanup(model.delete)
        return view, model, a, a1, a1a, a2, b, b1

    def key(self, view, item):
        return view._key_for_index(item.index())

    def test_right_expands_then_enters_first_child_and_left_reverses(self):
        view, _, a, a1, _, _, _, _ = self.create()
        view.setCurrentIndex(a.index())
        self.assertFalse(view.isExpanded(self.key(view, a)))
        target = view.moveCursor(view.MoveRight)
        self.assertEqual(target, a.index())
        self.assertTrue(view.isExpanded(self.key(view, a)))
        target = view.moveCursor(view.MoveRight)
        self.assertEqual(target, a1.index())
        view.setCurrentIndex(target)
        self.assertEqual(view.moveCursor(view.MoveLeft), a.index())
        view.setCurrentIndex(a.index())
        self.assertEqual(view.moveCursor(view.MoveLeft), a.index())
        self.assertFalse(view.isExpanded(self.key(view, a)))

    def test_up_down_follow_visible_order_not_raw_model_rows(self):
        view, _, a, a1, a1a, a2, b, _ = self.create()
        view.expand(self.key(view, a))
        view.expand(self.key(view, a1))
        expected = [a.index(), a1.index(), a1a.index(), a2.index(), b.index()]
        self.assertEqual(view.visibleIndexes(), expected)
        view.setCurrentIndex(a1a.index())
        self.assertEqual(view.moveCursor(view.MoveDown), a2.index())
        self.assertEqual(view.moveCursor(view.MoveUp), a1.index())
        view.collapse(self.key(view, a))
        self.assertEqual(view.visibleIndexes(), [a.index(), b.index()])
        # Current A1a is now hidden; navigation recovers to visible ancestor A.
        self.assertEqual(view.moveCursor(view.MoveDown), b.index())

    def test_home_end_page_and_tab_use_visible_order(self):
        view, _, a, a1, _, a2, b, b1 = self.create()
        view.expand(self.key(view, a))
        view.expand(self.key(view, b))
        view.setPageStep(2)
        view.setCurrentIndex(a1.index())
        self.assertEqual(view.moveCursor(view.MoveHome), a.index())
        self.assertEqual(view.moveCursor(view.MoveEnd), b1.index())
        self.assertEqual(view.moveCursor(view.MovePageDown), b.index())
        self.assertTrue(view.navigate(Qt.Key_Tab))
        self.assertEqual(view.currentIndex(), a2.index())
        self.assertTrue(view.navigate(Qt.Key_Backtab, shift=True))
        self.assertEqual(view.currentIndex(), a1.index())

    def test_navigation_updates_selection_model_and_scrolls(self):
        view, _, a, a1, _, _, _, _ = self.create()
        view.expand(self.key(view, a))
        view.setCurrentIndex(a.index())
        self.assertTrue(view.navigate(Qt.Key_Down))
        self.assertEqual(view.currentIndex(), a1.index())
        self.assertEqual(view.selectionModel().currentIndex(), a1.index())

    def test_enter_activates_without_expanding_or_moving(self):
        view, _, a, _, _, _, _, _ = self.create()
        events = []
        view.activated.connect(events.append)
        view.setCurrentIndex(a.index())
        self.assertTrue(view.navigate(Qt.Key_Return))
        self.assertEqual(events, [self.key(view, a)])
        self.assertFalse(view.isExpanded(self.key(view, a)))
        self.assertEqual(view.currentIndex(), a.index())


if __name__ == '__main__':
    unittest.main(verbosity=2)
