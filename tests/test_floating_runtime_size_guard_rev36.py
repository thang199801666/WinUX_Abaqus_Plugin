from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# dialogs/floating_runtime.py is a compatibility alias; the live implementation
# of the floating child runtime lives under ui/hosting/.
RUNTIME = ROOT / "WinUx" / "ui" / "hosting" / "floating_runtime.py"
# The address-bar measurement contract moved into the shared form text metrics
# helpers in the local folder selector form.
MEASUREMENT = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"


def test_floating_runtime_normalizes_empty_dpg_min_size_before_indexing():
    source = RUNTIME.read_text(encoding="utf-8")
    assert "def _normalize_size_pair" in source
    assert 'configured_minimum = form_item.nativeConfiguration().get("min_size")' in source
    assert "minimum = _normalize_size_pair(configured_minimum, (320, 180))" in source
    assert "min_width=minimum[0]" in source


def test_floating_runtime_normalizes_preferred_size_too():
    source = RUNTIME.read_text(encoding="utf-8")
    assert "preferred = _normalize_size_pair" in source
    assert "width = max(preferred[0], minimum[0])" in source


def test_address_text_measurement_does_not_assume_two_element_tuple():
    source = MEASUREMENT.read_text(encoding="utf-8")
    assert "def _text_width" in source
    # Never index an under-sized measurement tuple before checking its length.
    assert "if isinstance(measured, (tuple, list)) and measured:" in source
    assert "return float(measured[0] or 0.0)" in source
    assert 'if isinstance(measured, (tuple, list)) and len(measured) >= 2:' in source
