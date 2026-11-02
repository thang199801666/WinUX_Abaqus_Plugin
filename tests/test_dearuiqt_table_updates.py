"""Incremental table selection and retained cell colors, without WinUx/GPU."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt.modelview import QtDataGridView, QtGridRow
from DearUIQt.modelview.virtual_table import ReadOnlyTableViewport
from test_dearuiqt_list_updates import Backend as ListBackend


class Backend(ListBackend):
    def __init__(self):
        super().__init__()
        self.themes = []

    add_table = add_table_row = ListBackend.add_group

    def add_table_column(self, **options):
        return self.add_group(_slot=0, **options)

    def add_text(self, text, **options):
        return self.add_group(value=text, **options)

    def get_item_children(self, tag, slot=1):
        return [key for key, value in self.items.items()
                if value.get('parent') == tag and value.get('_slot', 1) == slot]

    def bind_item_theme(self, tag, theme):
        super().bind_item_theme(tag, theme)
        self.themes.append((tag, theme))

    def highlight_table_row(self, tag, row, color): pass
    def unhighlight_table_row(self, tag, row): pass


def make_table(count=1000):
    backend = Backend()
    table = QtDataGridView(backend=backend, columns=['Name', 'Type', 'Size'])
    table.setRows([QtGridRow(i, ('row ' + str(i), 'File', i), data={'id': i})
                   for i in range(count)])
    return backend, table


class TableUpdateTests(unittest.TestCase):
    def setUp(self):
        for name, value in [('qt_item_view_theme', 'table'),
                            ('qt_item_row_theme', 'row'), ('qt_item_text_theme', 'text')]:
            patcher = patch('DearUIQt.modelview.table.' + name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def create(self, count=1000):
        backend, table = make_table(count)
        self.addCleanup(table.delete)
        return backend, table

    def test_selection_updates_only_old_new_rows_and_all_their_cells(self):
        backend, table = self.create()
        table.setCurrentKey(900)
        backend.writes.clear()
        backend.themes.clear()
        table.setCurrentKey(901)
        self.assertEqual(set(backend.writes), {table.items[900], table.items[901]})
        expected = set(table._cell_native_items[900] + table._cell_native_items[901])
        self.assertEqual({tag for tag, theme in backend.themes}, expected)
        backend.writes.clear()
        backend.themes.clear()
        table._sync_selection_visuals()
        self.assertFalse(backend.writes)
        self.assertFalse(backend.themes)

    def test_current_without_selection_and_focus_hover_compatibility(self):
        backend, table = self.create(4)
        table.setCurrentKey(1)
        table.clearSelection()
        table.setCurrentKey(2, select=False)
        self.assertFalse(table._row_visual_state[1][2])
        self.assertTrue(table._row_visual_state[2][2])
        self.assertFalse(table.selected)
        backend.writes.clear()
        table._set_view_focus(False)
        self.assertEqual(len(backend.writes), 4)
        self.assertTrue(all(not state[3] for state in table._row_visual_state.values()))

    def test_model_metadata_refresh_append_trim_reorder(self):
        _, table = self.create(4)
        table.setCurrentKey(2)
        original = dict(table.items)
        rows = [QtGridRow(key, values, enabled=key != 1) for key, values in table.rows]
        table.setRows(rows)
        self.assertEqual(table.items, original)
        self.assertTrue(table._row_visual_state[1][1])
        table.setRows(rows + [QtGridRow(4, ('extra', 'File', 4))])
        self.assertEqual(table.items[2], original[2])
        self.assertIn(4, table._row_visual_state)
        table.setRows(rows)
        self.assertNotIn(4, table._row_visual_state)
        self.assertEqual(table.items[2], original[2])
        table.setRows(list(reversed(rows)))
        self.assertNotEqual(table.items[2], original[2])
        self.assertTrue(table._row_visual_state[2][0])
        self.assertEqual(table.rowValues(2), ('row 2', 'File', 2))
        table.setRows([])
        self.assertFalse(table._row_visual_state)

    def test_cell_theme_failure_retries_whole_affected_row(self):
        backend, table = self.create(4)
        table.setCurrentKey(1)
        backend.fail_once = table._cell_text_items[2][1]
        table.setCurrentKey(2)
        self.assertEqual(table._row_visual_retry, {2})
        backend.themes.clear()
        table._sync_selection_visuals()
        self.assertEqual({tag for tag, theme in backend.themes}, set(table._cell_native_items[2]))
        self.assertFalse(table._row_visual_retry)

    def test_old_native_callback_and_disabled_row_do_not_change_selection(self):
        _, table = self.create(4)
        old = table.items[2]
        rows = [QtGridRow(key, values, enabled=key != 1) for key, values in table.rows]
        table.setRows(list(reversed(rows)))
        table.setCurrentKey(3)
        table._row_clicked(old, True, 2)
        table._row_clicked(table.items[1], True, 1)
        self.assertEqual(table.selected, {3})
        table._row_clicked(table.items[2], True, 2)
        self.assertEqual(table.selected, {2})

    def test_spreadsheet_overlay_paint_hook_is_not_skipped(self):
        _, table = self.create(4)
        behavior = Mock()
        table._spreadsheet_behavior = behavior
        table._sync_selection_visuals()
        behavior._paint_selection.assert_called_once_with()
        table._spreadsheet_behavior = None

    def test_virtual_page_return_restores_selected_cell_themes(self):
        _, table = self.create(0)
        rows = [QtGridRow(i, ('row ' + str(i), 'File', i)) for i in range(100)]
        viewport = ReadOnlyTableViewport(table, rows, row_height=20, overscan=0)
        viewport.render(0, 100)
        table.setCurrentKey(2)
        viewport.render(1000, 100)
        self.assertEqual(viewport.selectedKeys, frozenset({2}))
        self.assertNotIn(2, table.items)
        viewport.render(0, 100)
        self.assertEqual(table.selected, {2})
        self.assertTrue(table._row_visual_state[2][0])
        self.assertTrue(table._row_visual_state[2][2])


if __name__ == '__main__':
    unittest.main(verbosity=2)
