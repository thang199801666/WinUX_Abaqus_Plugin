"""Regression checks for the compact multi-file Transfer Center."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
TRANSFER = ROOT / "WinUx" / "dialogs" / "transfer_center_form.py"
TRANSFER_ADAPTER = ROOT / "WinUx" / "dialogs" / "floating_adapters.py"
TRANSFER_LOGIC = ROOT / "WinUx" / "dialogs" / "logic" / "transfer.py"
FILE_PANEL = ROOT / "WinUx" / "ui" / "components" / "file_panel.py"
CONTROLLER = ROOT / "WinUx" / "controller.py"
TRANSFER_CONTROLLER = ROOT / "WinUx" / "controllers" / "transfer.py"


class TransferCenterV2Tests(unittest.TestCase):
    def test_clear_completed_button_is_removed(self):
        source = TRANSFER.read_text(encoding="utf-8")
        self.assertNotIn('text="Clear completed"', source)
        self.assertNotIn("_request_clear_completed", source)
        self.assertNotIn("def clear_completed", source)

    def test_successful_tasks_auto_remove(self):
        source = TRANSFER_LOGIC.read_text(encoding="utf-8")
        self.assertIn("AUTO_REMOVE_DELAY_MS", source)
        self.assertIn("schedule_auto_remove", source)
        self.assertIn("_auto_remove_completed_task", source)

    def test_each_transfer_row_owns_a_progress_bar(self):
        source = TRANSFER.read_text(encoding="utf-8")
        self.assertIn("self.progress_bar(", source)
        self.assertIn('percentage = QLabel("0.0%", parent=progress_host_frame)', source)
        self.assertIn("progress_host = progress_host_frame.tag", source)
        self.assertIn("action = self.action(", source)
        self.assertIn('"Cancel",', source)
        self.assertIn("self.row_widgets[row_id]", source)

    def test_context_menu_exposes_multi_file_upload_and_download(self):
        source = FILE_PANEL.read_text(encoding="utf-8")
        self.assertIn('"label": "Upload selected"', source)
        self.assertIn('"label": "Download selected"', source)
        self.assertGreaterEqual(source.count('"shortcut": "F5"'), 2)
        self.assertIn('"command:upload_selected"', source)
        self.assertIn('"command:download_selected"', source)

    def test_selected_transfer_reuses_conflict_drop_pipeline(self):
        facade = CONTROLLER.read_text(encoding="utf-8")
        source = TRANSFER_CONTROLLER.read_text(encoding="utf-8")
        self.assertIn("def transfer_selected", facade)
        start = source.index("def transfer_selected")
        end = source.index("def quick_transfer", start)
        block = source[start:end]
        self.assertIn("self.process_queued_drop", block)
        self.assertIn("list(paths", block)

    def test_percentage_is_rendered_inside_the_progress_bar_with_fixed_center_text(self):
        source = TRANSFER.read_text(encoding="utf-8")
        self.assertIn('self.progress_bar(0.0, parent=progress_host, overlay="")', source)
        self.assertIn('percentage = QLabel("0.0%", parent=progress_host_frame)', source)
        self.assertIn("self._recenter_progress_text(row)", source)
        self.assertIn('self._set_progress_text(row_id, values["ratio"])', source)
        self.assertIn("self._schedule_progress_recenter(row_id)", source)

    def test_cancel_button_shares_the_progress_row_and_matches_progress_height(self):
        source = TRANSFER.read_text(encoding="utf-8")
        self.assertNotIn("dpg.table_row", source)
        # Cancel and progress live on the same grid row, inside the row card.
        progress_row = source.split("progress_cell = controls_grid.cell(0, 0)", 1)[1].split("stats = self.status_text", 1)[0]
        self.assertIn('progress = self.progress_bar(0.0, parent=progress_host, overlay="")', progress_row)
        self.assertIn('percentage = QLabel("0.0%", parent=progress_host_frame)', progress_row)
        self.assertIn("action = self.action(", progress_row)
        self.assertIn('"Cancel"', progress_row)
        self.assertIn("width=self.ACTION_WIDTH, height=self.PROGRESS_HEIGHT", progress_row)

    def test_speed_sampler_resets_when_byte_counter_restarts(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from WinUx.dialogs.logic.transfer import TransferItemRow
        row = object.__new__(TransferItemRow)
        row.exists = Mock(return_value=True)
        row.task = SimpleNamespace(center=Mock())
        row.row_id = 1
        row._sample_time, row._sample_done, row._smoothed_speed = None, 0, 0
        with patch("WinUx.dialogs.logic.transfer.time.monotonic", side_effect=[1., 2., 3.]):
            row.update_progress(100, 1000)
            row.update_progress(200, 1000)
            self.assertGreater(row._smoothed_speed, 0)
            row.update_progress(50, 1000)
        self.assertEqual(row._smoothed_speed, 0)
        self.assertEqual(row._sample_done, 50)


    def test_progress_updates_are_coalesced(self):
        adapter = TRANSFER_ADAPTER.read_text(encoding="utf-8")
        logic = TRANSFER_LOGIC.read_text(encoding="utf-8")
        self.assertIn("_pending_row_updates", adapter)
        self.assertIn("flush_row_updates", adapter)
        self.assertIn("def update_row(self, row_id, **values)", logic)


if __name__ == "__main__":
    unittest.main()
