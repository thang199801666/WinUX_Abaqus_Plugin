from types import SimpleNamespace
from unittest.mock import Mock, patch

from DearUIQt.backends.native_windows import NativeWindowBackend
from DearUIQt.dialogs.qt_dialog import QtDialog


class _User32:
    def __init__(self, foreground=5678):
        self.foreground = foreground
        self.IsWindow = Mock(return_value=True)
        self.IsWindowVisible = Mock(return_value=True)
        self.GetForegroundWindow = Mock(side_effect=lambda: self.foreground)
        self.BringWindowToTop = Mock(return_value=True)
        self.SetForegroundWindow = Mock(side_effect=self._set_foreground)
        self.SetActiveWindow = Mock(return_value=0)
        self.SetFocus = Mock(return_value=0)

    def _set_foreground(self, hwnd):
        self.foreground = int(getattr(hwnd, 'value', hwnd) or 0)
        return True


def _backend(child=1234, owner=5678):
    extension = SimpleNamespace(
        dearuiqt_enable_native_windows=Mock(return_value=True),
        dearuiqt_native_windows_enabled=Mock(return_value=True),
        dearuiqt_configure_native_window=Mock(),
        dearuiqt_native_window_handle=Mock(return_value=child),
    )
    backend = NativeWindowBackend(SimpleNamespace(internal_dpg=extension))
    backend.configure(12, owner=None, modal=True, owner_hwnd=owner)
    return backend, extension


def test_owned_dialog_is_activated_before_first_user_click_when_owner_is_foreground():
    backend, _ = _backend()
    user32 = _User32(foreground=5678)
    with patch('DearUIQt.backends.native_windows._windows_user32', return_value=user32):
        assert backend.activateOwnedWindow(12) is True
    user32.BringWindowToTop.assert_called_once()
    user32.SetForegroundWindow.assert_called_once()
    user32.SetActiveWindow.assert_called_once()
    user32.SetFocus.assert_called_once()
    assert user32.foreground == 1234


def test_native_dialog_activation_never_steals_foreground_from_another_application():
    backend, _ = _backend()
    user32 = _User32(foreground=9999)
    with patch('DearUIQt.backends.native_windows._windows_user32', return_value=user32):
        assert backend.activateOwnedWindow(12) is False
    user32.BringWindowToTop.assert_not_called()
    user32.SetForegroundWindow.assert_not_called()
    user32.SetActiveWindow.assert_not_called()
    user32.SetFocus.assert_not_called()


def test_missing_native_hwnd_reports_not_ready_so_dialog_can_retry_after_render():
    backend, extension = _backend(child=0)
    with patch('DearUIQt.backends.native_windows._windows_user32', return_value=_User32()):
        assert backend.activateOwnedWindow(12) is None
    extension.dearuiqt_native_window_handle.assert_called()


def test_qdialog_retries_activation_only_while_native_hwnd_is_not_ready():
    scheduled = []
    native = SimpleNamespace(
        synchronizeOwner=Mock(return_value=True),
        activateOwnedWindow=Mock(side_effect=[None, True]),
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
    assert dialog._activate_native_modal_once(2) is None
    assert len(scheduled) == 1
    callback, args = scheduled.pop()
    assert callback(*args) is True
    assert native.activateOwnedWindow.call_count == 2


def test_qdialog_does_not_retry_when_foreground_belongs_to_another_app():
    scheduled = []
    native = SimpleNamespace(
        synchronizeOwner=Mock(return_value=True),
        activateOwnedWindow=Mock(return_value=False),
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
    assert dialog._activate_native_modal_once(2) is False
    assert scheduled == []
