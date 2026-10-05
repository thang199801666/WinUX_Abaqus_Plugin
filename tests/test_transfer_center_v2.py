"""Regression checks for the compact multi-file Transfer Center."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
TRANSFER = ROOT / "WinUx" / "dialogs" / "transfer_center_form.py"
TRANSFER_ADAPTER = ROOT / "WinUx" / "dialogs" / "floating_adapters.py"
TRANSFER_LOGIC = ROOT / "WinUx" / "dialogs" / "logic" / "transfer.py"
FILE_PANEL = ROOT / "WinUx" / "components" / "file_panel.py"
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
        self.assertIn('overlay="0%"', source)
        self.assertIn('action = self.action(', source)
        self.assertIn('"Cancel",', source)
        self.assertIn('self.row_widgets[row_id]', source)

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

    def test_percentage_is_rendered_inside_progress_bar(self):
        source = TRANSFER.read_text(encoding="utf-8")
        self.assertIn('overlay="0%"', source)
        self.assertIn('dpg.configure_item(row["progress"], overlay=', source)
        self.assertNotIn("progress_text", source)

    def test_cancel_button_shares_progress_row(self):
        source = TRANSFER.read_text(encoding="utf-8")
        self.assertIn("with dpg.table_row(parent=table) as row_parent:", source)
        row = source.split("with dpg.table_row(parent=table) as row_parent:", 1)[1].split("stats =", 1)[0]
        self.assertIn("self.progress_bar(", row)
        self.assertIn("action = self.action(", row)
        self.assertIn("parent=row_parent", row)

    def test_speed_sampler_resets_when_byte_counter_restarts(self):
        source = TRANSFER_LOGIC.read_text(encoding="utf-8")
        server = (ROOT / "WinUx" / "services" / "remote_jobs.py").read_text(encoding="utf-8")
        self.assertIn("elif done < self._sample_done", source)
        self.assertIn("progress(source.name, 0, total", server)


    def test_progress_updates_are_coalesced(self):
        adapter = TRANSFER_ADAPTER.read_text(encoding="utf-8")
        logic = TRANSFER_LOGIC.read_text(encoding="utf-8")
        self.assertIn("_pending_row_updates", adapter)
        self.assertIn("flush_row_updates", adapter)
        self.assertIn("def update_row(self, row_id, **values)", logic)


if __name__ == "__main__":
    unittest.main()
