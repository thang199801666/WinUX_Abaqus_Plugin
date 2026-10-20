"""Behavioral coverage of the release gate after an external HWND closes."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from DearUIQt import input_gate as gate


@pytest.fixture
def native_gate(monkeypatch):
    monkeypatch.setattr(gate, "_native_modal_tokens", set())
    monkeypatch.setattr(gate, "_native_modal_release_pending", False)
    monkeypatch.setattr(gate, "_native_modal_release_guard_until_frame", -1)
    monkeypatch.setattr(gate, "_native_surface_press_hwnd", None)
    monkeypatch.setattr(gate, "_native_release_guard_until_frame", -1)
    monkeypatch.setattr(gate, "_native_surface_under_pointer", lambda: None)
    monkeypatch.setattr(gate, "os", SimpleNamespace(name="nt"))
    key_state = Mock(return_value=0)
    monkeypatch.setattr(gate.ctypes, "windll", SimpleNamespace(
        user32=SimpleNamespace(GetAsyncKeyState=key_state)))
    # _mouse_button_down() is GetAsyncKeyState-authoritative on Windows; the
    # DPG backend no longer participates in the release gate, so patching the
    # backend proxy here is neither possible nor meaningful.
    frame = {"value": 10}
    monkeypatch.setattr(gate, "_frame_count", lambda: frame["value"])
    return frame, key_state


def test_modal_close_release_does_not_wait_forever_on_stale_dpg_press(
        native_gate, monkeypatch):
    frame, keys = native_gate
    token = object()
    gate.acquire_native_modal_input(token)
    assert gate.native_background_input_blocked()
    gate.release_native_modal_input(token)
    assert gate.native_background_input_blocked()
    frame["value"] += 1
    assert gate.native_background_input_blocked()
    frame["value"] += 1
    assert not gate.native_background_input_blocked()
    assert not gate.native_modal_input_active()


def test_real_held_button_remains_blocked_until_release_and_render_guard(
        native_gate, monkeypatch):
    frame, keys = native_gate
    keys.return_value = 0x8000
    token = object()
    gate.acquire_native_modal_input(token)
    gate.release_native_modal_input(token)
    for _ in range(4):
        frame["value"] += 1
        assert gate.native_background_input_blocked()
    keys.return_value = 0
    assert gate.native_background_input_blocked()
    frame["value"] += 2
    assert not gate.native_background_input_blocked()


def test_released_native_surface_capture_cannot_stick_on_dpg_state(native_gate, monkeypatch):
    frame, keys = native_gate
    monkeypatch.setattr(gate, "_native_surface_press_hwnd", 123)
    assert gate.native_background_input_blocked()
    frame["value"] += 2
    assert not gate.native_background_input_blocked()
    assert gate._native_surface_press_hwnd is None


def test_closing_one_modal_does_not_release_another_modal(
        native_gate, monkeypatch):
    first, second = object(), object()
    gate.acquire_native_modal_input(first)
    gate.acquire_native_modal_input(second)
    gate.release_native_modal_input(first)
    assert gate.native_background_input_blocked()
    assert gate.native_modal_input_active()
    gate.release_native_modal_input(second)
    assert not gate.native_modal_input_active()
