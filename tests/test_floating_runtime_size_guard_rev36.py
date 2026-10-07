from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "WinUx" / "dialogs" / "floating_runtime.py"
ADDRESS = ROOT / "WinUx" / "dialogs" / "folder_browser_address.py"


def test_floating_runtime_normalizes_empty_dpg_min_size_before_indexing():
    source = RUNTIME.read_text(encoding="utf-8")
    assert "def _normalize_size_pair" in source
    assert 'configured_minimum = dpg.get_item_configuration(self.form.tag).get("min_size")' in source
    assert "minimum = _normalize_size_pair(configured_minimum, (320, 180))" in source
    assert "min_width=minimum[0]" in source


def test_floating_runtime_normalizes_preferred_size_too():
    source = RUNTIME.read_text(encoding="utf-8")
    assert "preferred = _normalize_size_pair" in source
    assert "width = max(preferred[0], minimum[0])" in source


def test_address_text_measurement_does_not_assume_two_element_tuple():
    source = ADDRESS.read_text(encoding="utf-8")
    assert "len(measured) >= 1" in source
