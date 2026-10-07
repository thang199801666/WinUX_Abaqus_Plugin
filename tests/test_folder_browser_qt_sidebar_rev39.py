from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"


def test_qtree_sidebar_selectables_use_zero_width_fill_contract():
    source = FORM.read_text(encoding="utf-8")
    # DearPyGui Selectable uses width=0 for the remaining content width.
    # Negative width is not the child-window fill contract and destroys hit testing.
    assert source.count('label="", width=0, height=METRICS.sidebar_row_height') >= 2
    assert 'label="", width=-1, height=METRICS.sidebar_row_height' not in source


def test_sidebar_place_click_navigates_through_explicit_user_data_callback():
    source = FORM.read_text(encoding="utf-8")
    assert "callback=self._place_clicked" in source
    assert "def _place_clicked(self, _sender, _app_data, path):" in source
    assert "self.view.after(1, self._commit_place_navigation)" in source
