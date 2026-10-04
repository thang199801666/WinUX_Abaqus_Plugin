"""Regression checks for non-blocking WinUX application shutdown."""

from __future__ import annotations

import ast
from pathlib import Path
import socket
import threading
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


class _FakeWorker:
    def __init__(self):
        self.join_calls = []

    def join(self, timeout=None):
        self.join_calls.append(timeout)


class LocalWatcherShutdownTests(unittest.TestCase):
    def test_shutdown_can_signal_watcher_without_joining(self):
        from WinUx.services.local_file_watcher import LocalFileSystemWatcher

        watcher = LocalFileSystemWatcher()
        worker = _FakeWorker()
        watcher._thread = worker
        watcher.stop(wait=False)
        self.assertEqual(worker.join_calls, [])
        self.assertIsNone(watcher._thread)
        self.assertTrue(watcher._stop_event.is_set())


class _FakeResource:
    def __init__(self):
        self.closed = threading.Event()

    def close(self):
        self.closed.set()


class _FakeSocket:
    def __init__(self):
        self.shutdown_calls = []
        self.closed = False

    def shutdown(self, how):
        self.shutdown_calls.append(how)

    def close(self):
        self.closed = True


class _FakeTransport:
    def __init__(self):
        self.sock = _FakeSocket()


class _FakeClient(_FakeResource):
    def __init__(self, transport):
        super().__init__()
        self.transport = transport

    def get_transport(self):
        return self.transport


class SSHShutdownTests(unittest.TestCase):
    def test_request_shutdown_detaches_and_breaks_socket_before_cleanup(self):
        from WinUx.server_model import SSHServerModel

        server = SSHServerModel()
        transport = _FakeTransport()
        shell = _FakeResource()
        sftp = _FakeResource()
        client = _FakeClient(transport)
        server.shell = shell
        server.sftp = sftp
        server.client = client
        server._password = "secret"

        # This method must not wait for any serialized wire operation. The
        # immediate observable contract is detachment + underlying socket close.
        started = time.monotonic()
        server.request_shutdown()
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.25)
        self.assertIsNone(server.shell)
        self.assertIsNone(server.sftp)
        self.assertIsNone(server.client)
        self.assertIsNone(server._password)
        self.assertEqual(transport.sock.shutdown_calls, [socket.SHUT_RDWR])
        self.assertTrue(transport.sock.closed)

        # Graceful object closes are allowed to finish asynchronously.
        self.assertTrue(shell.closed.wait(0.5))
        self.assertTrue(sftp.closed.wait(0.5))
        self.assertTrue(client.closed.wait(0.5))


