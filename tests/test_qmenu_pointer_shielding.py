"""Qt-style popup menus must never click through to widgets below them."""
from types import ModuleType, SimpleNamespace
import sys

import pytest

try:
    from DearUIQt import input_gate as gate
except ModuleNotFoundError as exc:
    if exc.name not in {"dearpygui", "dearpygui.dearpygui"}:
        raise
    package = ModuleType("dearpygui")
    backend = ModuleType("dearpygui.dearpygui")
    package.dearpygui = backend
    sys.modules.setdefault("dearpygui", package)
    sys.modules.setdefault("dearpygui.dearpygui", backend)
    from DearUIQt import input_gate as gate


@pytest.fixture
def pointer_gate(monkeypatch):
    state = SimpleNamespace(frame=20)
    monkeypatch.setattr(gate, "_pointer_owner", None)
    monkeypatch.setattr(gate, "_popup_input_owners", [])
    monkeypatch.setattr(gate, "_popup_release_guard_until_frame", -1)
    monkeypatch.setattr(gate, "_surface_press_item", None)
    monkeypatch.setattr(gate, "_release_guard_until_frame", -1)
    monkeypatch.setattr(gate, "native_background_input_blocked", lambda: False)
    monkeypatch.setattr(gate, "_mouse_button_down", lambda: False)
    monkeypatch.setattr(gate, "_frame_count", lambda: state.frame)
    monkeypatch.setattr(gate, "_protected_surface_under_pointer", lambda: None)
    return state


def test_popup_owns_application_pointer_until_hidden(pointer_gate):
    menu = object()
    background = object()
    assert gate.acquire_popup_input(menu)
    assert not gate.pointer_input_is_blocked(menu)
    assert gate.pointer_input_is_blocked(background)


def test_closing_click_is_consumed_but_next_frame_is_not(pointer_gate):
    menu = object()
    background = object()
    gate.acquire_popup_input(menu)
    assert gate.release_popup_input(menu, consume_gesture=True)
    # Other global handlers dispatched from the same DPG event/frame are blocked.
    assert gate.pointer_input_is_blocked(background)
    pointer_gate.frame += 1
    # A fresh Qt-style press on the next frame is independent and passes.
    assert not gate.pointer_input_is_blocked(background)


def test_programmatic_hide_does_not_add_spurious_click_guard(pointer_gate):
    menu = object()
    gate.acquire_popup_input(menu)
    assert gate.release_popup_input(menu, consume_gesture=False)
    assert not gate.pointer_input_is_blocked(object())


def test_qmenu_self_registers_and_uses_popup_capture():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "DearUIQt" / "qt" / "menu.py").read_text(encoding="utf-8")
    assert "register_pointer_protected_item(self.tag)" in source
    assert "acquire_popup_input(self)" in source
    assert "release_popup_input(self, consume_gesture=bool(consume_pointer))" in source
    assert "root.hide(consume_pointer=True)" in source


def test_explorer_custom_context_menu_uses_same_popup_grab_contract():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    context = (root / "WinUx" / "ui" / "components" / "explorer_context_menu.py").read_text(encoding="utf-8")
    dispatch = (root / "WinUx" / "ui" / "components" / "explorer_pointer_dispatch.py").read_text(encoding="utf-8")
    assert "acquire_popup_input(self)" in context
    assert "release_popup_input(self, consume_gesture=bool(consume_pointer))" in context
    assert "self._acquire_context_popup_input()" in dispatch
    assert "self._hide_context_menus(consume_pointer=True)" in dispatch


def test_popup_hover_suppresses_explorer_header_feedback():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    dispatch = (root / "WinUx" / "ui" / "components" / "explorer_pointer_dispatch.py").read_text(encoding="utf-8")
    listview = (root / "WinUx" / "ui" / "components" / "explorer_list_view.py").read_text(encoding="utf-8")

    # Popup ownership must behave like Qt mouse-grab + leave delivery: the
    # background view cannot keep a stale header/resize hover while occluded.
    assert "if pointer_input_is_blocked(self):\n            self._clear_pointer_hover_feedback()" in dispatch
    assert "def _clear_pointer_hover_feedback(self):" in listview
    assert "self._header_hover_key = None" in listview
    assert "self._hover_separator_key = None" in listview
    assert 'self._set_mouse_cursor("mvMouseCursor_Arrow")' in listview
