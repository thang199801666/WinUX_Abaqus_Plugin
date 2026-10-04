from itertools import count
import unittest
from unittest.mock import Mock

from WinUx.widgets import QGridLayout, QLabel


def backend():
    value = Mock()
    ids = count(1)
    for name in ('add_table', 'add_table_column', 'add_table_row', 'add_group', 'add_text'):
        getattr(value, name).side_effect = lambda **kwargs: next(ids)
    value.add_text.side_effect = lambda *args, **kwargs: next(ids)
    value.does_item_exist.return_value = True
    return value


class GridTests(unittest.TestCase):
    def test_cells_are_retained_and_parent_owns_children(self):
        native = backend()
        grid = QGridLayout(3, backend=native)
        cell = grid.cell(2, 1)
        label = QLabel('Value', parent=cell)
        self.assertIs(grid.cell(2, 1), cell)
        self.assertEqual(native.add_table_row.call_count, 3)
        self.assertEqual(native.add_group.call_count, 9)
        grid.delete()
        self.assertTrue(label._deleted)
        self.assertEqual(grid._cells, {})
        self.assertEqual(grid._rows, [])

    def test_add_widget_moves_native_parent_and_transfers_ownership(self):
        native = backend()
        first = QGridLayout(backend=native)
        second = QGridLayout(backend=native)
        label = QLabel('Value', parent=first.cell(0, 0))
        second.addWidget(label, 0, 1)
        self.assertIs(label.parent, second.cell(0, 1))
        native.move_item.assert_called_once_with(label.tag, parent=label.parent.tag)
        second.addWidget(label, 0, 1)
        self.assertEqual(native.move_item.call_count, 1)
        first.delete()
        self.assertFalse(label._deleted)
        second.delete()
        self.assertTrue(label._deleted)

    def test_invalid_columns_positions_and_cycles_are_rejected(self):
        native = backend()
        for columns in (0, -1, 1.5, True):
            with self.assertRaises(ValueError):
                QGridLayout(columns, backend=native)
        native.add_table.assert_not_called()
        grid = QGridLayout(backend=native)
        for row, col in ((-1, 0), (0, 2), (1.5, 0), (True, 0)):
            with self.assertRaises(ValueError):
                grid.cell(row, col)
        native.add_table_row.assert_not_called()
        with self.assertRaises(ValueError):
            grid.addWidget(grid, 0, 0)

    def test_move_failure_keeps_original_ownership(self):
        native = backend()
        grid = QGridLayout(backend=native)
        label = QLabel('Value', parent=grid.cell(0, 0))
        original = label.parent
        native.move_item.side_effect = RuntimeError('failed')
        with self.assertRaises(RuntimeError):
            grid.addWidget(label, 0, 1)
        self.assertIs(label.parent, original)

    def test_other_backend_and_deleted_grid_rejected(self):
        native = backend()
        grid = QGridLayout(backend=native)
        label = QLabel('Value', backend=backend())
        with self.assertRaises(ValueError):
            grid.addWidget(label, 0, 0)
        grid.delete()
        with self.assertRaises(RuntimeError):
            grid.cell(0, 0)

    def test_partial_row_failure_rolls_back_and_can_retry(self):
        native = backend()
        grid = QGridLayout(backend=native)
        native.add_group.side_effect = [20, RuntimeError('failed')]
        with self.assertRaises(RuntimeError):
            grid.cell(0, 0)
        self.assertEqual(grid._rows, [])
        self.assertEqual(grid._cells, {})
        self.assertEqual(grid._children, [])
        native.add_group.side_effect = [21, 22]
        self.assertEqual(grid.cell(0, 1).tag, 22)

    def test_fixed_label_column_and_stretch_field_column(self):
        native = backend()
        QGridLayout(column_widths=(120, None), backend=native)
        calls = native.add_table_column.call_args_list
        self.assertTrue(calls[0].kwargs['width_fixed'])
        self.assertEqual(calls[0].kwargs['init_width_or_weight'], 120)
        self.assertTrue(calls[1].kwargs['width_stretch'])

    def test_invalid_widths_do_not_allocate_native_items(self):
        native = backend()
        for widths in ((100,), (0, None), (float('nan'), None), (float('inf'), None), (True, None)):
            with self.assertRaises(ValueError):
                QGridLayout(column_widths=widths, backend=native)
        native.add_table.assert_not_called()


if __name__ == '__main__':
    unittest.main()
