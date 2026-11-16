from __future__ import annotations

import inspect
import types
import unittest

from WinUx.controllers.explorer.navigation import NavigationController
from WinUx.controllers.inp.analysis import InpAnalysisController
from WinUx.controllers.jobs.polling import JobPollingController


class _Status:
    def __init__(self):
        self.value = None
    def set(self, value):
        self.value = value


class _Panel:
    def __init__(self, panel_id):
        self.panel_id = panel_id
        self.status = _Status()
        self.current_path = None
        self.listview = types.SimpleNamespace(
            _rename_active=False, _mouse_down=False, _rubber_active=False,
            _drag_started=False, _item_drag_active=False,
        )


class _Dispatcher:
    def __init__(self):
        self.posts = []
    def post(self, callback, *args, key=None):
        self.posts.append((callback, args, key))
        return True


class _View:
    def __init__(self):
        self._dispatcher = _Dispatcher()
        self.after_calls = []
        self.errors = []
    def eventDispatcher(self):
        return self._dispatcher
    def after(self, *args):
        self.after_calls.append(args)
    def winfo_exists(self):
        return True
    def show_error(self, *args):
        self.errors.append(args)


class _Path:
    suffix = ".txt"
    name = "folder"
    def __init__(self, value, is_file=False):
        self.value = value
        self._is_file = is_file
    def is_file(self):
        return self._is_file
    def __str__(self):
        return self.value


class _Handle:
    def __init__(self, result=None, state="completed", exception=None):
        self.result = result
        self.state = state
        self.exception = exception


class M4nEventPostedFeatureCompletionTests(unittest.TestCase):
    def test_local_navigation_worker_returns_data_and_on_done_owns_ui_delivery(self):
        view = _View()
        path = _Path("C:/data")
        model = types.SimpleNamespace(
            normalize=lambda value: path,
            list_directory=lambda value: ["a", "b"],
        )
        submitted = {}
        loaded = []
        app = types.SimpleNamespace(
            _closing=False, _initial_load_pending=False,
            _local_nav_generation=0, model=model, view=view,
            server=None,
            _submit_background=lambda name, callback, *args, **kwargs: submitted.update(
                name=name, callback=callback, kwargs=kwargs),
            _local_path_loaded=lambda *args: loaded.append(args),
            _local_path_failed=lambda *args: self.fail("unexpected local failure"),
            _ensure_server_online=lambda: True,
        )
        controller = NavigationController(app)
        controller.open(_Panel("local"), path)
        self.assertEqual(submitted["name"], "local-navigation")
        self.assertIn("on_done", submitted["kwargs"])
        result = submitted["callback"]()
        self.assertEqual(result, ("loaded", ["a", "b"]))
        self.assertEqual(view.after_calls, [])
        submitted["kwargs"]["on_done"](_Handle(result=result))
        self.assertEqual(len(loaded), 1)

    def test_server_navigation_worker_never_schedules_retained_ui(self):
        view = _View()
        path = "/remote"
        server = types.SimpleNamespace(
            normalize=lambda value: path,
            list_directory=lambda value: ["x"],
        )
        submitted = {}
        delivered = []
        app = types.SimpleNamespace(
            _closing=False, _server_nav_generation=0,
            _connection_generation=3, model=None, server=server, view=view,
            _submit_background=lambda name, callback, *args, **kwargs: submitted.update(
                name=name, callback=callback, kwargs=kwargs),
            _server_path_loaded=lambda *args: delivered.append(args),
            _server_path_failed=lambda *args: self.fail("unexpected server failure"),
            _ensure_server_online=lambda: True,
        )
        controller = NavigationController(app)
        panel = _Panel("server")
        controller.open(panel, path)
        result = submitted["callback"]()
        self.assertEqual(result, ("loaded", ["x"]))
        self.assertEqual(view.after_calls, [])
        submitted["kwargs"]["on_done"](_Handle(result=result))
        self.assertEqual(len(delivered), 1)

    def test_inp_worker_uses_background_task_completion_not_operation_context_post(self):
        source = inspect.getsource(InpAnalysisController.check_inp)
        self.assertIn("on_done=completed", source)
        self.assertNotIn("context.post(", source)

    def test_job_poller_marshals_thread_result_through_ui_dispatcher(self):
        view = _View()
        app = types.SimpleNamespace(view=view, server=None)
        controller = JobPollingController(app)
        seen = []
        controller._post_ui(seen.append, "done", key=("job", 1))
        self.assertEqual(view.after_calls, [])
        self.assertEqual(len(view._dispatcher.posts), 1)
        callback, args, key = view._dispatcher.posts[0]
        self.assertEqual(key, ("job", 1))
        callback(*args)
        self.assertEqual(seen, ["done"])

    def test_job_refresh_fallback_uses_on_done(self):
        source = inspect.getsource(JobPollingController.refresh_now)
        self.assertIn("on_done=completed", source)
        self.assertNotIn("context.post(", source)


if __name__ == "__main__":
    unittest.main()
