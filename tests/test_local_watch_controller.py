"""Watch bursts, generation isolation and rename/scroll lifetime coverage."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from WinUx.controllers.local_watch import LocalWatchController


def fixture():
    callbacks, workers, submissions = [], [], []
    def submit(name, worker, **kwargs):
        submissions.append((name, kwargs))
        workers.append(worker)
        return SimpleNamespace(state="pending")
    app = SimpleNamespace(
        _closing=False, LOCAL_WATCH_DEBOUNCE_MS=250, LOCAL_WATCH_BUSY_RETRY_MS=120,
        model=SimpleNamespace(list_directory=Mock(return_value=["items"])),
        view=SimpleNamespace(left=SimpleNamespace(
            current_path=Path("folder"), listview=SimpleNamespace(_rename_active=False),
            status=Mock(), refresh_directory=Mock(return_value=42), restore_vertical_scroll=Mock()),
            after=lambda delay, callback, *args: callbacks.append((delay, callback, args))),
        _submit_background=submit,
    )
    watcher = SimpleNamespace(running=False, watch=Mock(), close=Mock())
    component = LocalWatchController(app, watcher)
    return app, component, watcher, workers, callbacks, submissions


def run_callback(callbacks):
    delay, callback, args = callbacks.pop(0)
    callback(*args)
    return delay


class LocalWatchTests(unittest.TestCase):
    def test_install_runs_off_ui_and_uses_current_generation(self):
        app, component, watcher, workers, callbacks, _ = fixture()
        component.watch("folder")
        watcher.watch.assert_not_called()
        watcher.close.assert_called_once_with(wait=False)
        workers[0]()
        watcher.watch.assert_called_once()
        callback = watcher.watch.call_args.args[1]
        callback(Path("folder"))
        self.assertEqual(len(callbacks), 1)

    def test_stopped_install_does_not_create_watcher(self):
        _, component, watcher, workers, _, _ = fixture()
        component.watch("folder")
        component.stop(wait=False)
        workers[0]()
        watcher.watch.assert_not_called()

    def test_stop_during_install_releases_new_watcher(self):
        _, component, watcher, workers, _, _ = fixture()
        watcher.watch.side_effect = lambda *args: component.stop(wait=False)
        component.watch("folder")
        workers[0]()
        self.assertEqual(watcher.close.call_count, 3)

    def test_burst_coalesces_and_pending_events_trigger_one_followup(self):
        app, component, _, workers, callbacks, _ = fixture()
        component.watch("folder")
        workers.pop(0)()
        for _ in range(10_000):
            component.changed(Path("folder"), component._generation)
        self.assertEqual(len(callbacks), 1)
        run_callback(callbacks)
        for _ in range(100):
            component.changed(Path("folder"), component._generation)
        self.assertEqual(len(workers), 1)
        workers.pop(0)()
        run_callback(callbacks)
        app.view.left.refresh_directory.assert_called_once()
        self.assertEqual(len(callbacks), 3)  # two scroll restores, one followup
        run_callback(callbacks)
        run_callback(callbacks)
        run_callback(callbacks)
        self.assertEqual(len(workers), 1)

    def test_late_read_waits_for_active_rename(self):
        app, component, _, workers, callbacks, _ = fixture()
        component.watch("folder")
        workers.pop(0)()
        component.changed(Path("folder"), component._generation)
        run_callback(callbacks)
        workers.pop(0)()
        app.view.left.listview._rename_active = True
        run_callback(callbacks)
        app.view.left.refresh_directory.assert_not_called()
        self.assertEqual(len(callbacks), 1)
        app.view.left.listview._rename_active = False
        run_callback(callbacks)
        app.view.left.refresh_directory.assert_called_once()

    def test_old_scroll_restore_cannot_move_new_directory(self):
        app, component, _, workers, callbacks, _ = fixture()
        component.watch("folder")
        workers.pop(0)()
        component.changed(Path("folder"), component._generation)
        run_callback(callbacks)
        workers.pop(0)()
        run_callback(callbacks)
        app.view.left.current_path = Path("new")
        component.watch("new")
        run_callback(callbacks)
        run_callback(callbacks)
        app.view.left.restore_vertical_scroll.assert_not_called()

    def test_refresh_keys_isolate_generations(self):
        app, component, _, workers, callbacks, submissions = fixture()
        component.watch("folder")
        workers.pop(0)()
        component.changed(Path("folder"), component._generation)
        run_callback(callbacks)
        first_key = submissions[-1][1]["key"]
        app.view.left.current_path = Path("new")
        component.watch("new")
        component.changed(Path("new"), component._generation)
        run_callback(callbacks)
        second_key = submissions[-1][1]["key"]
        self.assertNotEqual(first_key, second_key)

    def test_queue_rejection_recovers_refresh_state(self):
        app, component, _, workers, callbacks, _ = fixture()
        component.watch("folder")
        workers.pop(0)()
        app._submit_background = lambda *args, **kwargs: SimpleNamespace(state="rejected")
        component.changed(Path("folder"), component._generation)
        run_callback(callbacks)
        self.assertFalse(component._active)
        self.assertTrue(component._scheduled)
        self.assertEqual(len(callbacks), 1)

    def test_wrong_path_and_old_generation_notifications_are_ignored(self):
        _, component, _, workers, callbacks, _ = fixture()
        component.watch("folder")
        workers.pop(0)()
        component.changed(Path("wrong"), component._generation)
        component.changed(Path("folder"), component._generation - 1)
        self.assertEqual(callbacks, [])
