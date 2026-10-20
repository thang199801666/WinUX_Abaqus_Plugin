from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "WinUx" / "dialogs" / "folder_browser_style.py"
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"


def test_sidebar_branch_indicator_is_owned_by_qtreewidget_geometry():
    form = FORM.read_text(encoding="utf-8")
    tree = (ROOT / "DearUIQt" / "modelview" / "tree_widget.py").read_text(encoding="utf-8")
    assert "QTreeWidget(" in form
    assert "draw_triangle" in tree
    assert "item.isExpanded()" in tree
    assert 'label=chr(GLYPHS["Expanded"])' not in form


def test_sidebar_place_selection_uses_qtreewidget_full_row_overlay():
    form = FORM.read_text(encoding="utf-8")
    tree = (ROOT / "DearUIQt" / "modelview" / "tree_widget.py").read_text(encoding="utf-8")
    assert "browser_sidebar_item_container_theme()" in form
    assert "item.setContainerTheme(browser_sidebar_item_container_theme())" in form
    assert "add_selectable(" in tree
    assert "add_drawlist(" in tree
    assert "height=self._row_height" in tree


def test_sidebar_drive_label_is_model_data_not_a_second_hit_target():
    form = FORM.read_text(encoding="utf-8")
    assert "def _set_place_label(self, item, text):" in form
    assert "item.setText(0, self._elide_sidebar_label(text))" in form
    assert "self._set_place_label(item, name)" in form
