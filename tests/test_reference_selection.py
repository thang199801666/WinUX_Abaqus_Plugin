"""Worksheet range/clipboard policies: abaqus python tests/test_reference_selection.py."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from DearUIQt.widgets.buttons import ImGuiPushButton
from DearUIQt.modelview import QTableWidget
from DearUIQt.dialogs.qt_dialog import QtDialog
from WinUx.services.reference_charts import ReferenceTableModel
from WinUx.ui.components.reference_data_table import ReferenceDataTable
from WinUx.dialogs.reference_chart_form import ReferenceChartDialog


class RangeTests(unittest.TestCase):
    def setUp(self):
        self.sheet = sheet = ReferenceDataTable.__new__(ReferenceDataTable)
        sheet.model = ReferenceTableModel()
        sheet.model.load_series([{'points': [[1, 10], [2, 20], [3, 30]]}])
        sheet._closed = False
        sheet._cell_anchor = sheet._cell_extent = None
        sheet._selected_rows = set()
        sheet._selection_anchor = None
        sheet._painted_cells = set()
        sheet.current_cell = (0, 0)
        sheet.table = 123
        sheet._table_widget = SimpleNamespace(
            rowCount=lambda: 20, backend=Mock(), setFocus=Mock())
        sheet._commit_active_editor = Mock(return_value=False)
        sheet._read_inputs = Mock()
        sheet._clipboard = SimpleNamespace(setText=Mock(return_value=True))
        sheet._sync_loaded_range = Mock()
        sheet._extend_population_target = Mock()
        sheet.qt_model = SimpleNamespace(notify_cells_changed=Mock())
        sheet._changed = Mock()
        sheet.on_error = Mock()

    def test_reversed_drag_copies_rectangle_not_entire_rows(self):
        self.sheet.select_range((2, 1), (0, 0))
        self.assertEqual(self.sheet.selected_range, (0, 0, 2, 1))
        self.sheet.copy_selection()
        self.sheet._clipboard.setText.assert_called_with('1\t10\n2\t20\n3\t30')

    def test_single_column_cut_preserves_other_column(self):
        self.sheet.select_range((0, 1), (1, 1))
        self.sheet.cut_selection()
        self.sheet._clipboard.setText.assert_called_with('10\n20')
        self.assertEqual(self.sheet.model.row_text(0), ['1', ''])
        self.assertEqual(self.sheet.model.row_text(1), ['2', ''])
        self.assertEqual(self.sheet.model.row_text(2), ['3', '30'])

    def test_paste_uses_top_left_of_reversed_selection(self):
        self.sheet.select_range((2, 1), (1, 0))
        self.sheet.paste_text('8\t80\n9\t90')
        self.assertEqual(self.sheet.model.row_text(1), ['8', '80'])
        self.assertEqual(self.sheet.model.row_text(2), ['9', '90'])
        self.assertEqual(self.sheet.selected_range, (1, 0, 2, 1))

    def test_paste_rejects_overflow_without_changing_cells(self):
        self.sheet.select_range((0, 1))
        self.sheet.paste_text('8\t80')
        self.sheet.on_error.assert_called_once()
        self.assertEqual(self.sheet.model.row_text(0), ['1', '10'])

    def test_select_all_excludes_empty_padding(self):
        self.sheet.select_all()
        self.assertEqual(self.sheet.selected_range, (0, 0, 2, 1))

    def test_whole_row_copy_remains_supported(self):
        self.sheet.select_row(0)
        self.sheet.select_row(2, ctrl=True)
        self.sheet.copy_selection()
        self.sheet._clipboard.setText.assert_called_with('1\t10\n3\t30')

    def test_hidden_retained_worksheet_does_not_take_focus(self):
        self.sheet._frame = SimpleNamespace(isVisible=lambda: False)
        self.sheet._activate_editor = Mock()
        self.assertFalse(self.sheet.focus_cell(1, 0))
        self.assertEqual(self.sheet._pending_focus, (1, 0))
        self.sheet._activate_editor.assert_not_called()


class ButtonDeliveryTests(unittest.TestCase):
    def button(self):
        button = SimpleNamespace(
            _pointer_pressed=True, _pointer_generation=1, _dialog_pointer_routing=True,
            _native_pointer_suppressed=True, _deleted=False,
            isVisible=lambda: True, _activate_click=Mock())
        button._after = lambda delay, callback, *args: callback(*args)
        button._clear_pointer_suppression = lambda generation: ImGuiPushButton._clear_pointer_suppression(button, generation)
        return button

    def test_routed_release_deduplicates_queued_native_fallback(self):
        button = self.button()
        ImGuiPushButton._end_pointer_click(button, True)
        self.assertFalse(button._native_pointer_suppressed)
        with patch('DearUIQt.core.application.QApplication.instance',
                   return_value=SimpleNamespace(_pointer_bridge_installed=True)):
            ImGuiPushButton._clicked(button, 123, None, None)
        button._activate_click.assert_called_once()

    def test_cancelled_pointer_does_not_activate_native_fallback(self):
        button = self.button()
        ImGuiPushButton._end_pointer_click(button, False)
        with patch('DearUIQt.core.application.QApplication.instance',
                   return_value=SimpleNamespace(_pointer_bridge_installed=True)):
            ImGuiPushButton._clicked(button, 123, None, None)
        button._activate_click.assert_not_called()

    def test_non_dialog_native_activation_is_unchanged(self):
        button = self.button()
        button._dialog_pointer_routing = False
        ImGuiPushButton._clicked(button, 123, None, None)
        button._activate_click.assert_called_once()


class NativeTableHitTests(unittest.TestCase):
    def test_taller_editor_row_does_not_shift_hit_to_previous_row(self):
        tops = [240, 270, 295, 320]
        backend = SimpleNamespace(
            get_y_scroll=lambda tag: 0,
            is_item_visible=lambda tag: 0 <= tag[0] < len(tops),
            get_item_rect_min=lambda tag: (10, tops[tag[0]]),
            get_item_rect_size=lambda tag: (10, 15))
        table = SimpleNamespace(_rows=4, backend=backend, tag=123,
                                columnCount=lambda: 3, nativeItem=lambda row, col: (row, col))
        self.assertEqual(QTableWidget._painted_row_at_global(table, 271), 1)

    def test_missing_container_rect_uses_visible_cells_after_scroll(self):
        scroll = 5000
        backend = SimpleNamespace(
            get_y_scroll=lambda tag: scroll,
            is_item_visible=lambda tag: 200 <= tag[0] < 210,
            get_item_rect_min=lambda tag: (10 + tag[1] * 150, 100 + tag[0] * 25 - scroll),
            get_item_rect_size=lambda tag: (10, 15))
        table = SimpleNamespace(
            _rows=1000, _painted_row_pitch=25, backend=backend, tag=123,
            columnCount=lambda: 3, nativeItem=lambda row, column: (row, column))
        self.assertEqual(QTableWidget._painted_row_at_global(table, 182), 203)
        self.assertEqual(QTableWidget._painted_row_at_global(table, 50), -1)


class FirstClickRecoveryTests(unittest.TestCase):
    def test_fallback_consumes_pending_routed_press_before_click(self):
        button = Mock(spec=ImGuiPushButton)
        button._deleted = False
        button.click.return_value = True
        dialog = SimpleNamespace(
            _button_activation_serial=0, winfo_exists=lambda: True,
            isVisible=lambda: True, _control_wrappers={123: button},
            _button_pointer_target=button, _button_contains_global_point=lambda *args: True)
        self.assertTrue(QtDialog._recover_native_first_button_click(dialog, (10, 20), 0))
        self.assertIsNone(dialog._button_pointer_target)
        button._end_pointer_click.assert_called_once_with(False)
        button.click.assert_called_once()

    def test_recovery_waits_for_rendered_normal_delivery(self):
        dialog = SimpleNamespace(
            _button_activation_serial=0,
            view=SimpleNamespace(after=Mock(), after_render=Mock()),
            _recover_native_first_button_click=Mock())
        QtDialog._queue_native_first_button_recovery(dialog, (10, 20))
        dialog.view.after.assert_not_called()
        dialog.view.after_render.assert_called_once_with(
            dialog._recover_native_first_button_click, (10, 20), 0)

    def test_normally_delivered_button_prevents_first_click_replay(self):
        dialog = SimpleNamespace(
            _button_activation_serial=1, winfo_exists=lambda: True,
            isVisible=lambda: True, _control_wrappers={123: Mock()})
        self.assertFalse(QtDialog._recover_native_first_button_click(dialog, (10, 20), 0))


class SeriesDeletionTests(unittest.TestCase):
    def test_delete_cannot_reenter_while_selection_is_rebuilding(self):
        dialog = SimpleNamespace(_delete_in_progress=True, _selected=Mock())
        ReferenceChartDialog._remove_selected(dialog)
        dialog._selected.assert_not_called()

    def test_old_session_timer_cannot_reenable_delete_in_new_transaction(self):
        dialog = SimpleNamespace(_delete_generation=2, _delete_in_progress=True,
                                 winfo_exists=lambda: True, set_control_enabled=Mock())
        ReferenceChartDialog._finish_delete(dialog, 1)
        self.assertTrue(dialog._delete_in_progress)
        dialog.set_control_enabled.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
