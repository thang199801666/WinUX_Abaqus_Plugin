"""Low-churn range dragging: no repeated paint, focus stealing or stale updates."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from DearUIQt.modelview.spreadsheet import SpreadsheetAdapter, SpreadsheetController
from DearUIQt.modelview.spreadsheet_behavior import SpreadsheetBehavior


class SpreadsheetDragTests(unittest.TestCase):
    def setUp(self):
        self.sheet = SpreadsheetBehavior.__new__(SpreadsheetBehavior)
        self.sheet.view = SimpleNamespace(
            rows=[(str(row), (row, row, row)) for row in range(20)], columns=[{}, {}, {}],
            selected=set(), current=None, selectionChanged=Mock(), setFocus=Mock())
        self.sheet.view.setCurrentKey = Mock(side_effect=self.set_current)
        self.sheet.backend = Mock()
        self.sheet.tag = 'grid'
        self.sheet.first_column = 1
        self.sheet._item_table = False
        self.sheet._painted = set()
        self.sheet._applied_selection = None
        self.sheet._keyboard_owned = False
        self.sheet.commit_editor = Mock()
        self.sheet.controller = SpreadsheetController(
            SpreadsheetAdapter(lambda: (20, 2), lambda r, c: str(r)), Mock())
        self.sheet._pressed = (0, 0)
        self.sheet._dragging = False
        self.sheet._drag_pending = None
        self.sheet._drag_scheduled = False
        self.sheet._drag_generation = 0
        self.pending = []
        self.sheet._defer = lambda fn, *args: self.pending.append((fn, args))

    def set_current(self, key, **kwargs):
        self.sheet.view.current = key

    def test_unchanged_drag_range_does_not_repaint_or_emit(self):
        self.sheet.select_range((0, 0), (4, 1), focus=False)
        self.sheet.backend.reset_mock()
        self.sheet.view.selectionChanged.reset_mock()
        self.sheet.view.setCurrentKey.reset_mock()
        self.sheet.select_range((0, 0), (4, 1), focus=False)
        self.sheet.backend.highlight_table_cell.assert_not_called()
        self.sheet.backend.unhighlight_table_cell.assert_not_called()
        self.sheet.view.selectionChanged.assert_not_called()
        self.sheet.view.setCurrentKey.assert_not_called()

    def test_only_added_and_removed_cells_are_painted(self):
        self.sheet.select_range((0, 0), (4, 1), focus=False)
        self.sheet.backend.reset_mock()
        self.sheet.select_range((0, 0), (6, 1), focus=False)
        self.assertEqual(self.sheet.backend.highlight_table_cell.call_count, 4)
        self.sheet.backend.unhighlight_table_cell.assert_not_called()
        self.sheet.backend.reset_mock()
        self.sheet.select_range((0, 0), (2, 1), focus=False)
        self.sheet.backend.highlight_table_cell.assert_not_called()
        self.assertEqual(self.sheet.backend.unhighlight_table_cell.call_count, 8)
        self.sheet.view.setFocus.assert_not_called()
        self.assertFalse(self.sheet.view.setCurrentKey.call_args.kwargs['focus'])

    def test_drag_callbacks_coalesce_to_latest_cell(self):
        self.sheet._hit = Mock(side_effect=[(2, 1), (3, 1), (6, 1)])
        for _ in range(3):
            self.sheet._drag()
        self.assertEqual(len(self.pending), 1)
        callback, args = self.pending.pop()
        callback(*args)
        self.assertEqual(self.sheet.selected_range.bounds, (0, 0, 6, 1))
        self.sheet.view.setFocus.assert_not_called()

    def test_cancelled_queued_drag_cannot_restore_old_range(self):
        self.sheet._hit = Mock(return_value=(6, 1))
        self.sheet._drag()
        self.sheet._cancel_pending_drag()
        callback, args = self.pending.pop()
        callback(*args)
        self.assertIsNone(self.sheet.selected_range)

    def test_moving_back_before_flush_cancels_pending_extension(self):
        self.sheet.select_range((0, 0), (4, 1), focus=False)
        self.sheet._hit = Mock(side_effect=[(6, 1), (4, 1)])
        self.sheet._drag()
        self.sheet._drag()
        callback, args = self.pending.pop()
        callback(*args)
        self.assertEqual(self.sheet.selected_range.bounds, (0, 0, 4, 1))

    def test_keyboard_precomputed_selection_still_updates_view(self):
        self.sheet.select_range((0, 0), focus=False)
        self.sheet.controller.selection.move(1, 0, shape=(20, 2))
        self.sheet.select_range(self.sheet.controller.selection.anchor,
                                self.sheet.controller.selection.current, focus=False)
        self.assertEqual(self.sheet.view.current, '1')
        self.assertEqual(self.sheet.view.selected, {'1'})


if __name__ == '__main__':
    unittest.main()
