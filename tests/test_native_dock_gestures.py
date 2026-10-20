from types import SimpleNamespace
from unittest.mock import Mock

from WinUx.dialogs.native_dock_hosts import PlotDockHost
from WinUx.platform import native_dock_gesture as gesture
from WinUx.platform import floating_viewport as viewport


def host():
    value = object.__new__(PlotDockHost)
    value._closed = False
    value._ready = True
    value._hwnd, value._owner_hwnd = 200, 100
    value.post = Mock()
    value.view = SimpleNamespace(after=Mock(), _hide_dock_drop_preview=Mock(),
        _set_plot_dock_preview=Mock(), _floating_focus_suppressed=False)
    return value


def test_native_drop_uses_owner_client_coordinates_and_restores_override(monkeypatch):
    import WinUx.platform.dialog_focus as focus
    value = host()
    monkeypatch.setattr(focus, "window_state", lambda hwnd: (True, True, True))
    monkeypatch.setattr(focus, "foreground_hwnd", lambda: 200)
    monkeypatch.setattr(gesture, "client_position", lambda hwnd, position: (-20, 40))
    value.view._native_dock_pointer_candidates = ((999, 999),)

    def target():
        assert value.view._native_dock_pointer_candidates == ((-20, 40),)
        return "left"

    value.view._plot_dock_target_at_pointer = target
    value._handle_dock_gesture({"action": "drop", "position": [-1000, 100]})
    value.post.assert_called_once_with("request_dock")
    assert value._requested_dock_area == "left"
    assert value.view._native_dock_pointer_candidates == ((999, 999),)


def test_drop_outside_target_or_over_disabled_owner_never_docks(monkeypatch):
    import WinUx.platform.dialog_focus as focus
    value = host()
    monkeypatch.setattr(focus, "window_state", lambda hwnd: (True, True, True))
    monkeypatch.setattr(focus, "foreground_hwnd", lambda: 200)
    value._dock_target = lambda position: None
    value._handle_dock_gesture({"action": "drop", "position": [0, 0]})
    value.post.assert_not_called()
    monkeypatch.setattr(focus, "window_state", lambda hwnd: (True, True, False))
    value._handle_dock_gesture({"action": "toggle"})
    value.post.assert_not_called()


def test_preview_tracks_native_move_loop_but_not_resize_and_is_cleared_on_close(monkeypatch):
    import WinUx.platform.dialog_focus as focus
    value = host()
    mode = {"value": 1}
    monkeypatch.setattr(gesture, "gesture_mode", lambda hwnd: mode["value"])
    monkeypatch.setattr(gesture, "cursor_position", lambda: (100, 100))
    monkeypatch.setattr(focus, "foreground_hwnd", lambda: 200)
    value._dock_target = lambda point: "tabify"
    value._poll_dock_preview()
    value.view._set_plot_dock_preview.assert_called_once_with(True, "tabify")
    assert value._native_preview_active
    mode["value"] = 2
    value._poll_dock_preview()
    assert not value._native_preview_active
    value.view._hide_dock_drop_preview.assert_called_once()
    mode["value"] = 1
    value._poll_dock_preview()
    value._closed = True
    value._poll_dock_preview()
    assert not value._native_preview_active


def install_hook(monkeypatch, before, after):
    pending = []
    view = SimpleNamespace(after=lambda delay, cb, *args: pending.append((cb, args)))
    callback = Mock()
    rect = {"value": before}
    modes = []

    def native_loop(*args):
        modes.append(mode["value"])
        rect["value"] = after
        return 7

    mode = {"value": 0}
    monkeypatch.setattr(gesture, "set_gesture", lambda hwnd, value: mode.update(value=value))
    monkeypatch.setattr(gesture, "cursor_position", lambda: (-100, 120))
    monkeypatch.setattr(viewport, "window_rect", lambda hwnd: rect["value"])
    user32 = SimpleNamespace(SetWindowLongPtrW=Mock(return_value=123),
        CallWindowProcW=Mock(side_effect=native_loop))
    monkeypatch.setattr(viewport.ctypes, "windll", SimpleNamespace(user32=user32))
    native = viewport.NativeViewport(200, True)
    native.install_close_handler(view, Mock(), dock_callback=callback)
    return native, pending, callback, modes, mode


def test_title_double_click_intercepts_native_maximize_and_queues_toggle(monkeypatch):
    native, pending, callback, modes, mode = install_hook(monkeypatch, (0, 0, 200, 100), (0, 0, 200, 100))
    assert native._procedure(200, 0x00a3, 2, 0) == 0
    assert not modes
    callback.assert_not_called()
    cb, args = pending.pop()
    cb(*args)
    callback.assert_called_once_with("toggle", None)


def test_move_drop_queues_captured_cursor_after_native_loop_and_clears_property(monkeypatch):
    native, pending, callback, modes, mode = install_hook(monkeypatch, (0, 0, 200, 100), (-100, 50, 100, 150))
    assert native._procedure(200, 0x0112, 0xf012, 0) == 7
    assert modes == [1] and mode["value"] == 0
    cb, args = pending.pop()
    cb(*args)
    callback.assert_called_once_with("drop", (-100, 120))


def test_cancelled_move_and_resize_do_not_queue_a_drop(monkeypatch):
    native, pending, callback, modes, mode = install_hook(monkeypatch, (0, 0, 200, 100), (0, 0, 200, 100))
    native._procedure(200, 0x0112, 0xf012, 0)
    assert not pending
    native._procedure(200, 0x0112, 0xf004, 0)
    assert modes == [1, 2] and mode["value"] == 0
    assert not pending


def test_keyboard_system_move_does_not_use_cursor_as_drop_target(monkeypatch):
    native, pending, callback, modes, mode = install_hook(monkeypatch, (0, 0, 200, 100), (100, 0, 300, 100))
    native._procedure(200, 0x0112, 0xf010, 0)
    assert modes == [2] and not pending


def test_tearoff_position_preserves_negative_screen_coordinates_and_anchor(monkeypatch):
    user32 = SimpleNamespace(SetWindowPos=Mock(return_value=True))
    monkeypatch.setattr(viewport.ctypes, "windll", SimpleNamespace(user32=user32))
    monkeypatch.setattr(gesture, "cursor_position", lambda: (-1200, 100))
    monkeypatch.setattr(viewport, "window_rect", lambda hwnd: (0, 0, 760, 440))
    native = viewport.NativeViewport(200, True)
    assert native.position_for_tearoff((80, 10))
    user32.SetWindowPos.assert_called_once_with(200, None, -1280, 90, 0, 0, 0x15)


def test_transfer_does_not_start_native_move_after_physical_release(monkeypatch):
    user32 = SimpleNamespace(GetAsyncKeyState=Mock(return_value=0), PostMessageW=Mock())
    monkeypatch.setattr(viewport.ctypes, "windll", SimpleNamespace(user32=user32))
    native = viewport.NativeViewport(200, True)
    native.visible = True
    native.is_foreground = lambda: True
    assert not native.begin_dock_move()
    user32.PostMessageW.assert_not_called()
