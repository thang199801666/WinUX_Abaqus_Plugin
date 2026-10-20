from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "WinUx" / "dialogs" / "server_path_form.py"
FLOATING = ROOT / "WinUx" / "dialogs" / "floating_adapters.py"


def test_server_folder_dialog_uses_compact_qt_layout():
    source = SERVER_PATH.read_text(encoding="utf-8")
    assert "DIALOG_SIZE = (560, 300)" in source
    assert "VISIBLE_MATCH_ROWS = 5" in source
    assert "visible_rows=self.VISIBLE_MATCH_ROWS" in source
    assert "status_item=self.status" in source
    assert "status_left_padding=2" in source


def test_server_folder_search_status_reuses_footer_slot_and_error_style():
    source = SERVER_PATH.read_text(encoding="utf-8")
    assert 'self.set_status_text(self.status, "Searching...", error=False)' in source
    assert "self.set_status_text(self.status, str(error), error=True)" in source
    assert 'label = "folder" if count == 1 else "folders"' in source


def test_legacy_process_host_matches_inprocess_geometry():
    source = FLOATING.read_text(encoding="utf-8")
    marker = '"server_path", "Server Folder"'
    block = source.split(marker, 1)[1].split("def request_search", 1)[0]
    assert "width=560, height=300" in block
