"""Regressions for two-phase native QDialog owner activation."""
from types import SimpleNamespace
from unittest.mock import Mock

import DearUIQt.backends.native_windows as native_windows
from DearUIQt.backends.native_windows import NativeWindowBackend


class FakeUser32:
    def __init__(self, *, child=1234, owner=5678, foreground=1234,
                 child_visible=True, owner_visible=True, owner_enabled=False,
                 input_tick=100, foreign_pid=99999):
        self.child = child
        self.owner = owner
        self.foreground = foreground
        self.child_visible = child_visible
        self.owner_visible = owner_visible
        self.owner_enabled = owner_enabled
        self.input_tick = input_tick
        self.foreign_pid = foreign_pid
        self.calls = []
        self.GetWindow = Mock(side_effect=lambda _hwnd, _rel: self.owner)
        self.IsWindow = Mock(return_value=True)
        self.IsWindowVisible = Mock(side_effect=self._visible)
        self.GetForegroundWindow = Mock(side_effect=lambda: self.foreground)
        self.IsWindowEnabled = Mock(side_effect=lambda hwnd: self.owner_enabled)
        self.EnableWindow = Mock(side_effect=self._enable)
        self.BringWindowToTop = Mock(side_effect=lambda _hwnd: self.calls.append("raise") or True)
        self.SetForegroundWindow = Mock(side_effect=self._foreground)
        self.SetActiveWindow = Mock(side_effect=lambda _hwnd: self.calls.append("active") or 0)
        self.SetFocus = Mock(side_effect=lambda _hwnd: self.calls.append("focus") or 0)
        self.ShowWindow = Mock(side_effect=self._show)
        self.GetLastInputInfo = Mock(side_effect=self._last_input)
        self.GetWindowThreadProcessId = Mock(side_effect=self._pid)

    @staticmethod
    def _value(hwnd):
        return int(getattr(hwnd, "value", hwnd) or 0)

    def _visible(self, hwnd):
        hwnd = self._value(hwnd)
        if hwnd == self.child:
            return self.child_visible
        if hwnd == self.owner:
            return self.owner_visible
        return True

    def _enable(self, _hwnd, enabled):
        self.owner_enabled = bool(enabled)
        self.calls.append("enable")
        return True

    def _foreground(self, hwnd):
        self.foreground = self._value(hwnd)
        self.calls.append("foreground")
        return True

    def _show(self, hwnd, command):
        if self._value(hwnd) == self.owner:
            self.owner_visible = True
        self.calls.append(("show", command))
        return True

    def _last_input(self, info_ptr):
        info_ptr._obj.dwTime = self.input_tick
        return True

    def _pid(self, hwnd, pid_ptr):
        hwnd = self._value(hwnd)
        pid_ptr._obj.value = self.foreign_pid if hwnd not in (self.child, self.owner) else 1
        return 1


def _backend():
    extension = SimpleNamespace(
        dearuiqt_enable_native_windows=Mock(return_value=True),
        dearuiqt_native_windows_enabled=Mock(return_value=True),
        dearuiqt_configure_native_window=Mock(),
        dearuiqt_native_window_handle=Mock(return_value=1234),
    )
    return NativeWindowBackend(SimpleNamespace(internal_dpg=extension))


def test_platform_teardown_foreground_fallback_is_repaired_after_child_disappears(monkeypatch):
    api = FakeUser32(owner_enabled=False)
    monkeypatch.setattr(native_windows, "_windows_user32", lambda: api)
    monkeypatch.setattr(native_windows.os, "getpid", lambda: 111)
    backend = _backend()

    lease = backend.beginOwnerClose(99)
    assert lease is not None
    assert api.foreground == api.owner

    # The next renderer frame removes the child HWND and GLFW/Windows chooses a
    # different application's window even though the user made no new input.
    api.child_visible = False
    api.foreground = 9999
    api.owner_enabled = True
    api.foreign_pid = 222
    assert backend.repairOwnerAfterHide(lease) is True
    assert api.foreground == api.owner
    assert "raise" in api.calls


def test_new_user_input_after_close_prevents_post_render_focus_steal(monkeypatch):
    api = FakeUser32(owner_enabled=False, input_tick=100)
    monkeypatch.setattr(native_windows, "_windows_user32", lambda: api)
    monkeypatch.setattr(native_windows.os, "getpid", lambda: 111)
    backend = _backend()
    lease = backend.beginOwnerClose(99)

    api.child_visible = False
    api.owner_enabled = True
    api.foreground = 9999
    api.input_tick = 101  # real Alt-Tab/click after the OK/Cancel gesture
    before = api.SetForegroundWindow.call_count
    assert backend.repairOwnerAfterHide(lease) is True
    assert api.foreground == 9999
    assert api.SetForegroundWindow.call_count == before


def test_post_render_repair_restores_accidentally_hidden_owner_without_activation(monkeypatch):
    api = FakeUser32(owner_enabled=False, input_tick=100)
    monkeypatch.setattr(native_windows, "_windows_user32", lambda: api)
    backend = _backend()
    lease = backend.beginOwnerClose(99)

    # Simulate the main GLFW viewport being hidden as the final secondary
    # viewport is destroyed. Visibility is repaired with SW_SHOWNOACTIVATE.
    api.child_visible = False
    api.owner_visible = False
    api.owner_enabled = True
    assert backend.repairOwnerAfterHide(lease) is True
    api.ShowWindow.assert_called()
    assert api.owner_visible


def test_same_process_replacement_dialog_wins_over_stale_owner_repair(monkeypatch):
    api = FakeUser32(owner_enabled=False, input_tick=100)
    monkeypatch.setattr(native_windows, "_windows_user32", lambda: api)
    monkeypatch.setattr(native_windows.os, "getpid", lambda: 111)
    backend = _backend()
    lease = backend.beginOwnerClose(99)

    api.child_visible = False
    api.owner_enabled = True
    api.foreground = 7777
    api.foreign_pid = 111  # newly opened in-process DearUIQt dialog
    before = api.SetForegroundWindow.call_count
    assert backend.repairOwnerAfterHide(lease) is True
    assert api.foreground == 7777
    assert api.SetForegroundWindow.call_count == before


def test_repair_waits_until_child_is_hidden_and_owner_enabled(monkeypatch):
    api = FakeUser32(owner_enabled=False)
    monkeypatch.setattr(native_windows, "_windows_user32", lambda: api)
    backend = _backend()
    lease = backend.beginOwnerClose(99)

    # First verification is intentionally too early.
    assert backend.repairOwnerAfterHide(lease) is None
    api.child_visible = False
    api.owner_enabled = False
    assert backend.repairOwnerAfterHide(lease) is None
    api.owner_enabled = True
    assert backend.repairOwnerAfterHide(lease) is True
