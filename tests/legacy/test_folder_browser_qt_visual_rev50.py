from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"


def test_name_cell_uses_centered_icon_slot_instead_of_inline_image():
    source = FORM.read_text(encoding="utf-8")
    assert "icon_slot = dpg.add_child_window(" in source
    assert "parent=name, width=18, height=METRICS.row_height" in source
    assert "parent=icon_slot, width=16, height=16" in source


def test_sidebar_text_y_has_small_upward_bias():
    source = FORM.read_text(encoding="utf-8")
    assert "* 0.5)) - 1" in source
    assert "return 3" in source
