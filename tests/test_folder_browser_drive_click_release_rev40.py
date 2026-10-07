from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"


def test_sidebar_drive_navigation_is_deferred_out_of_selectable_callback():
    source = FORM.read_text(encoding="utf-8")
    start = source.index("def _place_clicked")
    end = source.index("def _change_view", start)
    block = source[start:end]
    assert "self._pending_place_path = str(path)" in block
    assert "self.view.after(1, self._commit_place_navigation)" in block
    assert "def _commit_place_navigation" in block
    assert "self._navigate(path)" in block
    clicked_body = block[:block.index("def _commit_place_navigation")]
    assert "self._navigate(path)" not in clicked_body


def test_sidebar_navigation_queue_coalesces_multiple_clicks():
    source = FORM.read_text(encoding="utf-8")
    assert "self._place_navigation_scheduled = False" in source
    assert "if self._place_navigation_scheduled:" in source
    assert "self._pending_place_path = None" in source
