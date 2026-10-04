from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLBAR = ROOT / "WinUx" / "components" / "toolbar.py"
FILE_PANEL = ROOT / "WinUx" / "components" / "file_panel.py"
VIEW = ROOT / "WinUx" / "view.py"
STYLE = ROOT / "WinUx" / "widgets" / "imgui_qt_style.py"


def test_file_toolbar_uses_shared_imgui_qt_toolbar_path_and_status_themes():
    source = TOOLBAR.read_text(encoding="utf-8")
    for token in (
        "imgui_tool_bar_theme", "imgui_tool_button_theme",
        "imgui_path_bar_theme", "imgui_status_bar_theme",
        "COLLAPSED_HEIGHT = 38", "SEARCH_ROW_HEIGHT = 36",
    ):
        assert token in source


def test_path_selector_is_compact_left_aligned_qlineedit_like_surface():
    style = STYLE.read_text(encoding="utf-8")
    toolbar = TOOLBAR.read_text(encoding="utf-8")
    assert "def path_bar_theme" in style
    assert "mvStyleVar_ButtonTextAlign" in style
    assert "segoeuib.ttf" in toolbar
    assert "add_font(str(font_path), 16)" in toolbar
    assert "height=28" in toolbar


def test_file_status_strips_share_qstatusbar_palette_and_compact_height():
    panel = FILE_PANEL.read_text(encoding="utf-8")
    view = VIEW.read_text(encoding="utf-8")
    style = STYLE.read_text(encoding="utf-8")
    assert "STATUS_HEIGHT = 22" in panel
    assert "FILE_STATUS_HEIGHT = 22" in view
    assert "file_status_bar_theme()" in panel
    assert "file_status_bar_theme()" in view
    assert "def status_bar_theme" in style
    assert "def status_text_theme" in style


def test_file_toolbar_exposes_qtoolbar_like_retained_properties_without_qt_backend():
    source = TOOLBAR.read_text(encoding="utf-8")
    for token in (
        "def setIconSize", "def iconSize", "def setMovable",
        "def isMovable", "def setFloatable", "def isFloatable",
    ):
        assert token in source
    assert "PyQt" not in source
    assert "PySide" not in source
    assert "tkinter" not in source
