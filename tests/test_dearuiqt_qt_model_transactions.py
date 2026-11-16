"""Qt structural timing contracts and DearUIQt-specific mutation safeguards."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.QtCore import Qt
from DearUIQt.QtGui import QStandardItem, QStandardItemModel


class ModelTransactionTests(unittest.TestCase):
    def model(self, rows=2, columns=2):
        model = QStandardItemModel(rows, columns)
        self.addCleanup(model.delete)
        return model

    def test_insert_remove_observers_see_old_then_new_state(self):
        model = self.model()
        events = []
        for name in ('rowsAboutToBeInserted', 'rowsInserted', 'rowsAboutToBeRemoved', 'rowsRemoved'):
            getattr(model, name).connect(lambda parent, first, last, name=name:
                                        events.append((name, first, last, model.rowCount(parent))))
        self.assertTrue(model.insertRows(1, 3))
        self.assertTrue(model.removeRows(1, 3))
        self.assertEqual(events, [('rowsAboutToBeInserted', 1, 3, 2), ('rowsInserted', 1, 3, 5),
                                  ('rowsAboutToBeRemoved', 1, 3, 5), ('rowsRemoved', 1, 3, 2)])
        self.assertFalse(model._change_stack)

    def test_columns_notify_old_then_new_dimensions(self):
        model = self.model()
        events = []
        for name in ('columnsAboutToBeInserted', 'columnsInserted',
                     'columnsAboutToBeRemoved', 'columnsRemoved'):
            getattr(model, name).connect(lambda parent, first, last, name=name:
                                        events.append((name, first, last, model.columnCount(parent))))
        model.setColumnCount(4)
        model.setColumnCount(1)
        self.assertEqual(events, [('columnsAboutToBeInserted', 2, 3, 2), ('columnsInserted', 2, 3, 4),
                                  ('columnsAboutToBeRemoved', 1, 3, 4), ('columnsRemoved', 1, 3, 1)])

    def test_strict_counts_reject_invalid_ranges_without_signals(self):
        model = self.model()
        events = []
        model.rowsAboutToBeInserted.connect(lambda *args: events.append(args))
        model.rowsAboutToBeRemoved.connect(lambda *args: events.append(args))
        for row, count in ((-1, 1), (0, 0), (0, -1), (3, 1)):
            self.assertFalse(model.insertRows(row, count))
        for row, count in ((-1, 1), (0, 0), (0, -1), (1, 2), (2, 1)):
            self.assertFalse(model.removeRows(row, count))
        self.assertEqual(events, [])
        self.assertEqual(model.rowCount(), 2)

    def test_empty_cells_have_indexes_but_materialize_only_on_request(self):
        model = self.model()
        index = model.index(0, 0)
        self.assertTrue(index.isValid())
        self.assertIsNone(model.data(index))
        model.flags(index)
        self.assertIsNone(model.item(0, 0))
        item = model.itemFromIndex(index)
        self.assertIs(model.item(0, 0), item)
        self.assertEqual(index, model.index(0, 0))
        self.assertIsNone(item.parent())
        self.assertIsNone(model.item(0, 1))

    def test_set_data_roles_signal_order_and_successful_noop(self):
        model = self.model()
        events = []
        model.itemChanged.connect(lambda item: events.append(('item', item.text())))
        model.dataChanged.connect(lambda top, bottom, roles: events.append(('data', roles)))
        index = model.index(0, 0)
        self.assertTrue(model.setData(index, 'value'))
        self.assertEqual(events, [('item', 'value'), ('data', [Qt.DisplayRole, Qt.EditRole])])
        events.clear()
        self.assertTrue(model.setData(index, 'value'))
        self.assertEqual(events, [])

    def test_set_item_expands_rows_before_columns(self):
        model = self.model()
        events = []
        model.rowsInserted.connect(lambda *args: events.append(('rows', model.rowCount(), model.columnCount())))
        model.columnsInserted.connect(lambda *args: events.append(('columns', model.rowCount(), model.columnCount())))
        model.setItem(3, 4, QStandardItem('expanded'))
        self.assertEqual(events, [('rows', 4, 2), ('columns', 4, 5)])

    def test_nested_zero_column_insert_and_foreign_detached_parents(self):
        model = self.model()
        model.setItem(0, 0, QStandardItem('parent'))
        parent = model.index(0, 0)
        self.assertTrue(model.insertRows(0, 2, parent))
        self.assertEqual(model.rowCount(parent), 2)
        self.assertEqual(model.columnCount(parent), 0)
        other = self.model()
        self.assertFalse(model.insertRows(0, 1, other.index(0, 0)))
        taken = model.takeRow(0)
        self.assertFalse(model.insertRows(0, 1, parent))
        self.assertFalse(model.removeRows(0, 1, parent))
        self.assertIsNone(taken[0].model())

    def test_take_reinsert_preserves_subtree_ownership(self):
        model = self.model()
        item, child = QStandardItem('parent'), QStandardItem('child')
        item.appendRow(child)
        model.setItem(0, 0, item)
        taken = model.takeRow(0)
        self.assertIsNone(item.parent())
        self.assertIsNone(child.model())
        self.assertIs(child.parent(), item)
        model.appendRow(taken)
        self.assertIs(child.model(), model)
        self.assertEqual(child.index().parent(), item.index())

    def test_duplicate_owned_and_cyclic_items_rejected_before_mutation(self):
        model = self.model()
        item = QStandardItem('owned')
        model.setItem(0, 0, item)
        for values in ([item], [QStandardItem('new'), item]):
            with self.assertRaises(ValueError):
                model.appendRow(values)
        fresh = QStandardItem('fresh')
        with self.assertRaises(ValueError):
            model.appendRow([fresh, fresh])
        with self.assertRaises(ValueError):
            item.appendRow(item)
        self.assertEqual(model.rowCount(), 2)
        self.assertIsNone(fresh.model())

    def test_about_to_reentry_is_rejected_and_outer_operation_completes(self):
        model = self.model()
        attempts = []
        def about(*args):
            for action in (lambda: model.insertRows(0, 1), model.clear,
                           lambda: model.setItem(0, 0, QStandardItem('unsafe'))):
                with self.assertRaises(RuntimeError):
                    action()
                attempts.append(True)
        model.rowsAboutToBeInserted.connect(about)
        self.assertTrue(model.insertRows(0, 1))
        self.assertEqual(len(attempts), 3)
        self.assertEqual(model.rowCount(), 3)

    def test_about_to_exception_leaves_model_and_transaction_reusable(self):
        model = self.model()
        def fail(*args):
            raise ValueError('observer failed')
        connection = model.rowsAboutToBeInserted.connect(fail)
        with self.assertRaisesRegex(ValueError, 'observer failed'):
            model.insertRows(0, 1)
        self.assertEqual(model.rowCount(), 2)
        self.assertFalse(model._change_stack)
        connection.disconnect()
        self.assertTrue(model.insertRows(0, 1))

    def test_completed_callback_can_mutate_and_exceptions_do_not_poison_stack(self):
        model = self.model()
        def completed(*args):
            model.removeRows(0, 1)
            raise ValueError('completed failed')
        connection = model.rowsInserted.connect(completed)
        with self.assertRaisesRegex(ValueError, 'completed failed'):
            model.insertRows(0, 1)
        self.assertEqual(model.rowCount(), 2)
        self.assertFalse(model._change_stack)
        connection.disconnect()
        self.assertTrue(model.insertRows(0, 1))


if __name__ == '__main__':
    unittest.main(verbosity=2)
