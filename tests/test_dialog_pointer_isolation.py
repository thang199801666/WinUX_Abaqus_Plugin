"""Release after a disappearing dialog cannot reach a background handler."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from DearUIQt import input_gate as gate


@pytest.fixture
def pointer(monkeypatch):
    state = SimpleNamespace(down=False, frame=10, inside=True)
    monkeypatch.setattr(gate, "_pointer_owner", None)
    monkeypatch.setattr(gate, "_surface_press_item", None)
    monkeypatch.setattr(gate, "_release_guard_until_frame", -1)
    monkeypatch.setattr(gate, "_protected_items", set())
    monkeypatch.setattr(gate, "native_background_input_blocked", lambda: False)
    monkeypatch.setattr(gate, "_mouse_button_down", lambda: state.down)
    monkeypatch.setattr(gate, "_frame_count", lambda: state.frame)
    monkeypatch.setattr(gate, "_item_contains_mouse", lambda item, mouse=None: state.inside)
    monkeypatch.setattr(gate, "_protected_surface_under_pointer", lambda: None)
    return state


def test_close_on_mouse_up_before_any_background_handler_consumes_release(pointer):
    gate.guard_pointer_surface_release("dialog")
    gate.unregister_pointer_protected_item("dialog")
    pointer.inside = False
    assert gate.pointer_input_is_blocked(object())
    pointer.frame += 1
    assert gate.pointer_input_is_blocked(object())
    pointer.frame += 1
    assert not gate.pointer_input_is_blocked(object())


def test_dialog_press_stays_blocked_outside_and_after_dialog_disappears(pointer):
    pointer.down = True
    gate.guard_pointer_surface_release("dialog")
    pointer.inside = False
    for _ in range(4):
        pointer.frame += 1
        assert gate.pointer_input_is_blocked(object())
    pointer.down = False
    assert gate.pointer_input_is_blocked(object())
    pointer.frame += 2
    assert not gate.pointer_input_is_blocked(object())


def test_programmatic_close_away_from_pointer_does_not_block_unrelated_input(pointer):
    pointer.inside = False
    gate.guard_pointer_surface_release("dialog")
    assert not gate.pointer_input_is_blocked(object())


@pytest.mark.parametrize("operation", ["hide", "destroy"])
def test_dialog_latches_release_before_hiding_its_geometry(monkeypatch, operation):
    from DearUIQt.dialogs import base, qt_dialog
    events = []
    backend = SimpleNamespace(
        does_item_exist=lambda tag: True,
        hide_item=lambda tag: events.append("hide"),
        configure_item=lambda tag, **kw: events.append("hide"),
    )
    monkeypatch.setattr(base, "dpg", backend)
    monkeypatch.setattr(qt_dialog, "dpg", backend)
    for module in (base, qt_dialog):
        monkeypatch.setattr(module, "guard_pointer_surface_release", lambda tag: events.append("guard"))
        monkeypatch.setattr(module, "unregister_escape_target", lambda tag: None)
    monkeypatch.setattr(qt_dialog, "unregister_modal_window", lambda tag: None)
    dialog = object.__new__(qt_dialog.QtDialog if operation == "hide" else base.DialogBase)
    dialog.tag = "dialog"
    dialog._closed = dialog._destroy_scheduled = False
    dialog.view = SimpleNamespace(after=Mock())
    getattr(dialog, operation)()
    assert events[:2] == ["guard", "hide"]
