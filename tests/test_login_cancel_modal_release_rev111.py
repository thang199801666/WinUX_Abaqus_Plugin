"""Regression: cancelling a native Login QDialog must not freeze WinUx input."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from DearUIQt.backends.native_windows import NativeWindowBackend
from DearUIQt.qt import QApplication, QEvent, QInputTarget, QMouseEvent, Qt


ROOT = Path(__file__).resolve().parents[1]
DIALOG_SOURCE = (ROOT / "DearUIQt/dialogs/qt_dialog.py").read_text(encoding="utf-8")


class FakeUser32:
    def __init__(self):
        self.enabled = False
        self.GetWindow = Mock(return_value=5678)
        self.IsWindow = Mock(return_value=True)
        self.IsWindowEnabled = Mock(side_effect=lambda _hwnd: self.enabled)
        self.EnableWindow = Mock(side_effect=self._enable)

    def _enable(self, _hwnd, value):
        self.enabled = bool(value)
        return True


def _backend():
    extension = SimpleNamespace(
        dearuiqt_enable_native_windows=Mock(return_value=True),
        dearuiqt_native_windows_enabled=Mock(return_value=True),
        dearuiqt_configure_native_window=Mock(),
        dearuiqt_native_window_handle=Mock(return_value=1234),
    )
    backend = NativeWindowBackend(SimpleNamespace(internal_dpg=extension))
    backend.configure(SimpleNamespace(tag=12), owner=SimpleNamespace(tag=13), modal=True)
    return backend, extension


def test_native_modal_is_disarmed_and_owner_reenabled_before_hide():
    import DearUIQt.backends.native_windows as native_windows

    backend, extension = _backend()
    user32 = FakeUser32()
    with patch.object(native_windows, "_windows_user32", return_value=user32):
        assert backend.disarmModalBeforeHide(12, enable_owner=True)

    assert extension.dearuiqt_configure_native_window.call_args_list[-1].args == (12, 13, False)
    assert user32.enabled is True
    user32.EnableWindow.assert_called_once()


def test_sibling_modal_can_keep_owner_disabled_while_current_dialog_disarms():
    import DearUIQt.backends.native_windows as native_windows

    backend, extension = _backend()
    user32 = FakeUser32()
    with patch.object(native_windows, "_windows_user32", return_value=user32):
        assert backend.disarmModalBeforeHide(12, enable_owner=False)

    assert extension.dearuiqt_configure_native_window.call_args_list[-1].args == (12, 13, False)
    user32.EnableWindow.assert_not_called()
    assert user32.enabled is False


def test_removing_dialog_subtree_clears_implicit_mouse_grab_bits():
    app = QApplication(after=lambda *_args: None)
    target = QInputTarget(
        parent=app,
        hit_test=lambda _pos: True,
        pointer_handler=lambda _event: True,
    )
    try:
        press = QMouseEvent(
            QEvent.MouseButtonPress, (10, 10), button=Qt.LeftButton,
            buttons=Qt.LeftButton,
        )
        assert app.dispatchPointerEvent(press)
        assert app.mouseGrabberObject() is target
        assert app._implicit_grab_buttons & Qt.LeftButton

        # Cancel/delete can happen before a native multi-viewport release event
        # reaches the application's main pointer bridge.
        app._clear_widget(target)
        assert app.mouseGrabberObject() is None
        assert app._implicit_grab_buttons == Qt.NoButton
    finally:
        target.delete()
        app.delete()


def test_qdialog_close_disarms_native_modal_before_visual_destroy():
    destroy = DIALOG_SOURCE.split("    def destroy(self):", 1)[1].split(
        "\n\nQDialog = QtDialog", 1)[0]
    assert "unregister_modal_window(self.tag)" in destroy
    assert "self._disarm_native_modal_before_hide()" in destroy
    assert destroy.index("self._disarm_native_modal_before_hide()") < destroy.index("super().destroy()")

    hide = DIALOG_SOURCE.split("    def hide(self):", 1)[1].split(
        "    def event(self, event):", 1)[0]
    assert "application._unregister_modal(self)" in hide
    assert "self._disarm_native_modal_before_hide()" in hide
    assert hide.index("application._unregister_modal(self)") < hide.index(
        "self._disarm_native_modal_before_hide()")
