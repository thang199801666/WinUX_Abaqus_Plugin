"""Headless regression checks for callback and native watcher lifetimes.

Run with Abaqus Python: -m unittest discover -s tests -v
"""
import ast
from collections import deque
import importlib.util
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_callback_pump(dpg):
    # Exercise the real view method without importing/starting its GUI stack.
    tree = ast.parse((ROOT / "WinUx/view.py").read_bytes())
    view = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                and n.name == "WinUXView")
    method = next(n for n in view.body if isinstance(n, ast.FunctionDef)
                  and n.name == "_drain_dpg_callbacks")
    namespace = {"dpg": dpg, "sys": sys}
    exec(compile(ast.Module(body=[method], type_ignores=[]),
                 "WinUx/view.py", "exec"), namespace)
    return namespace[method.name]


class CallbackPumpTests(unittest.TestCase):
    def setUp(self):
        self.jobs = []
        self.errors = []

        def fetch():
            jobs, self.jobs = self.jobs, []
            return jobs

        dpg = SimpleNamespace(
            get_callback_queue=fetch,
            run_callbacks=lambda jobs: jobs[0][0](),
        )
        self.pump = load_callback_pump(dpg)
        self.view = SimpleNamespace(
            _dpg_callbacks=deque(), _alive=True,
            _handle_ui_callback_error=lambda cb, exc: self.errors.append(exc[1]),
        )

    def test_nested_modal_pump_preserves_order_and_ui_thread(self):
        calls = []
        owner = threading.get_ident()

        def record(name):
            self.assertEqual(threading.get_ident(), owner)
            calls.append(name)

        def modal():
            record("open")
            self.jobs.append((lambda: record("modal_ok"),))
            self.pump(self.view)
            record("return")

        self.jobs = [(modal,), (lambda: record("queued"),)]
        self.pump(self.view)
        self.assertEqual(calls, ["open", "queued", "modal_ok", "return"])
        self.assertFalse(self.view._dpg_callbacks)

    def test_callback_error_does_not_discard_following_input(self):
        calls = []

        def fail():
            raise ValueError("callback failure")

        self.jobs = [(fail,), (lambda: calls.append("ok"),)]
        self.pump(self.view)
        self.assertEqual(calls, ["ok"])
        self.assertEqual(len(self.errors), 1)

    def test_shutdown_stops_remaining_callbacks(self):
        calls = []
        self.jobs = [(lambda: setattr(self.view, "_alive", False),),
                     (lambda: calls.append("must not run"),)]
        self.pump(self.view)
        self.assertEqual(calls, [])


@unittest.skipUnless(sys.platform == "win32", "Windows native watcher")
class WatcherLifetimeTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "watcher_under_test", ROOT / "WinUx/services/local_file_watcher.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.events = []
        self.event_handles = iter((20, 30))
        self.module._KERNEL32 = SimpleNamespace(
            CreateFileW=lambda *args: 10,
            CreateEventW=lambda *args: next(self.event_handles),
            SetEvent=lambda handle: True,
            ResetEvent=lambda handle: True,
            ReadDirectoryChangesW=lambda *args: True,
            WaitForMultipleObjects=lambda *args: 1,
            GetOverlappedResult=self.complete,
            CloseHandle=lambda handle: self.events.append(("close", handle)),
        )
        self.module._cancel_io = lambda *args: self.events.append(("cancel",))

    def complete(self, handle, overlapped, returned, wait):
        self.events.append(("completion", bool(wait)))
        return False  # ERROR_OPERATION_ABORTED is an expected completion.

    def test_cancellation_is_completed_before_handles_are_closed(self):
        watcher = self.module.LocalFileSystemWatcher()
        watcher._run_windows(ROOT, watcher._stop_event)
        self.assertEqual(self.events[:2], [("cancel",), ("completion", True)])
        self.assertEqual(set(self.events[2:]),
                         {("close", 10), ("close", 20), ("close", 30)})
        self.assertIsNone(watcher._native_stop_handle)

    def test_old_watcher_does_not_clear_new_stop_handle(self):
        watcher = self.module.LocalFileSystemWatcher()

        def wait(*args):
            watcher._native_stop_handle = 99  # replacement watcher published
            return 1

        self.module._KERNEL32.WaitForMultipleObjects = wait
        watcher._run_windows(ROOT, watcher._stop_event)
        self.assertEqual(watcher._native_stop_handle, 99)
        self.assertNotIn(("close", 99), self.events)


if __name__ == "__main__":
    unittest.main()
