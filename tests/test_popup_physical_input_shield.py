from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_qmenu_uses_physical_transparent_viewport_shield():
    source = (ROOT / "DearUIQt" / "qt" / "menu.py").read_text(encoding="utf-8")
    assert "self._input_shield_tag" in source
    assert "no_background=True" in source
    assert "get_viewport_client_width" in source
    assert "get_viewport_client_height" in source
    assert "self._show_input_shield()" in source
    assert "self._hide_input_shield()" in source
    # Shield must be created before the popup tag so normal z ordering places
    # the popup above the blocker.
    assert source.index("self._input_shield_tag = backend.generate_uuid()") < source.index("self.tag = backend.generate_uuid()")


def test_explorer_context_menu_uses_same_physical_shield_contract():
    source = (ROOT / "WinUx" / "ui" / "components" / "explorer_context_menu.py").read_text(encoding="utf-8")
    dispatch = (ROOT / "WinUx" / "ui" / "components" / "explorer_pointer_dispatch.py").read_text(encoding="utf-8")
    assert "_ensure_context_input_shield" in source
    assert "no_background=True" in source
    assert "_show_context_input_shield" in source
    assert "_hide_context_input_shield" in source
    assert "self._show_context_input_shield()" in dispatch
    assert "dpg.focus_item(self.itemmenu_tag)" in dispatch


def test_popup_shield_is_released_on_every_context_menu_teardown():
    source = (ROOT / "WinUx" / "ui" / "components" / "explorer_context_menu.py").read_text(encoding="utf-8")
    release = source[source.index("def _release_context_popup_input"):source.index("def set_context_menu")]
    assert "finally:" in release
    assert "self._hide_context_input_shield()" in release
