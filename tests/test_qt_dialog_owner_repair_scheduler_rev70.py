"""QDialog close focus repair is renderer-frame based, not callback-order based."""
from types import SimpleNamespace
from unittest.mock import Mock

from DearUIQt.dialogs.qt_dialog import QtDialog


def _dialog(backend):
    dialog = object.__new__(QtDialog)
    dialog._native_window_backend = backend
    dialog._native_owner_repair_generation = 0
    dialog._native_owner_close_lease = None
    dialog._restore_focus_on_hide = False
    dialog.tag = 42
    callbacks = []
    dialog.view = SimpleNamespace(
        after_render=lambda callback, *args: callbacks.append((callback, args)),
        after=lambda _delay, callback, *args: callbacks.append((callback, args)),
    )
    return dialog, callbacks


def test_hwnd_foreground_lease_is_authoritative_even_when_dpg_focus_was_stale():
    lease = SimpleNamespace(return_foreground=True)
    backend = SimpleNamespace(beginOwnerClose=Mock(return_value=lease))
    dialog, _callbacks = _dialog(backend)

    assert dialog._begin_native_owner_close() is lease
    assert dialog._restore_focus_on_hide is True
    assert dialog._native_owner_close_lease is lease


def test_owner_repair_waits_for_render_and_retries_only_while_native_teardown_pending():
    lease = object()
    backend = SimpleNamespace(repairOwnerAfterHide=Mock(side_effect=[None, True]))
    dialog, callbacks = _dialog(backend)

    assert dialog._schedule_native_owner_repair(lease)
    assert len(callbacks) == 1
    first, args = callbacks.pop(0)
    first(*args)
    assert len(callbacks) == 1
    second, args = callbacks.pop(0)
    second(*args)
    assert backend.repairOwnerAfterHide.call_count == 2
    assert dialog._native_owner_close_lease is None


def test_reshow_generation_invalidates_stale_post_close_repair():
    lease = object()
    backend = SimpleNamespace(repairOwnerAfterHide=Mock(return_value=True))
    dialog, callbacks = _dialog(backend)

    dialog._schedule_native_owner_repair(lease)
    dialog._cancel_native_owner_repair()
    callback, args = callbacks.pop(0)
    callback(*args)
    backend.repairOwnerAfterHide.assert_not_called()
