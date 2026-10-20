from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIALOGS = ROOT / "WinUx" / "dialogs" / "theme.py"

# WinUx/dialogs/theme.py is a thin alias for the shared DearUIQt dialog theme
# (DialogMetrics + style factories), so resolve the canonical source directly.
THEME = ROOT / "DearUIQt" / "dialogs" / "theme.py"


def test_shared_imgui_dialog_footer_has_balanced_vertical_space():
    theme = THEME.read_text(encoding="utf-8")
    assert "FOOTER_HEIGHT = 48" in theme
    assert "mvStyleVar_WindowPadding, 12, 8" in theme


def test_folder_selector_footer_uses_same_bottom_safe_margin():
    style = (ROOT / "WinUx" / "dialogs" / "folder_browser_style.py").read_text(encoding="utf-8")
    block = style.split("def browser_footer_theme", 1)[1].split("def browser_sidebar_section_text_theme", 1)[0]
    assert "ThemeStyle.WINDOW_PADDING: (12, 8)" in block


# test_native_dialog_footer_spacing_is_not_flush_to_bottom_edge was superseded
# by test_shared_imgui_dialog_footer_has_balanced_vertical_space + test_qt_
# dialog_style: the legacy native Tk login runtime (WinUx/dialogs/native_login_
# runtime.py) was removed; login/dialog footer spacing now comes from the
# shared DearUIQt DialogMetrics footer (FOOTER_HEIGHT/WINDOW_PADDING).
