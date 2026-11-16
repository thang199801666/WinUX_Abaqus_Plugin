import unittest

from DearUIQt.core import Qt, QItemSelectionModel
from DearUIQt.gui import QStandardItem, QStandardItemModel
from DearUIQt.modelview.base import QAbstractItemView


class _Harness(QAbstractItemView):
    def __init__(self, model):
        self.backend = object()
        self._model = model
        self._edit_triggers = self.NoEditTriggers
        self._page_step = 3
        self._model_cursor_anchor = model.index(0, 0)
        self._selection_model = QItemSelectionModel(model)
        self._selection_model.setCurrentIndex(model.index(0, 0), QItemSelectionModel.NoUpdate)
        self._selection_model.select([model.index(0, 0)], QItemSelectionModel.ClearAndSelect)
        self.multiple = True
        self.scrolled = []
        self.focus_calls = 0

    def currentIndex(self):
        return self._selection_model.currentIndex()

    def _pull_model_selection(self, *args, **kwargs):
        return None

    def scrollTo(self, index, hint=QAbstractItemView.EnsureVisible):
        self.scrolled.append((index.row(), index.column(), hint))
        return self

    def _focus_current(self):
        self.focus_calls += 1

    def _set_view_focus(self, focused):
        return bool(focused)


class ItemViewCursorNavigationTests(unittest.TestCase):
    def setUp(self):
        self.model = QStandardItemModel(8, 3)
        for row in range(8):
            for column in range(3):
                self.model.setItem(row, column, QStandardItem(f"{row},{column}"))
        self.view = _Harness(self.model)

    def test_release_version(self):
        import DearUIQt
        self.assertGreaterEqual(tuple(map(int, DearUIQt.__version__.split("."))), (1, 112, 0))

    def test_move_cursor_supports_full_flat_navigation_set(self):
        self.assertEqual((self.view.moveCursor(self.view.MoveDown).row(), self.view.moveCursor(self.view.MoveDown).column()), (1, 0))
        self.assertEqual((self.view.moveCursor(self.view.MoveRight).row(), self.view.moveCursor(self.view.MoveRight).column()), (0, 1))
        self.assertEqual((self.view.moveCursor(self.view.MoveEnd).row(), self.view.moveCursor(self.view.MoveEnd).column()), (0, 2))
        self.view._selection_model.setCurrentIndex(self.model.index(5, 1), QItemSelectionModel.NoUpdate)
        self.assertEqual((self.view.moveCursor(self.view.MovePageUp).row(), self.view.moveCursor(self.view.MovePageUp).column()), (2, 1))
        self.assertEqual((self.view.moveCursor(self.view.MovePageDown).row(), self.view.moveCursor(self.view.MovePageDown).column()), (7, 1))

    def test_navigate_updates_current_and_scrolls_to_it(self):
        self.assertTrue(self.view.navigate(Qt.Key_Down))
        self.assertEqual((self.view.currentIndex().row(), self.view.currentIndex().column()), (1, 0))
        self.assertEqual(self.view.scrolled[-1][:2], (1, 0))
        self.assertTrue(self.view.navigate(Qt.Key_PageDown))
        self.assertEqual(self.view.currentIndex().row(), 4)

    def test_ctrl_navigation_preserves_selection(self):
        before = set((i.row(), i.column()) for i in self.view._selection_model.selectedIndexes())
        self.assertTrue(self.view.navigate(Qt.Key_Down, ctrl=True))
        after = set((i.row(), i.column()) for i in self.view._selection_model.selectedIndexes())
        self.assertEqual(before, after)
        self.assertEqual(self.view.currentIndex().row(), 1)

    def test_shift_navigation_uses_stable_anchor_and_can_shrink(self):
        self.assertTrue(self.view.navigate(Qt.Key_Down, shift=True))
        self.assertTrue(self.view.navigate(Qt.Key_Down, shift=True))
        selected = {(i.row(), i.column()) for i in self.view._selection_model.selectedIndexes()}
        self.assertEqual(selected, {(0, 0), (1, 0), (2, 0)})
        self.assertTrue(self.view.navigate(Qt.Key_Up, shift=True))
        selected = {(i.row(), i.column()) for i in self.view._selection_model.selectedIndexes()}
        self.assertEqual(selected, {(0, 0), (1, 0)})

    def test_tab_and_backtab_use_same_move_cursor_engine(self):
        self.assertTrue(self.view.navigate(Qt.Key_Tab))
        self.assertEqual((self.view.currentIndex().row(), self.view.currentIndex().column()), (0, 1))
        self.assertTrue(self.view.navigate(Qt.Key_Backtab))
        self.assertEqual((self.view.currentIndex().row(), self.view.currentIndex().column()), (0, 0))


if __name__ == '__main__':
    unittest.main()
