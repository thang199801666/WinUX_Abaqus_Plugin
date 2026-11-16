from __future__ import annotations

import inspect
import queue
import threading
from types import SimpleNamespace

from WinUx.ui.hosting.floating_runtime import FloatingDialogRuntime


class _Form:
    def __init__(self):
        self.alive = True
    def winfo_exists(self):
        return self.alive


class _View:
    def __init__(self):
        self.callbacks = []
        self._dispatcher = SimpleNamespace(closed=False)
    def eventDispatcher(self):
        return self._dispatcher
    def after(self, delay, callback, *args):
        self.callbacks.append((delay, callback, args))
        return None


def _runtime():
    runtime = FloatingDialogRuntime.__new__(FloatingDialogRuntime)
    runtime.incoming = queue.Queue()
    runtime.view = _View()
    runtime.form = _Form()
    runtime._event_loop = None
    runtime._command_drain_lock = threading.Lock()
    runtime._command_drain_scheduled = False
    runtime._drain_commands = lambda: None
    return runtime


def test_ipc_wake_is_coalesced_onto_ui_dispatcher():
    runtime = _runtime()
    runtime._schedule_command_drain()
    runtime._schedule_command_drain()
    assert len(runtime.view.callbacks) == 1
    assert runtime._command_drain_scheduled is True

    _delay, callback, args = runtime.view.callbacks.pop()
    callback(*args)
    assert runtime._command_drain_scheduled is False


def test_remaining_ipc_work_reposts_after_bounded_drain():
    runtime = _runtime()
    calls = []
    runtime.incoming.put({"command": "one"})
    runtime._drain_commands = lambda: calls.append("drain")

    runtime._schedule_command_drain()
    _delay, callback, args = runtime.view.callbacks.pop()
    callback(*args)

    assert calls == ["drain"]
    # The fake drain intentionally leaves the queue populated, so the runtime
    # must schedule another UI-event turn rather than spin in the current one.
    assert len(runtime.view.callbacks) == 1
    assert runtime._command_drain_scheduled is True


def test_host_turn_does_not_poll_ipc_queue_directly():
    source = inspect.getsource(FloatingDialogRuntime._application_host_turn)
    assert "_drain_commands" not in source
    assert "incoming.empty" not in source
