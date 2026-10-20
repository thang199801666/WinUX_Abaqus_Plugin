"""A modeless native window behind WinUx must not intercept Explorer clicks."""
from types import SimpleNamespace

import pytest

from DearUIQt import input_gate as gate


@pytest.fixture
def protected(monkeypatch):
    gate.reset_pointer_input_gate()
    mouse = [(65.0, 40.0)]
    monkeypatch.setattr(gate, "_mouse_position", lambda: mouse[0])
    monkeypatch.setattr(gate, "_mouse_button_down", lambda: False)
    monkeypatch.setattr(gate, "_native_cursor_position", lambda: None)
    monkeypatch.setattr(gate, "native_background_input_blocked", lambda: False)
    monkeypatch.setattr(gate, "_frame_count", lambda: 25)
    # A renderer rectangle covers the Explorer row but native Z-order does not.
    fake = SimpleNamespace(
        does_item_exist=lambda tag: tag == "transfer",
        is_item_shown=lambda tag: True,
        is_item_hovered=lambda tag: False,
        get_item_rect_min=lambda tag: (0, 0),
        get_item_rect_size=lambda tag: (800, 300),
    )
    monkeypatch.setattr(gate, "dpg", fake)
    try:
        yield mouse
    finally:
        gate.reset_pointer_input_gate()


def test_native_modeless_behind_main_does_not_block_explorer(protected):
    under_cursor = {"native": False}
    gate.register_pointer_protected_item(
        "transfer", hit_test=lambda point: under_cursor["native"])
    assert gate.pointer_input_is_blocked(object()) is False
    under_cursor["native"] = True
    assert gate.pointer_input_is_blocked(object()) is True
    under_cursor["native"] = False
    assert gate.pointer_input_is_blocked(object()) is False


def test_generic_protected_surface_still_prevents_click_through(protected):
    gate.register_pointer_protected_item("transfer")
    assert gate.pointer_input_is_blocked(object()) is True
    gate.unregister_pointer_protected_item("transfer")
    assert gate.pointer_input_is_blocked(object()) is False


def test_modeless_hit_test_lifecycle_clears_on_hide_and_context_reset(protected):
    gate.register_pointer_protected_item("transfer", hit_test=lambda point: True)
    assert gate.pointer_input_is_blocked(object()) is True
    gate.unregister_pointer_protected_item("transfer")
    assert "transfer" not in gate._protected_hit_tests
    assert gate.pointer_input_is_blocked(object()) is False
    gate.register_pointer_protected_item("transfer", hit_test=lambda point: True)
    gate.reset_pointer_input_gate()
    assert not gate._protected_hit_tests


def test_invalid_hit_test_does_not_leave_partial_registration(protected):
    with pytest.raises(TypeError):
        gate.register_pointer_protected_item("transfer", hit_test=object())
    assert "transfer" not in gate._protected_hit_tests


def test_native_hit_test_uses_os_desktop_coordinates(protected, monkeypatch):
    recorded = []
    monkeypatch.setattr(gate, "_native_cursor_position", lambda: (-180, 420))
    gate.register_pointer_protected_item(
        "transfer", hit_test=lambda point: recorded.append(point) or False)
    assert gate.pointer_input_is_blocked(object()) is False
    assert recorded == [(-180, 420)]


def test_qdialog_wires_native_modeless_hit_testing():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "DearUIQt/dialogs/qt_dialog.py").read_text(encoding="utf-8")
    assert 'elif self._native_window_backend is not None:' in source
    assert 'hit_test=lambda point: self._native_window_backend.containsGlobalPoint(' in source
