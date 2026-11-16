"""Repeated pointer selection must reconcile an externally changed current cell."""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from DearUIQt.modelview.spreadsheet_behavior import SpreadsheetBehavior


class SpreadsheetCurrentContinuityTests(TestCase):
    def make_sheet(self, current=(0, 0)):
        view = Mock()
        view.currentRow.return_value, view.currentColumn.return_value = current
        selection = SimpleNamespace(anchor=(80, 1), current=(80, 1))
        return SimpleNamespace(
            view=view, controller=SimpleNamespace(select=Mock(return_value='region'), selection=selection),
            first_column=1, _item_table=True, _applied_selection=((80, 1), (80, 1)),
            commit_editor=Mock(), _paint_selection=Mock(), _keyboard_owned=False)

    def test_same_selection_repairs_current_row_without_focusing_or_scrolling(self):
        sheet = self.make_sheet()
        self.assertEqual(SpreadsheetBehavior.select_range(sheet, (80, 1), focus=False), 'region')
        sheet.view.setCurrentCell.assert_called_once_with(80, 2)
        sheet.view.setFocus.assert_not_called()

    def test_same_selection_repairs_changed_column_with_gutter_offset(self):
        sheet = self.make_sheet(current=(80, 0))
        SpreadsheetBehavior.select_range(sheet, (80, 1), focus=False)
        sheet.view.setCurrentCell.assert_called_once_with(80, 2)

    def test_already_synchronized_selection_does_not_repaint_or_change_current(self):
        sheet = self.make_sheet(current=(80, 2))
        SpreadsheetBehavior.select_range(sheet, (80, 1), focus=False)
        sheet.view.setCurrentCell.assert_not_called()
        sheet._paint_selection.assert_not_called()
        sheet.view.setFocus.assert_not_called()
