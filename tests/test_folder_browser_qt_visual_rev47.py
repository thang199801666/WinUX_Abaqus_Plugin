"""Qt selection/toolbutton polish guards for WinUx 1.1.16."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "WinUx" / "dialogs" / "folder_browser_style.py"


def test_sidebar_selected_row_uses_active_qtreeview_palette():
    source = STYLE.read_text(encoding="utf-8")
    block = source.split("def browser_sidebar_row_theme():", 1)[1].split("def browser_sidebar_item_text_theme", 1)[0]
    assert "mvThemeCol_Header, p.SELECTION_ACTIVE" in block
    assert "mvThemeCol_HeaderHovered, p.SELECTION_ACTIVE_HOVER" in block
    assert "mvThemeCol_HeaderActive, p.SELECTION_ACTIVE_PRESSED" in block
    assert "mvThemeCol_Text, p.SELECTION_TEXT" in block


def test_checked_view_toolbutton_is_sunken_not_permanently_focus_blue():
    source = STYLE.read_text(encoding="utf-8")
    block = source.split("def browser_tool_button_theme", 1)[1].split("def browser_inline_action_theme", 1)[0]
    assert "p.BORDER if checked" in block
    assert "p.FOCUS if checked" not in block


def test_qfiledialog_footer_and_selection_bar_keep_compact_horizontal_margins():
    source = STYLE.read_text(encoding="utf-8")
    footer = source.split("def browser_footer_theme", 1)[1].split("def browser_sidebar_section_text_theme", 1)[0]
    selection = source.split("def browser_selection_bar_theme", 1)[1].split("def browser_separator_theme", 1)[0]
    assert "mvStyleVar_WindowPadding, 12, 8" in footer
    assert "mvStyleVar_WindowPadding, 4, 4" in selection
