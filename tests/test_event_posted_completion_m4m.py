import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from WinUx.runtime.task_manager import BackgroundTaskManager
from WinUx.runtime.ui_dispatcher import UiDispatcher
from WinUx.controllers.explorer.navigation import NavigationController


class EventPostedCompletionM4mTests(unittest.TestCase):
    def test_coalesced_post_delivers_once_per_pending_key(self):
        dispatcher = UiDispatcher()
        delivered = []
        self.assertTrue(dispatcher.post(delivered.append, 1, key="refresh"))
        self.assertFalse(dispatcher.post(delivered.append, 2, key="refresh"))
        self.assertEqual(dispatcher.diagnosticsSnapshot()["coalesced_posts"], 1)
        dispatcher.processEvents(max_callbacks=None, time_budget_ms=None)
        self.assertEqual(delivered, [1])
        self.assertEqual(dispatcher.diagnosticsSnapshot()["coalesced_posts"], 0)
        self.assertTrue(dispatcher.post(delivered.append, 3, key="refresh"))
        dispatcher.processEvents(max_callbacks=None, time_budget_ms=None)
        self.assertEqual(delivered, [1, 3])
        dispatcher.close()

    def test_task_completion_runs_only_on_ui_dispatcher(self):
        dispatcher = UiDispatcher()
        manager = BackgroundTaskManager(
            max_workers=1, max_pending=4, name="m4m-test",
            completion_dispatcher=dispatcher,
        )
        owner_thread = threading.get_ident()
        callbacks = []
        handle = manager.submit(
            "value", lambda: 42,
            on_done=lambda task: callbacks.append(
                (threading.get_ident(), task.state, task.result)),
        )
        self.assertTrue(handle.wait(2.0))
        self.assertEqual(callbacks, [])
        dispatcher.processEvents(max_callbacks=None, time_budget_ms=None)
        self.assertEqual(callbacks, [(owner_thread, "completed", 42)])
        manager.close()
        dispatcher.close()

    def test_rejected_task_posts_terminal_completion(self):
        dispatcher = UiDispatcher()
        manager = BackgroundTaskManager(
            max_workers=1, max_pending=1, name="m4m-reject",
            completion_dispatcher=dispatcher,
        )
        manager.close()
        callbacks = []
        handle = manager.submit(
            "rejected", lambda: None,
            on_done=lambda task: callbacks.append(task.state),
        )
        self.assertEqual(handle.state, "rejected")
        self.assertEqual(callbacks, [])
        dispatcher.processEvents(max_callbacks=None, time_budget_ms=None)
        self.assertEqual(callbacks, ["rejected"])
        dispatcher.close()

    def test_initial_navigation_uses_task_completion_instead_of_worker_ui_post(self):
        loaded = []
        failed = []

        class Model:
            def list_directory(self, path):
                return ["a", "b"]

        app = SimpleNamespace(
            _closing=False,
            _initial_load_pending=True,
            initial_local=Path("."),
            model=Model(),
            server=None,
            view=SimpleNamespace(),
            _initial_local_loaded=lambda path, items: loaded.append((path, items)),
            _initial_local_failed=lambda error: failed.append(error),
        )

        def submit(_name, worker, **kwargs):
            result = worker()
            handle = SimpleNamespace(state="completed", result=result, exception=None)
            # Simulate BackgroundTaskManager delivering completion on the UI
            # turn after the worker has returned.
            kwargs["on_done"](handle)
            return handle

        app._submit_background = submit
        NavigationController(app).load_initial()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0][1], ["a", "b"])
        self.assertEqual(failed, [])


if __name__ == "__main__":
    unittest.main()
