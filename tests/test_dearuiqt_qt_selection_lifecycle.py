"""Qt 6 documented selection lifecycle contracts; no Qt/WinUx/GPU dependency."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.core import QAbstractTableModel, QItemSelectionModel, Qt
from DearUIQt import QtCore


class Model(QAbstractTableModel):
    def rowCount(self, parent=None): return 4
    def columnCount(self, parent=None): return 3


class QtSelectionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.model = Model()
        self.selection = QItemSelectionModel(self.model)
        self.addCleanup(self.model.delete)
        self.addCleanup(self.selection.delete)
        self.index = self.model.index(1, 2)
        self.selection.setCurrentIndex(self.index, self.selection.ClearAndSelect)
        self.events = []
        for name in ('selectionChanged', 'currentChanged', 'currentRowChanged', 'currentColumnChanged'):
            getattr(self.selection, name).connect(lambda *args, name=name: self.events.append(name))

    def test_reset_is_silent_and_clears_current_and_selection(self):
        self.selection.reset()
        self.assertFalse(self.selection.hasSelection())
        self.assertFalse(self.selection.currentIndex().isValid())
        self.assertEqual(self.events, [])
        self.selection.reset()
        self.assertEqual(self.events, [])

    def test_model_reset_is_silent_for_selection_signals(self):
        observed = []
        self.model.modelReset.connect(lambda: observed.append((
            self.selection.hasSelection(), self.selection.currentIndex().isValid())))
        self.model.beginResetModel()
        self.model.endResetModel()
        self.assertEqual(observed, [(False, False)])
        self.assertEqual(self.events, [])

    def test_clear_current_keeps_selected_items_and_emits_current_signals(self):
        self.selection.clearCurrentIndex()
        self.assertTrue(self.selection.isSelected(self.index))
        self.assertFalse(self.selection.currentIndex().isValid())
        self.assertEqual(self.events, ['currentChanged', 'currentRowChanged', 'currentColumnChanged'])
        self.selection.clearCurrentIndex()
        self.assertEqual(len(self.events), 3)

    def test_clear_selection_keeps_current_and_emits_only_selection(self):
        self.selection.clearSelection()
        self.assertEqual(self.selection.currentIndex(), self.index)
        self.assertFalse(self.selection.hasSelection())
        self.assertEqual(self.events, ['selectionChanged'])

    def test_clear_performs_selection_then_current_reset(self):
        current_during_selection = []
        self.selection.selectionChanged.connect(lambda *args: current_during_selection.append(
            self.selection.currentIndex()))
        self.selection.clear()
        self.assertEqual(self.events, ['selectionChanged', 'currentChanged',
                                      'currentRowChanged', 'currentColumnChanged'])
        self.assertEqual(current_during_selection, [self.index])
        self.assertFalse(self.selection.hasSelection())
        self.assertFalse(self.selection.currentIndex().isValid())
        self.events.clear()
        self.selection.clear()
        self.assertEqual(self.events, [])

    def test_same_model_assignment_is_noop(self):
        changed = []
        connection = self.selection._model_reset_connection
        self.selection.modelChanged.connect(changed.append)
        self.selection.setModel(self.model)
        self.assertIs(self.selection._model_reset_connection, connection)
        self.assertEqual(changed, [])
        self.assertTrue(self.selection.isSelected(self.index))
        self.assertEqual(self.selection.currentIndex(), self.index)
        self.assertEqual(self.events, [])

    def test_model_switch_emits_model_changed_and_disconnects_old_reset(self):
        new = Model()
        self.addCleanup(new.delete)
        observed = []
        self.selection.modelChanged.connect(lambda model: observed.append((
            model, self.selection.hasSelection(), self.selection.currentIndex().isValid())))
        old_connection = self.selection._model_reset_connection
        self.selection.setModel(new)
        self.assertEqual(observed, [(new, False, False)])
        self.assertFalse(old_connection.active)
        self.assertEqual(self.events, [])
        index = new.index(2, 1)
        self.selection.setCurrentIndex(index, self.selection.ClearAndSelect)
        self.events.clear()
        self.model.modelReset.emit()
        self.assertEqual(self.selection.currentIndex(), index)
        self.assertTrue(self.selection.isSelected(index))
        new.modelReset.emit()
        self.assertFalse(self.selection.hasSelection())
        self.assertFalse(self.selection.currentIndex().isValid())
        self.assertEqual(self.events, [])

    def test_detach_model_notifies_once_without_selection_signals(self):
        changed = []
        self.selection.modelChanged.connect(changed.append)
        self.selection.setModel(None)
        self.selection.setModel(None)
        self.assertEqual(changed, [None])
        self.assertIsNone(self.selection.model())
        self.assertFalse(self.selection.hasSelection())
        self.assertFalse(self.selection.currentIndex().isValid())
        self.assertEqual(self.events, [])

    def test_qtcore_facade_exposes_same_contract(self):
        self.assertIs(QtCore.QItemSelectionModel, QItemSelectionModel)
        model = QtCore.QAbstractTableModel()
        selection = QtCore.QItemSelectionModel(model)
        try:
            self.assertTrue(callable(selection.reset))
            self.assertTrue(callable(selection.clearCurrentIndex))
            self.assertTrue(callable(selection.modelChanged.connect))
        finally:
            selection.delete()
            model.delete()

    def test_scoped_selection_flags_support_qt_python_syntax(self):
        flags = QtCore.QItemSelectionModel.SelectionFlag
        command = flags.ClearAndSelect | flags.Rows
        self.selection.select(self.index, command)
        self.assertEqual(int(flags.Current), 0x10)
        self.assertEqual(self.selection.selectedRows(), [self.model.index(1, 0)])
        self.assertEqual(self.selection.SelectCurrent, flags.Select | flags.Current)


if __name__ == '__main__':
    unittest.main(verbosity=2)
