"""Architecture checks for native Windows Explorer drag/drop."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "WinUx" / "services" / "windows_shell_dragdrop.py"
LIST_VIEW = ROOT / "WinUx" / "components" / "explorer_list_view.py"
DRAG_DROP = ROOT / "WinUx" / "components" / "explorer_drag_drop.py"
FILE_PANEL = ROOT / "WinUx" / "components" / "file_panel.py"
CONTROLLER = ROOT / "WinUx" / "controller.py"
INTERACTION = ROOT / "WinUx" / "controllers" / "explorer_transfer_interaction.py"


class WindowsExplorerDragDropTests(unittest.TestCase):
    def test_outbound_drag_uses_windows_shell_data_object(self):
        source = SERVICE.read_text(encoding="utf-8")
        self.assertIn("SHCreateShellItemArrayFromIDLists", source)
        self.assertIn("BHID_DataObject", source)
        self.assertIn("SHDoDragDrop", source)
        self.assertIn("pdsrc == NULL", source)

    def test_local_drag_hands_off_only_after_leaving_winux(self):
        source = DRAG_DROP.read_text(encoding="utf-8")
        self.assertIn("_cursor_over_other_top_level", source)
        self.assertIn("WindowFromPoint", source)
        self.assertIn("_maybe_handoff_drag_to_windows_shell", source)
        self.assertIn("self._finish_item_drag(perform_drop=False)", source)
        self.assertIn("ReleaseCapture", source)

    def test_explorer_drop_is_enabled_for_local_and_server_panes(self):
        source = FILE_PANEL.read_text(encoding="utf-8")
        # Regression: old code gated external_drop to panel_id == server.
        block_start = source.index("on_external_drop=(")
        block_end = source.index("on_sort_change=", block_start)
        block = source[block_start:block_end]
        self.assertNotIn('self.panel_id == "server"', block)
        self.assertIn('self.panel_id == "local"', block)  # outbound only

    def test_local_explorer_drop_copies_in_worker_and_refreshes(self):
        source = INTERACTION.read_text(encoding="utf-8")
        controller = CONTROLLER.read_text(encoding="utf-8")
        self.assertIn("class ExplorerTransferInteractionMixin", source)
        self.assertIn("ExplorerTransferInteractionMixin", controller)
        self.assertIn("def _external_drop_to_local", source)
        self.assertIn('self._submit_background("explorer-local-drop", worker)', source)
        self.assertIn("self.model.transfer", source)
        self.assertIn("move=False", source)
        self.assertIn("def shell_drag", source)


if __name__ == "__main__":
    unittest.main()
