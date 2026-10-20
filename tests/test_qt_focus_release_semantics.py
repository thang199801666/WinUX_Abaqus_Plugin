"""Regressions for Qt-like focus/modality and close-release mouse semantics."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from DearUIQt import input_gate as gate

ROOT = Path(__file__).resolve().parents[1]
DIALOG_SOURCE = (ROOT / "DearUIQt/dialogs/qt_dialog.py").read_text(encoding="utf-8")


def _native_gate(monkeypatch, *, down=False):
    monkeypatch.setattr(gate, "_native_modal_tokens", set())
    monkeypatch.setattr(gate, "_native_modal_release_pending", False)
    monkeypatch.setattr(gate, "_native_modal_release_started_down", False)
    monkeypatch.setattr(gate, "_native_modal_release_guard_until_frame", -1)
    monkeypatch.setattr(gate, "_native_surface_press_hwnd", None)
    monkeypatch.setattr(gate, "_native_surface_press_started_down", False)
    monkeypatch.setattr(gate, "_native_release_guard_until_frame", -1)
    monkeypatch.setattr(gate, "_native_surface_under_pointer", lambda: None)
    monkeypatch.setattr(gate, "os", SimpleNamespace(name="nt"))
    state = {"down": bool(down), "frame": 10}
    key_state = Mock(side_effect=lambda _vk: 0x8000 if state["down"] else 0)
    monkeypatch.setattr(gate.ctypes, "windll", SimpleNamespace(
        user32=SimpleNamespace(GetAsyncKeyState=key_state)), raising=False)
    monkeypatch.setattr(gate, "_frame_count", lambda: state["frame"])
    return state


def test_fresh_press_after_mouse_up_close_is_not_swallowed(monkeypatch):
    state = _native_gate(monkeypatch, down=False)
    token = object()
    gate.acquire_native_modal_input(token)
    gate.release_native_modal_input(token)

    # Same mouse-up/render turn is protected against click-through.
    assert gate.native_background_input_blocked()

    # A new physical press is a new Qt mouse gesture, even if it arrives before
    # the extra render-guard frame has elapsed.
    state["down"] = True
    assert not gate.native_background_input_blocked()


def test_held_close_gesture_remains_captured_until_release(monkeypatch):
    state = _native_gate(monkeypatch, down=True)
    token = object()
    gate.acquire_native_modal_input(token)
    gate.release_native_modal_input(token)
    assert gate.native_background_input_blocked()
    state["frame"] += 2
    assert gate.native_background_input_blocked()

    state["down"] = False
    assert gate.native_background_input_blocked()
    state["frame"] += 2
    assert not gate.native_background_input_blocked()


def test_modeless_qdialog_is_pointer_surface_not_application_modal():
    show_start = DIALOG_SOURCE.index("    def show(self):")
    show_end = DIALOG_SOURCE.index("    def raise_(self):", show_start)
    show = DIALOG_SOURCE[show_start:show_end]
    assert "if self.modal:" in show
    assert "register_modal_window(self.tag)" in show
    assert "register_pointer_protected_item(self.tag)" in show


def test_modal_hide_releases_explicit_pointer_capture():
    hide_start = DIALOG_SOURCE.index("    def hide(self):")
    hide_end = DIALOG_SOURCE.index("    def event(self, event):", hide_start)
    hide = DIALOG_SOURCE[hide_start:hide_end]
    assert "if self.modal:" in hide
    assert "release_pointer_input()" in hide


def test_qdialog_active_window_includes_focused_descendants():
    assert "def isActiveWindow(self):" in DIALOG_SOURCE
    assert "self._item_belongs_to(focused, self.tag)" in DIALOG_SOURCE
    assert "not dialog.isActiveWindow()" in DIALOG_SOURCE


def test_qdialog_tab_chain_matches_qt_forward_and_backward_navigation():
    assert "def setTabOrder(self, first, second):" in DIALOG_SOURCE
    assert "def focusNextPrevChild(self, next=True):" in DIALOG_SOURCE
    assert 'key == getattr(dpg, "mvKey_Tab", None)' in DIALOG_SOURCE
    assert "next=not shift" in DIALOG_SOURCE


def test_nested_focus_restore_prefers_logical_qobject_parent():
    restore = DIALOG_SOURCE.split("    def _restore_embedded_owner_focus(self):", 1)[1]
    restore = restore.split("    def delete_owned_item", 1)[0]
    assert "parent = self.parent" in restore
    assert "isinstance(parent, QtDialog)" in restore
    assert "self._item_belongs_to(target, parent.tag)" in restore


def test_modeless_close_restores_focus_only_when_it_owned_focus():
    hide = DIALOG_SOURCE.split("    def hide(self):", 1)[1].split("    def event(self, event):", 1)[0]
    assert "self.modal or self._item_belongs_to(focused_item, self.tag)" in hide
    assert "self._activation_owned" not in hide.split("self._restore_focus_on_hide = bool(", 1)[1].split(")", 1)[0]

def test_native_qdialog_uses_two_phase_owner_focus_transaction():
    hide = DIALOG_SOURCE.split("    def hide(self):", 1)[1].split("    def event(self, event):", 1)[0]
    destroy = DIALOG_SOURCE.split("    def destroy(self):", 1)[1].split("\n\nQDialog = QtDialog", 1)[0]
    begin = "native_owner_lease = self._begin_native_owner_close()"
    repair = "self._schedule_native_owner_repair(native_owner_lease)"
    assert begin in hide and repair in hide
    assert begin in destroy and repair in destroy
    assert hide.index(begin) < hide.index("dpg.hide_item(self.tag)") < hide.index(repair)
    assert destroy.index(begin) < destroy.index("super().destroy()") < destroy.index(repair)
    assert 'schedule = getattr(self.view, "after_render", None)' in DIALOG_SOURCE
