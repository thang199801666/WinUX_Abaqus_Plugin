"""Backend-independent spreadsheet policies and atomic adapter contracts."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from DearUIQt.modelview.spreadsheet import (
    CellRange, SpreadsheetSelection, SpreadsheetClipboard, SpreadsheetAdapter, SpreadsheetController,
)


class SpreadsheetTests(unittest.TestCase):
    def sheet(self, *, read_only=False, editable=None):
        data = [['A1', 'B1', 'C1'], ['A2', 'B2', 'C2'], ['A3', 'B3', 'C3']]
        writes, clipboard = [], {'text': '', 'ok': True}

        def write(changes):
            writes.append(dict(changes))
            for (row, col), value in changes.items():
                data[row][col] = value

        def copy(text):
            if clipboard['ok']:
                clipboard['text'] = text
            return clipboard['ok']

        adapter = SpreadsheetAdapter(lambda: (len(data), 3), lambda r, c: data[r][c],
                                     write=None if read_only else write, editable=editable)
        controller = SpreadsheetController(adapter, SimpleNamespace(setText=copy, text=lambda: clipboard['text']))
        return controller, data, writes, clipboard

    def test_reversed_rectangle(self):
        sheet, _, _, clipboard = self.sheet()
        sheet.select((2, 2), (0, 1))
        self.assertEqual(sheet.selection.selected_range.bounds, (0, 1, 2, 2))
        self.assertTrue(sheet.copy())
        self.assertEqual(clipboard['text'], 'B1\tC1\nB2\tC2\nB3\tC3')

    def test_clipboard_preserves_unicode_tabs_newlines_quotes_and_blanks(self):
        rows = [['Việt', 'a\tb', 'line1\nline2'], ['', '"quoted"', 'last']]
        self.assertEqual(SpreadsheetClipboard.loads(SpreadsheetClipboard.dumps(rows)), rows)

    def test_crlf_and_ragged_clipboard(self):
        self.assertEqual(SpreadsheetClipboard.loads('a\tb\r\nc\r\n'), [['a', 'b'], ['c', '']])

    def test_plain_comma_is_not_silently_split_into_columns(self):
        self.assertEqual(SpreadsheetClipboard.loads('hello, world'), [['hello, world']])

    def test_invalid_quotes_and_cell_limit(self):
        with self.assertRaises(ValueError):
            SpreadsheetClipboard.loads('"unterminated')
        previous = SpreadsheetClipboard.MAX_CELLS
        try:
            SpreadsheetClipboard.MAX_CELLS = 3
            with self.assertRaises(ValueError):
                SpreadsheetClipboard.loads('a\tb\nc\td')
        finally:
            SpreadsheetClipboard.MAX_CELLS = previous

    def test_paste_batch_updates_selected_top_left(self):
        sheet, data, writes, _ = self.sheet()
        sheet.select((2, 2), (1, 1))
        result = sheet.paste_text('10\t20\n30\t40')
        self.assertEqual(result.bounds, (1, 1, 2, 2))
        self.assertEqual(data[1], ['A2', '10', '20'])
        self.assertEqual(len(writes), 1)

    def test_scalar_fill_selected_rectangle(self):
        sheet, data, _, _ = self.sheet()
        sheet.select((0, 1), (2, 2))
        sheet.paste_text('5')
        self.assertEqual(data, [['A1', '5', '5'], ['A2', '5', '5'], ['A3', '5', '5']])

    def test_overflow_is_rejected_before_any_write(self):
        sheet, data, writes, _ = self.sheet()
        before = [row[:] for row in data]
        sheet.select((2, 2))
        with self.assertRaises(ValueError):
            sheet.paste_text('1\t2')
        self.assertEqual(writes, [])
        self.assertEqual(data, before)

    def test_read_only_allows_copy_but_no_mutation(self):
        sheet, _, writes, _ = self.sheet(read_only=True)
        sheet.select_all()
        self.assertTrue(sheet.copy())
        for action in (sheet.clear, sheet.cut, lambda: sheet.paste_text('5')):
            with self.assertRaises(ValueError):
                action()
        self.assertEqual(writes, [])

    def test_read_only_column_preflight_is_atomic(self):
        sheet, _, writes, _ = self.sheet(editable=lambda r, c: c != 0)
        sheet.select_all()
        with self.assertRaises(ValueError):
            sheet.clear()
        self.assertEqual(writes, [])
        sheet.select((0, 1), (2, 2))
        self.assertTrue(sheet.clear())

    def test_clipboard_failure_cannot_delete_cut_data(self):
        sheet, data, writes, clipboard = self.sheet()
        sheet.select_all()
        before = [row[:] for row in data]
        clipboard['ok'] = False
        self.assertFalse(sheet.cut())
        self.assertEqual(data, before)
        self.assertEqual(writes, [])

    def test_cut_and_clear_do_not_delete_rows(self):
        sheet, data, writes, clipboard = self.sheet()
        sheet.select((0, 1), (1, 1))
        self.assertTrue(sheet.cut())
        self.assertEqual(clipboard['text'], 'B1\nB2')
        self.assertEqual(data[0], ['A1', '', 'C1'])
        self.assertEqual(len(data), 3)

    def test_navigation_extends_range_and_tab_wraps(self):
        selection = SpreadsheetSelection()
        selection.select((0, 2), shape=(3, 3))
        selection.move(0, 1, shape=(3, 3), tab=True)
        self.assertEqual(selection.current, (1, 0))
        selection.move(1, 1, shape=(3, 3), extend=True)
        self.assertEqual(selection.selected_range.bounds, (1, 0, 2, 1))
        selection.move(0, -1, shape=(3, 3), tab=True)
        self.assertEqual(selection.current, (2, 0))

    def test_stale_selection_does_not_copy_a_different_dataset(self):
        sheet, data, _, _ = self.sheet()
        sheet.select_all()
        data.pop()
        with self.assertRaises(ValueError):
            sheet.copy_text()

    def test_empty_table_and_invalid_ranges(self):
        adapter = SpreadsheetAdapter(lambda: (0, 3), lambda r, c: '')
        sheet = SpreadsheetController(adapter)
        self.assertIsNone(sheet.select_all())
        self.assertEqual(sheet.copy_text(), '')
        with self.assertRaises(ValueError):
            CellRange(1, 0, 0, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
