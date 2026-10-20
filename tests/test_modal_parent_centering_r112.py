"""Parent-relative centering with Qt-style modal ownership and no GUI renderer."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from types import SimpleNamespace
from unittest.mock import Mock, patch

from DearUIQt.core import QObject
from DearUIQt.dialogs.placement import centered_over
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.backends.native_windows import NativeWindowBackend


def _dialog(*, parent=None, native=False, modal=True):
    dialog = QtDialog.__new__(QtDialog)
    QObject.__init__(dialog)
    dialog._requested_parent = parent
    dialog.view = SimpleNamespace(primary_window_tag="winux_primary", is_standalone_ui_host=False)
    dialog.tag = "dialog"
    dialog.width, dialog.height = 300, 180
    dialog.modal = modal
    dialog._native_window_backend = object() if native else None
    dialog._closed = False
    return dialog


class _FakeRenderer:
    def __init__(self):
        self.shown = {"main", "winux_primary", "first", "dialog"}
        self.geometry = {
            "main": ((60, 90), (900, 700)),
            "winux_primary": ((20, 30), (1000, 800)),
            "first": ((180, 230), (460, 320)),
        }
        self.positioned = []

    def does_item_exist(self, tag):
        return tag in self.shown

    def is_item_shown(self, tag):
        return tag in self.shown

    def get_item_rect_min(self, tag):
        return self.geometry[tag][0]

    def get_item_rect_size(self, tag):
        return self.geometry[tag][1]

    def get_viewport_client_width(self):
        return 1200

    def get_viewport_client_height(self):
        return 900

    def set_item_pos(self, tag, position):
        self.positioned.append((tag, position))


def test_basic_parent_geometry_is_centered_exactly():
    assert centered_over((100, 120, 800, 600), (320, 180)) == (340, 330)


def test_embedded_dialog_is_clamped_inside_viewport_not_centered_on_screen():
    assert centered_over((900, 600, 200, 100), (400, 300), (0, 0, 1000, 700)) == (600, 400)


def test_child_larger_than_viewport_does_not_get_negative_coordinates():
    assert centered_over((0, 0, 100, 80), (1500, 1200), (0, 0, 800, 600)) == (0, 0)


def test_explicit_parent_widget_wins_over_main_window():
    dialog = _dialog(parent=SimpleNamespace(tag="first"))
    renderer = _FakeRenderer()
    with patch("DearUIQt.dialogs.qt_dialog.dpg", renderer):
        assert dialog.center() == (260, 300)
    assert renderer.positioned == [("dialog", (260, 300))]


def test_no_dialog_parent_uses_primary_window_not_viewport_center():
    dialog = _dialog()
    renderer = _FakeRenderer()
    with patch("DearUIQt.dialogs.qt_dialog.dpg", renderer):
        assert dialog.center() == (370, 340)
    assert renderer.positioned[-1] == ("dialog", (370, 340))


def test_invisible_explicit_parent_falls_back_to_main_window():
    dialog = _dialog(parent=SimpleNamespace(tag="missing"))
    renderer = _FakeRenderer()
    with patch("DearUIQt.dialogs.qt_dialog.dpg", renderer):
        assert dialog.center() == (370, 340)


def test_nested_modal_centers_on_active_dialog():
    dialog = _dialog()
    active = SimpleNamespace(tag="first", _closed=False, isVisible=lambda: True)
    renderer = _FakeRenderer()
    with patch("DearUIQt.dialogs.qt_dialog.dpg", renderer), patch(
        "DearUIQt.core.application.QApplication.instance", return_value=SimpleNamespace(
            activeModalWidget=lambda: active, activeWindow=lambda: active
        )
    ):
        assert dialog.center() == (260, 300)


def test_native_windows_use_parent_frame_coordinates_without_viewport_clamp():
    dialog = _dialog(parent=SimpleNamespace(tag="first"), native=True)
    renderer = _FakeRenderer()
    renderer.geometry["first"] = ((1500, 550), (460, 320))
    with patch("DearUIQt.dialogs.qt_dialog.dpg", renderer):
        assert dialog.center() == (1580, 620)


def test_native_window_frame_center_does_not_activate_owner_or_change_z_order():
    backend = NativeWindowBackend(backend=SimpleNamespace(internal_dpg=object()))
    backend.isEnabled = Mock(return_value=True)
    backend.winId = Mock(return_value=202)
    backend._owner_from_child = Mock(return_value=101)
    user = SimpleNamespace()
    user.IsWindow = Mock(return_value=True)

    def rect(hwnd, pointer):
        handle = int(getattr(hwnd, 'value', hwnd))
        region = (100, 200, 800, 600) if handle == 101 else (0, 0, 400, 240)
        r = ctypes.cast(pointer, ctypes.POINTER(wintypes.RECT)).contents
        r.left, r.top, r.right, r.bottom = region
        return True

    user.GetWindowRect = Mock(side_effect=rect)
    user.SetWindowPos = Mock(return_value=True)
    with patch("DearUIQt.backends.native_windows._windows_user32", return_value=user):
        assert backend.centerOverOwner(202) is True
    args = user.SetWindowPos.call_args.args
    assert (args[2], args[3]) == (250, 280)
    assert args[-1] == 0x0015  # no resize, reorder, or activate


def test_native_center_defers_until_hwnd_exists():
    backend = NativeWindowBackend(backend=SimpleNamespace(internal_dpg=object()))
    backend.isEnabled = Mock(return_value=True)
    backend.winId = Mock(return_value=0)
    with patch("DearUIQt.backends.native_windows._windows_user32", return_value=object()):
        assert backend.centerOverOwner('dialog') is False


def test_hidden_modal_from_app_stack_uses_next_visible_launcher():
    dialog = _dialog()
    hidden = SimpleNamespace(tag="first", _closed=False, isVisible=lambda: False)
    launcher = SimpleNamespace(tag="main", _closed=False, isVisible=lambda: True)
    renderer = _FakeRenderer()
    with patch("DearUIQt.dialogs.qt_dialog.dpg", renderer), patch(
        "DearUIQt.core.application.QApplication.instance", return_value=SimpleNamespace(
            activeModalWidget=lambda: hidden, activeWindow=lambda: launcher
        )
    ):
        assert dialog.center() == (360, 350)


def test_native_center_retries_only_until_owner_hwnd_is_available():
    dialog = _dialog(native=True)
    dialog._visible_state = True
    backend = SimpleNamespace(centerOverOwner=Mock(side_effect=[False, False, True]))
    dialog._native_window_backend = backend
    renderer = _FakeRenderer()
    callbacks = []
    dialog.view.after_render = lambda callback, *args: callbacks.append((callback, args))
    with patch("DearUIQt.dialogs.qt_dialog.dpg", renderer), patch(
        "DearUIQt.dialogs.base.dpg", renderer
    ):
        dialog._schedule_native_modal_center()
        while callbacks:
            callback, args = callbacks.pop(0)
            callback(*args)
    assert backend.centerOverOwner.call_count == 3


def test_closed_dialog_never_moves_native_window():
    dialog = _dialog(native=True)
    dialog._closed = True
    backend = SimpleNamespace(centerOverOwner=Mock(return_value=True))
    dialog._native_window_backend = backend
    renderer = _FakeRenderer()
    with patch("DearUIQt.dialogs.qt_dialog.dpg", renderer), patch(
        "DearUIQt.dialogs.base.dpg", renderer
    ):
        dialog._center_native_modal_once(2)
    backend.centerOverOwner.assert_not_called()
