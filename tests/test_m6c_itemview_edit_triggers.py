import unittest

from DearUIQt.core import Qt, QEvent, QKeyEvent
from DearUIQt.gui import QStandardItem, QStandardItemModel
from DearUIQt.modelview.base import QAbstractItemView


class _Backend:
    pass


class _Harness(QAbstractItemView):
    def __init__(self, model):
        # Deliberately avoid QWidget/native setup: these tests exercise the
        # retained QAbstractItemView trigger/navigation policy only.
        self.backend = _Backend()
        self._model = model
        self._edit_triggers = self.DoubleClicked | self.EditKeyPressed
        self._current_index = model.index(0, 0)
        self.edits = []
        self.activations = 0
        self.focus_calls = 0

    def currentIndex(self):
        return self._current_index

    def setCurrentIndex(self, index):
        self._current_index = index
        return self

    def edit(self, index):
        self.edits.append((index.row(), index.column()))
        return object()

    def activateCurrent(self):
        self.activations += 1
        return True

    def _set_view_focus(self, focused):
        return bool(focused)

    def _focus_current(self):
        self.focus_calls += 1

    def keyPressEvent(self, event):
        return QAbstractItemView.keyPressEvent(self, event)


class ItemViewEditTriggerTests(unittest.TestCase):
    def setUp(self):
        self.model = QStandardItemModel(2, 2)
        for row in range(2):
            for column in range(2):
                self.model.setItem(row, column, QStandardItem(f"{row},{column}"))
        self.view = _Harness(self.model)

    def test_release_version(self):
        import DearUIQt
        self.assertGreaterEqual(tuple(map(int, DearUIQt.__version__.split("."))), (1, 111, 0))

    def test_default_edit_triggers_match_qabstractitemview_policy(self):
        self.assertEqual(
            self.view.editTriggers(),
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed,
        )
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.assertEqual(self.view.editTriggers(), QAbstractItemView.NoEditTriggers)

    def test_f2_edits_current_index_but_enter_activates(self):
        self.assertTrue(self.view.navigate(Qt.Key_F2))
        self.assertEqual(self.view.edits, [(0, 0)])
        self.assertTrue(self.view.navigate(Qt.Key_Return))
        self.assertEqual(self.view.activations, 1)
        self.assertEqual(self.view.edits, [(0, 0)])

    def test_tab_backtab_and_horizontal_navigation_move_current_index(self):
        self.assertTrue(self.view.navigate(Qt.Key_Tab))
        self.assertEqual((self.view.currentIndex().row(), self.view.currentIndex().column()), (0, 1))
        self.assertTrue(self.view.navigate(Qt.Key_Tab))
        self.assertEqual((self.view.currentIndex().row(), self.view.currentIndex().column()), (1, 0))
        self.assertTrue(self.view.navigate(Qt.Key_Backtab))
        self.assertEqual((self.view.currentIndex().row(), self.view.currentIndex().column()), (0, 1))
        self.assertTrue(self.view.navigate(Qt.Key_Left))
        self.assertEqual((self.view.currentIndex().row(), self.view.currentIndex().column()), (0, 0))
        self.assertTrue(self.view.navigate(Qt.Key_Right))
        self.assertEqual((self.view.currentIndex().row(), self.view.currentIndex().column()), (0, 1))

    def test_current_changed_trigger_auto_opens_editor(self):
        self.view.setEditTriggers(QAbstractItemView.CurrentChanged)
        self.view._current_index = self.model.index(0, 0)
        self.assertTrue(self.view._move_model_current(Qt.Key_Right))
        self.assertEqual(self.view.edits, [(0, 1)])

    def test_any_key_pressed_trigger_can_auto_open_editor(self):
        self.view.setEditTriggers(QAbstractItemView.AnyKeyPressed)
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_A, text="a")
        QAbstractItemView.keyPressEvent(self.view, event)
        self.assertTrue(event.isAccepted())
        self.assertEqual(self.view.edits, [(0, 0)])


if __name__ == "__main__":
    unittest.main()
