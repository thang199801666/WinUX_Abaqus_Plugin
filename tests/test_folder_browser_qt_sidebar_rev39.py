from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"


def test_qtree_sidebar_fill_contract_is_centralized_in_dearuiqt():
    source = FORM.read_text(encoding="utf-8")
    tree = (ROOT / "DearUIQt" / "modelview" / "tree_widget.py").read_text(encoding="utf-8")
    assert "QTreeWidget(" in source
    assert "width=-1" in tree
    assert "height=self._row_height" in tree


def test_sidebar_place_click_navigates_through_tree_item_user_data():
    source = FORM.read_text(encoding="utf-8")
    assert "item.setData(0, Qt.UserRole, str(path))" in source
    assert "def _place_tree_clicked(self, item, _column=0):" in source
    assert "def _place_clicked(self, _sender, _app_data, path):" in source
    assert "self.view.after(1, self._commit_place_navigation)" in source
