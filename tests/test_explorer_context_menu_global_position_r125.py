from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_explorer_context_menus_use_explicit_global_popup_api():
    source = (ROOT / "WinUx" / "ui" / "components" / "explorer_context_menu.py").read_text(encoding="utf-8")
    assert "QCursor.screenPos" in source
    assert source.count("popupGlobal(") >= 2


def test_explorer_pointer_dispatch_does_not_forward_ambiguous_dpg_mouse_position():
    source = (ROOT / "WinUx" / "ui" / "components" / "explorer_pointer_dispatch.py").read_text(encoding="utf-8")
    block = source.split("def _on_right_click", 1)[1].split("def ", 1)[0]
    assert "self._show_item_context_menu()" in block
    assert "QCursor.pos()" not in block