class ControllerShutdownArchitectureTests(unittest.TestCase):
    @staticmethod
    def _method(class_name, method_name, file_name):
        tree = ast.parse((ROOT / file_name).read_bytes())
        cls = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == class_name
        )
        return next(
            node for node in cls.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == method_name
        )

    def test_finish_close_uses_ui_request_then_guaranteed_standalone_exit(self):
        method = self._method(
            "WinUXController", "_finish_close", "WinUx/controller.py")

        calls = []
        for node in ast.walk(method):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute):
                calls.append((func.attr, node.lineno, func))

        self.assertFalse(any(
            name == "close"
            and isinstance(func.value, ast.Attribute)
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id == "self"
            and func.value.attr == "server"
            for name, _line, func in calls
        ))

        request_ui_line = next(
            line for name, line, func in calls
            if name == "request_shutdown"
            and isinstance(func.value, ast.Attribute)
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id == "self"
            and func.value.attr == "view"
        )
        request_server_line = next(
            line for name, line, func in calls
            if name == "request_shutdown"
            and isinstance(func.value, ast.Attribute)
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id == "self"
            and func.value.attr == "server"
        )
        hide_children_line = next(
            node.lineno for node in ast.walk(method)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "hide_registered_process_windows"
        )
        terminate_children_line = next(
            node.lineno for node in ast.walk(method)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "terminate_registered_children"
        )
        hard_exit_line = next(
            line for name, line, func in calls
            if name == "_exit"
            and isinstance(func.value, ast.Name)
            and func.value.id == "os"
        )
        self.assertLess(request_ui_line, hide_children_line)
        self.assertLess(hide_children_line, request_server_line)
        self.assertLess(request_server_line, terminate_children_line)
        self.assertLess(terminate_children_line, hard_exit_line)

    def test_view_request_shutdown_does_not_stop_or_destroy_dpg_context(self):
        method = self._method(
            "WinUXView", "request_shutdown", "WinUx/view.py")
        names = [
            node.func.attr
            for node in ast.walk(method)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        ]
        self.assertNotIn("stop_dearpygui", names)
        self.assertNotIn("destroy_context", names)

    def test_standalone_finish_close_reaches_hard_exit_without_waiting(self):
        from WinUx.controller import WinUXController

        class FakeView:
            transfer_center_dialog = None

            def __init__(self):
                self.shutdown_requested = False

            def request_shutdown(self):
                self.shutdown_requested = True

        class FakeServer:
            def __init__(self):
                self.shutdown_requested = False

            def request_shutdown(self):
                self.shutdown_requested = True

        controller = object.__new__(WinUXController)
        controller._closing = False
        controller.view = FakeView()
        controller.server = FakeServer()
        controller._job_poll_cancel = None
        controller._schedule_wakeup = threading.Event()
        controller._reconnect_active = True
        controller._job_delete_lock = threading.Lock()
        controller._job_delete_tasks = {}
        controller._job_run_lock = threading.Lock()
        controller._job_run_tasks = {}
        controller.transfer_cancel = threading.Event()
        controller._clipboard_prepare_cancel = None

        with mock.patch.dict(
                "os.environ", {"WINUX_STANDALONE_PROCESS": "1"}, clear=False), \
                mock.patch("WinUx.controller.hide_registered_process_windows") as hide_children, \
                mock.patch("WinUx.controller.terminate_registered_children") as terminate_children, \
                mock.patch(
                    "WinUx.controller.os._exit", side_effect=SystemExit(0)) as hard_exit:
            with self.assertRaises(SystemExit):
                controller._finish_close()

        hide_children.assert_called_once_with()
        terminate_children.assert_called_once_with(
            grace_timeout=0.12, force_timeout=0.25)
        hard_exit.assert_called_once_with(0)
        self.assertTrue(controller.view.shutdown_requested)
        self.assertTrue(controller.server.shutdown_requested)
        self.assertTrue(controller.transfer_cancel.is_set())


class ChildProcessRegistryTests(unittest.TestCase):
    class _FakeProcess:
        def __init__(self, pid, alive=True):
            self.pid = pid
            self.alive = alive

        def poll(self):
            return None if self.alive else 0

    def test_registry_keeps_live_helper_after_dialog_object_can_disappear(self):
        from WinUx.runtime.child_processes import (
            register_child_process, registered_child_pids,
            unregister_child_process,
        )

        process = self._FakeProcess(987654)
        register_child_process(process, "test-helper")
        try:
            self.assertIn(process.pid, registered_child_pids())
            process.alive = False
            self.assertNotIn(process.pid, registered_child_pids())
        finally:
            unregister_child_process(process)

    def test_unregister_accepts_process_object(self):
        from WinUx.runtime.child_processes import (
            register_child_process, registered_child_pids,
            unregister_child_process,
        )

        process = self._FakeProcess(987655)
        register_child_process(process, "test-helper")
        unregister_child_process(process)
        self.assertNotIn(process.pid, registered_child_pids())


class StandaloneLaunchTests(unittest.TestCase):
    def test_launcher_marks_child_as_disposable_standalone_process(self):
        import winux_launcher

        environment = winux_launcher._launch_environment(
            str(ROOT), environ={})
        self.assertEqual(environment["WINUX_STANDALONE_PROCESS"], "1")

    def test_run_script_marks_direct_child_as_standalone(self):
        source = (ROOT / "run_winux.py").read_text(encoding="utf-8")
        self.assertIn(
            'os.environ.setdefault("WINUX_STANDALONE_PROCESS", "1")',
            source,
        )


if __name__ == "__main__":
    unittest.main()
