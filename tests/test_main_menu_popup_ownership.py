from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEW = (ROOT / "WinUx" / "view.py").read_text(encoding="utf-8")
MENU = (ROOT / "DearUIQt" / "qt" / "menu.py").read_text(encoding="utf-8")
MENUBAR = (ROOT / "DearUIQt" / "qt" / "menu_bar.py").read_text(encoding="utf-8")
POINTER = (ROOT / "WinUx" / "ui" / "components" / "explorer_pointer_dispatch.py").read_text(encoding="utf-8")


def _menu_block():
    start = VIEW.index("    def _build_menu(self):")
    end = VIEW.index("    @staticmethod\n    def _add_icon_menu_item", start)
    return VIEW[start:end]


def test_main_application_menu_uses_dearuiqt_qmenubar_not_native_dpg_popup():
    block = _menu_block()
    assert "QMenuBar(backend=dpg" in block
    assert 'menu_bar.addMenu("View"' in block
    assert 'action("Job Schedule"' in block
    assert "with dpg.menu_bar()" not in block
    assert "with dpg.menu(" not in block


def test_qmenubar_keeps_bar_interactive_but_shields_application_body():
    assert "menu.setInputShieldTop(popup_y)" in MENUBAR
    assert "menu.popup((x, popup_y))" in MENUBAR
    assert "viewport_height - top" in MENU
    assert "acquire_popup_input(self)" in MENU
    assert "self.backend.focus_item(tag)" in MENU
    assert "self.backend.focus_item(self.tag)" in MENU


def test_explorer_checks_global_popup_ownership_before_hover_or_click():
    move = POINTER.split("def _on_mouse_move", 1)[1].split("def _on_left_down", 1)[0]
    click = POINTER.split("def _on_left_down", 1)[1].split("def _on_left_release", 1)[0]
    assert move.index("pointer_input_is_blocked(self)") < move.index("_update_header_hover_state()")
    assert "_clear_pointer_hover_feedback()" in move
    assert "pointer_input_is_blocked(self)" in click
