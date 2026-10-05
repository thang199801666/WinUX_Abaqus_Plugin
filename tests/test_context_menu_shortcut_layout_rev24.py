from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ROOT / "WinUx" / "components" / "explorer_context_menu.py"
RENDER = ROOT / "WinUx" / "components" / "explorer_rendering.py"
PANEL = ROOT / "WinUx" / "components" / "file_panel.py"


def test_shortcuts_have_a_dedicated_right_aligned_slot():
    context = CONTEXT.read_text(encoding="utf-8")
    rendering = RENDER.read_text(encoding="utf-8")
    assert 'shortcut = str(spec.get("shortcut") or "")' in context
    assert 'shortcut_width = 58 if shortcut else 0' in context
    assert 'self._context_menu_shortcut_theme' in context
    assert 'mvStyleVar_ButtonTextAlign, 1.0, 0.5' in rendering


def test_file_menu_uses_explicit_accelerators_and_new_group():
    source = PANEL.read_text(encoding="utf-8")
    assert '"id": "new_group"' in source
    assert '"label": "New"' in source
    assert '"label": "New Folder"' in source
    assert '"shortcut": "F7"' in source
    assert '"label": "New File"' in source
    assert '"shortcut": "Ctrl+R"' in source
    assert 'Rename   F2' not in source
    assert 'New Folder   F7' not in source
