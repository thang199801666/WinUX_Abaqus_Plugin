"""Behavioral guards for asynchronous directory navigation."""
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from WinUx.controllers.navigation import NavigationController


def app_fixture():
    callbacks, workers = [], []
    local = SimpleNamespace(panel_id="local", status=Mock(), display=Mock(), focus=Mock())
    remote = SimpleNamespace(panel_id="server", status=Mock(), focus=Mock())
    app = SimpleNamespace(
        _closing=False, _initial_load_pending=True, _local_nav_generation=0,
        _server_nav_generation=0, _connection_generation=0,
        initial_local=Path("initial"), navigation_preferences=Mock(),
        model=SimpleNamespace(normalize=Path, list_directory=Mock(return_value=["local-item"])),
        server=SimpleNamespace(normalize=PurePosixPath, connected=True, host="host", username="user",
                               list_directory=Mock(return_value=["remote-item"]), set_shell_directory=Mock()),
        view=SimpleNamespace(left=local, right=remote, winfo_exists=lambda: True,
                             display_server_directory=Mock(), show_error=Mock(),
                             after=lambda delay, callback, *args: callbacks.append((callback, args))),
        _submit_background=lambda name, worker, **kwargs: workers.append(worker),
        _ensure_server_online=lambda: True, _watch_local_path=Mock(), _launch=Mock(),
        _start_reconnect=Mock(),
    )
    component = NavigationController(app)
    app._local_path_loaded = component.local_loaded
    app._local_path_failed = component.local_failed
    app._server_path_loaded = component.server_loaded
    app._server_path_failed = component.server_failed
    app._initial_local_loaded = component.initial_loaded
    app._initial_local_failed = component.initial_failed
    return app, component, workers, callbacks


def drain(callbacks):
    while callbacks:
        callback, args = callbacks.pop(0)
        callback(*args)


class NavigationTests(unittest.TestCase):
    def test_local_navigation_probes_and_lists_only_in_worker(self):
        app, navigation, workers, callbacks = app_fixture()
        with patch.object(Path, "is_file", return_value=False) as probe:
            navigation.open(app.view.left, "local", False)
            probe.assert_not_called()
            app.model.list_directory.assert_not_called()
            workers[0]()
        app.view.left.display.assert_not_called()
        drain(callbacks)
        app.view.left.display.assert_called_once_with(Path("local"), ["local-item"], False)
        app._watch_local_path.assert_called_once_with(Path("local"))

    def test_rapid_navigation_skips_old_reads_and_startup(self):
        app, navigation, workers, callbacks = app_fixture()
        navigation.load_initial()
        navigation.open(app.view.left, "new")
        workers[0]()
        app.model.list_directory.assert_not_called()
        self.assertFalse(app._initial_load_pending)
        navigation.open(app.view.left, "newer")
        workers[1]()
        app.model.list_directory.assert_not_called()

    def test_file_launch_is_queued_and_superseded_launch_is_ignored(self):
        app, navigation, workers, callbacks = app_fixture()
        navigation.open(app.view.left, "file")
        with patch.object(Path, "is_file", return_value=True):
            workers[0]()
        app._launch.assert_not_called()
        navigation.open(app.view.left, "other")
        drain(callbacks)
        app._launch.assert_not_called()

    def test_current_file_launch_runs_on_ui_dispatch(self):
        app, navigation, workers, callbacks = app_fixture()
        navigation.open(app.view.left, "file")
        with patch.object(Path, "is_file", return_value=True):
            workers[0]()
        drain(callbacks)
        app._launch.assert_called_once_with(Path("file"))

    def test_reconnect_discards_queued_server_result(self):
        app, navigation, workers, callbacks = app_fixture()
        navigation.open(app.view.right, "/remote")
        workers[0]()
        app._connection_generation += 1
        drain(callbacks)
        app.view.display_server_directory.assert_not_called()

    def test_superseded_server_worker_skips_wire_calls(self):
        app, navigation, workers, _ = app_fixture()
        navigation.open(app.view.right, "/old")
        navigation.open(app.view.right, "/new")
        workers[0]()
        app.server.list_directory.assert_not_called()
        app.server.set_shell_directory.assert_not_called()

    def test_current_server_result_records_history_and_saved_path(self):
        app, navigation, workers, callbacks = app_fixture()
        navigation.open(app.view.right, "/new", False)
        workers[0]()
        drain(callbacks)
        app.view.display_server_directory.assert_called_once_with(
            PurePosixPath("/new"), ["remote-item"], "host", record_history=False)
        app.navigation_preferences.save_server.assert_called_once_with("host", "user", PurePosixPath("/new"))

    def test_closed_window_rejects_initial_and_local_results(self):
        app, navigation, _, _ = app_fixture()
        app.view.winfo_exists = lambda: False
        navigation.initial_loaded(Path("initial"), [])
        navigation.local_loaded(app.view.left, Path("local"), [], True, 0)
        app.view.left.display.assert_not_called()

