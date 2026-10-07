from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDRESS = ROOT / "WinUx" / "dialogs" / "folder_browser_address.py"


def test_address_bar_never_indexes_unvalidated_dpg_rect_tuple():
    source = ADDRESS.read_text(encoding="utf-8")
    assert "dpg.get_item_rect_size(self.body)[0]" not in source
    assert "def _available_width" in source
    assert "len(rect) >= 1" in source
    assert "self._last_valid_width" in source


def test_text_measurement_is_shape_checked_before_indexing():
    source = ADDRESS.read_text(encoding="utf-8")
    assert "len(measured) >= 1" in source
