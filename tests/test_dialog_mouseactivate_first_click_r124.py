from types import SimpleNamespace
from unittest.mock import Mock, patch

from DearUIQt.backends.native_windows import NativeWindowBackend
from DearUIQt.dialogs.qt_dialog import QtDialog


class _User32:
    def __init__(self):
        self.GetWindowLongPtrW = Mock(return_value=0x123456)
        self.SetWindowLongPtrW = Mock(return_value=0x123456)
        self.CallWindowProcW = Mock(return_value=77)


def _backend(child=1234):
    extension = SimpleNamespace(
        dearuiqt_enable_native_windows=Mock(return_value=True),
        dearuiqt_native_windows_enabled=Mock(return_value=True),
        dearuiqt_configure_native_window=Mock(),
        dearuiqt_native_window_handle=Mock(return_value=child),
    )
    return NativeWindowBackend(SimpleNamespace(internal_dpg=extension))


def test_mouseactivate_hook_returns_ma_activate_and_preserves_client_click():
    backend = _backend()
    user32 = _User32()
    with patch('DearUIQt.backends.native_windows._windows_user32', return_value=user32):
        assert backend.preserveFirstClientClick(12) is True
    assert 1234 in backend._mouse_activate_hooks
    callback, old_proc = backend._mouse_activate_hooks[1234]
    assert old_proc == 0x123456
    # WM_MOUSEACTIVATE must activate without eating the following click.
    assert callback(1234, 0x0021, 0, 0) == 1
    # All unrelated messages continue to the original GLFW/ImGui WNDPROC.
    assert callback(1234, 0x0200, 0, 0) == 77
    user32.CallWindowProcW.assert_called_once()


def test_mouseactivate_hook_is_installed_only_once_per_hwnd():
    backend = _backend()
    user32 = _User32()
    with patch('DearUIQt.backends.native_windows._windows_user32', return_value=user32):
        assert backend.preserveFirstClientClick(12) is True
        assert backend.preserveFirstClientClick(12) is True
    user32.SetWindowLongPtrW.assert_called_once()


def test_qdialog_installs_first_click_hook_before_native_activation():
    calls = []
    native = SimpleNamespace(
        synchronizeOwner=lambda tag: calls.append(('owner', tag)) or True,
        preserveFirstClientClick=lambda tag: calls.append(('mouseactivate', tag)) or True,
        activateOwnedWindow=lambda tag: calls.append(('activate', tag)) or True,
    )
    dialog = SimpleNamespace(
        modal=True,
        _native_window_backend=native,
        tag=77,
        winfo_exists=lambda: True,
        isVisible=lambda: True,
        view=SimpleNamespace(after_render=lambda *_: None),
    )
    result = QtDialog._activate_native_modal_once(dialog, 2)
    assert result is True
    assert calls == [('owner', 77), ('mouseactivate', 77), ('activate', 77)]


def test_qdialog_retries_until_mouseactivate_hook_has_native_hwnd():
    scheduled = []
    native = SimpleNamespace(
        synchronizeOwner=Mock(return_value=True),
        preserveFirstClientClick=Mock(side_effect=[None, True]),
        activateOwnedWindow=Mock(return_value=True),
    )
    dialog = SimpleNamespace(
        modal=True,
        _native_window_backend=native,
        tag=77,
        winfo_exists=lambda: True,
        isVisible=lambda: True,
        view=SimpleNamespace(after_render=lambda callback, *args: scheduled.append((callback, args))),
    )
    dialog._activate_native_modal_once = lambda remaining=2: QtDialog._activate_native_modal_once(dialog, remaining)
    assert dialog._activate_native_modal_once(2) is True
    assert len(scheduled) == 1
    callback, args = scheduled.pop()
    assert callback(*args) is True
    assert native.preserveFirstClientClick.call_count == 2


def test_modeless_native_dialog_also_prepares_first_click_without_forcing_activation():
    scheduled = []
    native = SimpleNamespace(preserveFirstClientClick=Mock(return_value=True))
    dialog = SimpleNamespace(
        modal=False,
        _native_window_backend=native,
        tag=88,
        winfo_exists=lambda: True,
        isVisible=lambda: True,
        view=SimpleNamespace(after_render=lambda callback, *args: scheduled.append((callback, args))),
    )
    dialog._prepare_native_first_click_once = lambda remaining=2: QtDialog._prepare_native_first_click_once(dialog, remaining)
    assert dialog._prepare_native_first_click_once(2) is True
    native.preserveFirstClientClick.assert_called_once_with(88)
    assert scheduled == []


def test_native_first_client_release_notifies_recovery_once():
    backend = _backend()
    user32 = _User32()
    recovery = Mock()
    with patch('DearUIQt.backends.native_windows._windows_user32', return_value=user32):
        assert backend.preserveFirstClientClick(12, recovery) is True
    callback, _old_proc = backend._mouse_activate_hooks[1234]
    lparam = (40 << 16) | 30
    assert callback(1234, 0x0202, 0, lparam) == 77  # WM_LBUTTONUP
    recovery.assert_called_once_with((30.0, 40.0))
    callback(1234, 0x0202, 0, lparam)
    recovery.assert_called_once()


def test_lost_first_native_button_click_is_recovered_once_without_double_activation():
    class FakeButton:
        _deleted = False
        tag = 5
        def __init__(self):
            self.calls = 0
        def click(self):
            self.calls += 1
            return True

    button = FakeButton()
    dialog = SimpleNamespace(
        _button_activation_serial=0,
        _control_wrappers={5: button},
        winfo_exists=lambda: True,
        isVisible=lambda: True,
        _button_contains_global_point=lambda candidate, point: candidate is button and point == (100.0, 200.0),
        _initial_pointer_activity=False,
    )
    with patch('DearUIQt.dialogs.qt_dialog.QPushButton', FakeButton):
        assert QtDialog._recover_native_first_button_click(dialog, (100.0, 200.0), 0) is True
        assert button.calls == 1
        # Normal delivery already happened: the fallback must not duplicate it.
        dialog._button_activation_serial = 1
        assert QtDialog._recover_native_first_button_click(dialog, (100.0, 200.0), 0) is False
        assert button.calls == 1
