from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"


def test_right_list_icon_slot_uses_drawlist_not_child_window():
    source = FORM.read_text(encoding="utf-8")
    assert "icon_slot = dpg.add_drawlist(" in source
    assert "self.icons[item.key] = dpg.draw_image(" in source
    assert "pmin=(1, max(0, (METRICS.row_height - 16) // 2))" in source
    assert "pmax=(17, max(0, (METRICS.row_height - 16) // 2) + 16)" in source
    assert "add_child_window" not in source[source.find("icon_slot = dpg.add_drawlist("):source.find("dpg.move_item(tag, parent=name)")]
