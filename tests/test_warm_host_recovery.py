"""A replacement transport must replay init and ignore retired-host callbacks."""
import socket
import threading
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from WinUx.ui.hosting.floating_dialog import FloatingDialogController
from WinUx.runtime.command_queue import LatestCommandQueue


class WarmHostRecoveryTests(unittest.TestCase):
    def test_cold_and_warm_contexts_dispatch_callbacks_on_gui_thread(self):
        source = Path(__file__).resolve().parents[1] / "WinUx/ui/hosting/floating_runtime.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == "createContext"]
        self.assertEqual(len(calls), 2)
        for call in calls:
            value = next(item.value for item in call.keywords if item.arg == "manual_callbacks")
            self.assertIsInstance(value, ast.Constant)
            self.assertIs(value.value, True)

    def controller(self):
        dialog = object.__new__(FloatingDialogController)
        dialog._closed = dialog._ready = False
        dialog._from_prewarm = True
        dialog._ipc_retry_count = dialog._transport_generation = 0
        dialog._startup_generation = 1
        dialog._hwnd = None
        dialog._owner_acquired = False
        dialog._native_prepared = False
        dialog._kind = "reference_chart"
        dialog.title = "Reference Chart"
        dialog._ipc_stage = "connected to dialog host"
        dialog._lease = "old"
        dialog._initial_message = {
            "command": "init", "kind": "reference_chart", "lease": "old",
            "authorized_hwnd": 123, "reuse_host": True,
            "payload": {"entries": []}}
        # The old writer has already sent/removed init; rebinding pending
        # commands alone cannot start a replacement process.
        dialog._outgoing = LatestCommandQueue(maxsize=256)
        dialog._outgoing.put_nowait({"command": "activate", "lease": "old"})
        dialog._connection_ready = threading.Event()
        dialog._connection_ready.set()
        dialog._host_lease = Mock()
        dialog._host_manager = Mock()
        dialog._host_manager.acquire.return_value = SimpleNamespace(
            host=Mock(), reused=False, lease="new", reusable=True,
            listener=Mock(), token="new-token", process=Mock(), log_path="unused.log")
        dialog.view = SimpleNamespace(after=Mock())
        dialog._append_failure_log = Mock()
        return dialog

    def test_timeout_replays_consumed_init_before_pending_commands(self):
        dialog = self.controller()
        old = dialog._host_lease
        with patch("WinUx.ui.hosting.floating_dialog._DIALOG_IPC_POOL.start") as start:
            self.assertTrue(dialog._retry_startup_with_fresh_host(socket.timeout()))
        old.close_channel.assert_called_once_with()
        old.retire.assert_called_once_with()
        initial = dialog._outgoing.get_nowait()
        self.assertEqual(initial["command"], "init")
        self.assertEqual(initial["lease"], "new")
        self.assertIsNone(initial["authorized_hwnd"])
        self.assertEqual(initial["payload"], {"entries": []})
        self.assertEqual(dialog._outgoing.get_nowait(), {"command": "activate", "lease": "new"})
        start.assert_called_once_with(dialog._write_commands, 1)
        self.assertFalse(dialog._connection_ready.is_set())
        self.assertFalse(dialog._retry_startup_with_fresh_host(socket.timeout()))

    def test_retired_writer_cannot_fail_replacement_dialog(self):
        dialog = self.controller()
        dialog._transport_generation = 1
        dialog._failed = Mock()
        dialog._command_failed(0, "old socket closed")
        dialog._failed.assert_not_called()
        dialog._command_failed(1, "current socket closed")
        dialog._failed.assert_called_once()

    def test_native_disconnect_before_ready_can_replace_a_cold_host_once(self):
        dialog = self.controller()
        dialog._from_prewarm = False
        with patch("WinUx.ui.hosting.floating_dialog._DIALOG_IPC_POOL.start"):
            self.assertTrue(dialog._retry_startup_with_fresh_host(ConnectionResetError()))
            self.assertFalse(dialog._retry_startup_with_fresh_host(ConnectionResetError()))
        self.assertEqual(dialog._outgoing.get_nowait()["command"], "init")

    def test_retired_lease_events_are_ignored_on_ui_delivery(self):
        dialog = self.controller()
        dialog._lease = "new"
        dialog._failed = Mock()
        dialog._deliver_event({"event": "error", "lease": "old", "message": "old failure"})
        dialog._failed.assert_not_called()
        dialog._deliver_event({"event": "ready", "lease": "old"})
        self.assertFalse(dialog._ready)


if __name__ == "__main__":
    unittest.main()
