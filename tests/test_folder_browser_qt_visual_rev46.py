"""QFileDialog/QTreeView polish guards for WinUx 1.1.15."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"
STYLE = ROOT / "WinUx" / "dialogs" / "folder_browser_style.py"


def test_sidebar_overlay_text_tracks_qtreeview_selected_palette():
    form = FORM.read_text(encoding="utf-8")
    style = STYLE.read_text(encoding="utf-8")
    assert "def browser_sidebar_item_text_theme" in style
    assert "p.HIGHLIGHT_TEXT if selected else p.TEXT" in style
    assert "self._sidebar_selected_text_theme" in form
    assert "dpg.bind_item_theme(label_item, self._sidebar_text_theme)" in form


def test_folder_list_outer_scroll_owner_keeps_shared_qt_scroller_chrome():
    form = FORM.read_text(encoding="utf-8")
    style = STYLE.read_text(encoding="utf-8")
    assert "def browser_list_viewport_theme" in style
    assert "add_dpg_scroller_style(dpg, track=p.WINDOW_ALT)" in style
    assert "dpg.bind_item_theme(self.listbox.tag, browser_list_viewport_theme())" in form
    assert "scrollY=True" not in form
