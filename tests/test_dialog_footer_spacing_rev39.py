from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIALOGS = ROOT / "WinUx" / "dialogs"


def test_shared_imgui_dialog_footer_has_balanced_vertical_space():
    theme = (DIALOGS / "theme.py").read_text(encoding="utf-8")
    assert "FOOTER_HEIGHT = 48" in theme
    assert "mvStyleVar_WindowPadding, 12, 8" in theme


def test_folder_selector_footer_uses_same_bottom_safe_margin():
    style = (DIALOGS / "folder_browser_style.py").read_text(encoding="utf-8")
    block = style.split("def browser_footer_theme", 1)[1].split("def browser_sidebar_section_text_theme", 1)[0]
    assert "mvStyleVar_WindowPadding, 12, 8" in block


def test_native_dialog_footer_spacing_is_not_flush_to_bottom_edge():
    modern = (DIALOGS / "modern.py").read_text(encoding="utf-8")
    login = (DIALOGS / "native_login_runtime.py").read_text(encoding="utf-8")
    assert "FOOTER_PAD_Y = 12" in modern
    assert 'padding=(10, 9, 10, 14)' in login
