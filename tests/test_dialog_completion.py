"""QDialog-like completion is queued and ordered after reusable-host cleanup."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from WinUx.dialogs.floating_adapters import ResultDialog


def dialog_fixture(*, reusable=False, notify_cancel=True):
    jobs, events = [], []
    dialog = object.__new__(ResultDialog)
    dialog._init_result(lambda value: events.append(("payload", value)), notify_cancel=notify_cancel)
    dialog.view = SimpleNamespace(after=lambda delay, callback, *args: jobs.append((delay, callback, args)))
    dialog._reuse_host = reusable
    dialog._host_returned = False
    dialog._closed = dialog._finalized = False
    dialog._lease = "current"
    dialog._prepared_worker = object()
    dialog._recycle_timer = Mock()
    dialog._prewarm_pool = SimpleNamespace(release=Mock())
    dialog.accepted.connect(lambda: events.append(("accepted",)))
    dialog.rejected.connect(lambda: events.append(("rejected",)))
    dialog.finished.connect(lambda code: events.append(("finished", code)))

    def destroy():
        dialog._closed = dialog._finalized = True
        if not reusable:
            dialog._close_completed()

    dialog.destroy = destroy

    def pump():
        while jobs:
            _delay, callback, args = jobs.pop(0)
            callback(*args)

    return dialog, jobs, events, pump


@pytest.mark.parametrize("value,code", [(True, 1), ("", 1), (0, 1), (False, 0), (None, 0)])
def test_completion_signals_are_queued_exactly_once(value, code):
    dialog, jobs, events, pump = dialog_fixture()
    dialog.finish(value)
    assert dialog._closed and not events
    assert all(delay == 0 for delay, _, _ in jobs)
    dialog._close_completed()
    dialog.finish("late")
    pump()
    assert events == [("accepted" if code else "rejected",), ("finished", code), ("payload", value)]


def test_reusable_completion_waits_until_host_is_available():
    dialog, jobs, events, pump = dialog_fixture(reusable=True)
    dialog.done(dialog.Accepted, "chosen.png")
    assert dialog._closed and not jobs and not events
    ready = []
    dialog._prewarm_pool.release.side_effect = lambda *args: ready.append(True)
    dialog.finished.connect(lambda code: ready.append("finished-after-release" if ready else "too-early"))
    dialog._return_host({"item_count": 12})
    assert ready == [True] and not events
    pump()
    assert ready == [True, "finished-after-release"]
    assert events[-1] == ("payload", "chosen.png")
    dialog._return_host({"item_count": 12})
    pump()
    assert len(events) == 3


def test_explicit_result_code_is_independent_of_payload():
    dialog, _, events, pump = dialog_fixture()
    dialog.done(dialog.Accepted, False)
    pump()
    assert events == [("accepted",), ("finished", 1), ("payload", False)]


def test_cancel_signal_is_not_suppressed_by_legacy_callback_policy():
    dialog, _, events, pump = dialog_fixture(notify_cancel=False)
    dialog.reject()
    pump()
    assert events == [("rejected",), ("finished", 0)]


@pytest.mark.parametrize("code", [None, True, False, -1, 2, 1.0, "1"])
def test_invalid_close_codes_do_not_change_dialog_state(code):
    dialog, jobs, events, _ = dialog_fixture()
    with pytest.raises(ValueError):
        dialog.done(code)
    assert not dialog._closed and not dialog.result["done"] and not jobs and not events


def test_deleted_qobject_receiver_does_not_receive_queued_completion():
    from DearUIQt.qt.core import QObject
    dialog, _, _, pump = dialog_fixture()
    receiver = QObject(after=dialog.view.after)
    slot = Mock()
    dialog.finished.connect(slot, receiver=receiver, queued=True)
    dialog.finish(True)
    receiver.delete()
    pump()
    slot.assert_not_called()


@pytest.mark.parametrize("fallback", ["exit", "timeout"])
def test_missing_idle_ack_still_completes_once_on_the_ui_queue(fallback):
    dialog, jobs, events, pump = dialog_fixture(reusable=True)
    dialog._prewarm_pool.retire = Mock()
    dialog.done(dialog.Accepted, "result")
    assert not events
    if fallback == "exit":
        dialog._process_exited()
    else:
        dialog._retire_unreturned_host()
    assert jobs and not events
    pump()
    dialog._close_completed()
    pump()
    assert events == [("accepted",), ("finished", 1), ("payload", "result")]


def test_programmatic_accept_uses_client_validation_instead_of_fabricating_result():
    dialog, jobs, events, _ = dialog_fixture()
    dialog.post = Mock(return_value=True)
    assert dialog.accept()
    dialog.post.assert_called_once_with("dialog_accept")
    assert not dialog.result["done"] and not jobs and not events


def test_accept_command_routes_to_form_acceptance_action():
    from WinUx.dialogs.floating_forms import deliver_command
    form = SimpleNamespace(accept=Mock(), handle_command=Mock())
    deliver_command(form, "dialog_accept", [])
    form.accept.assert_called_once()
    form.handle_command.assert_not_called()


@pytest.mark.parametrize("enabled", [False, True])
def test_form_acceptance_uses_its_default_not_another_focused_button(enabled):
    from WinUx.dialogs.qt_dialog import QtDialog
    dialog = object.__new__(QtDialog)
    dialog._default = Mock()
    dialog._default_button = 42
    dialog._item_is_focusable = lambda item: enabled
    assert dialog.accept() is enabled
    assert dialog._default.call_count == int(enabled)
