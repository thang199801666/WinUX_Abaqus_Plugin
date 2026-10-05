from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LISTVIEW = ROOT / "WinUx" / "components" / "explorer_list_view.py"
FILE_PANEL = ROOT / "WinUx" / "components" / "file_panel.py"
RENDERING = ROOT / "WinUx" / "components" / "explorer_rendering.py"
LAYOUT = ROOT / "WinUx" / "components" / "explorer_layout.py"


def test_file_panels_use_shared_qt_theme_and_metrics():
    source = FILE_PANEL.read_text(encoding="utf-8")
    assert 'theme="Explorer"' in source
    assert 'row_height=23' in source
    assert 'header_height=26' in source
    assert 'cell_padding=6' in source
    assert 'auto_fit_column_key="name"' in source


def test_winscp_theme_has_native_active_and_inactive_selection():
    source = (LISTVIEW.parent / "explorer_themes.py").read_text(encoding="utf-8")
    assert 'WINSCP = "WinSCP"' in source
    assert '"selected_text": (255, 255, 255, 255)' in source
    assert '"inactive_selected_fill": (217, 217, 217, 255)' in source
    assert '"inactive_selected_text": (30, 30, 30, 255)' in source
    assert '"show_row_lines": False' in source


def test_winscp_listview_supports_header_bevel_and_selection_foreground():
    source = "\n".join((LISTVIEW.read_text(encoding="utf-8"), RENDERING.read_text(encoding="utf-8"), LAYOUT.read_text(encoding="utf-8")))
    assert 'self._header_top_line' in source
    assert 'self._header_bottom_line' in source
    assert 'header_alignment = self.theme_config.get("header_alignment", "center")' in source
    assert 'text_color = self.theme_config.get("selected_text"' in source
    assert 'text_color = self.theme_config.get("inactive_selected_text"' in source
