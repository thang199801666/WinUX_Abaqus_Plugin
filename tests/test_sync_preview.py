"""Directory comparison and stale asynchronous scan regression coverage."""
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from WinUx.controllers.sync_preview import SyncPreviewController
from WinUx.controller import WinUXController


def item(name, size=10, modified=100, is_dir=False):
    return SimpleNamespace(name=name, size=size, modified=modified, is_dir=is_dir)


class SyncComparisonTests(unittest.TestCase):
    def rows(self, local, remote):
        return SyncPreviewController.build_rows(local, remote, Path("local"), "/remote")

    def test_comparison_actions_and_metadata_tolerance(self):
        local = [item("same"), item("tolerance", modified=102), item("upload"),
                 item("newer", modified=103), item("older", modified=97), item("size")]
        remote = [item("same"), item("tolerance"), item("download"),
                  item("newer"), item("older"), item("size", size=11)]
        rows = self.rows(local, remote)
        self.assertEqual([row["name"] for row in rows], ["download", "newer", "older", "size", "upload"])
        self.assertEqual([row["action"] for row in rows], ["Download", "Upload", "Download", "Review", "Upload"])
        self.assertEqual(rows[0]["server_path"], "/remote/download")
        self.assertEqual(rows[-1]["local_path"], str(Path("local") / "upload"))
        self.assertFalse(rows[0]["local_exists"])
        self.assertFalse(rows[-1]["server_exists"])

    def test_directories_are_excluded_even_when_other_side_has_a_file(self):
        self.assertEqual(self.rows([item("folder", is_dir=True), item("file")],
                                   [item("folder"), item("file", is_dir=True)]), [])

    def test_names_preserve_case_and_ignore_unnamed_entries(self):
        rows = self.rows([item("A"), item("")], [item("a"), item(None)])
        self.assertEqual({row["name"]: row["action"] for row in rows}, {"A": "Upload", "a": "Download"})

    def test_metadata_is_extracted_once_per_named_item(self):
        original = SyncPreviewController.item_fields
        with patch.object(SyncPreviewController, "item_fields", wraps=original) as fields:
            self.rows([item("a"), item("b")], [item("a")])
        self.assertEqual(fields.call_count, 3)

    def test_facade_preserves_comparison_contract(self):
        local = [item("a")]
        self.assertEqual(WinUXController._build_sync_rows(local, [], "local", "/remote"),
                         self.rows(local, []))


def make_app():
    callbacks, workers = [], []
    view = SimpleNamespace(
        left=SimpleNamespace(current_path=Path("local")),
        right=SimpleNamespace(current_path=PurePosixPath("/remote")),
        sync_preview_dialog=None,
        winfo_exists=lambda: True,
        after=lambda delay, callback, *args: callbacks.append((callback, args)),
        show_sync_preview=Mock(), show_error=Mock(), show_message=Mock(),
    )
    app = SimpleNamespace(
        view=view, _closing=False, _connection_generation=0,
        model=SimpleNamespace(list_directory=Mock(return_value=[item("a")])),
        server=SimpleNamespace(connected=True, normalize=PurePosixPath,
                               list_directory=Mock(return_value=[])),
        _ensure_server_online=lambda: True,
        _submit_background=lambda name, worker, **kwargs: workers.append(worker),
        _process_queued_drop=Mock(),
    )
    component = SyncPreviewController(app)
    app.sync_preview = component.preview
    app._sync_preview_ready = component.ready
    app._sync_transfer_rows = component.transfer_rows
    return app, component, workers, callbacks


def drain(callbacks):
    while callbacks:
        callback, args = callbacks.pop(0)
        callback(*args)


class SyncScanTests(unittest.TestCase):
    def test_latest_scan_publishes_and_routes_upload_to_captured_root(self):
        app, component, workers, callbacks = make_app()
        component.preview()
        workers[0]()
        self.assertFalse(app.view.show_sync_preview.called)
        drain(callbacks)
        rows = app.view.show_sync_preview.call_args.args[0]
        component.transfer_rows(rows)
        app._process_queued_drop.assert_called_once_with(
            app.view.left, app.view.right, PurePosixPath("/remote"), True, [Path("local/a")])

    def test_result_queued_before_a_new_scan_is_ignored(self):
        app, component, workers, callbacks = make_app()
        component.preview()
        workers[0]()
        component.preview()
        drain(callbacks)
        app.view.show_sync_preview.assert_not_called()
        workers[1]()
        drain(callbacks)
        app.view.show_sync_preview.assert_called_once()

    def test_superseded_worker_skips_directory_reads(self):
        app, component, workers, callbacks = make_app()
        component.preview()
        component.preview()
        workers[0]()
        app.model.list_directory.assert_not_called()
        app.server.list_directory.assert_not_called()
        self.assertEqual(callbacks, [])

    def test_new_scan_during_local_read_skips_old_remote_read(self):
        app, component, workers, callbacks = make_app()
        component.preview()
        app.model.list_directory.side_effect = lambda path: (component.preview() or [])
        workers[0]()
        app.server.list_directory.assert_not_called()
        self.assertEqual(callbacks, [])

    def test_navigation_close_and_disconnect_discard_results(self):
        for change in (lambda app: setattr(app.view.left, "current_path", Path("other")),
                       lambda app: setattr(app.view.right, "current_path", PurePosixPath("/other")),
                       lambda app: setattr(app, "_closing", True),
                       lambda app: setattr(app, "_connection_generation", 1),
                       lambda app: setattr(app.server, "connected", False),
                       lambda app: setattr(app.view, "winfo_exists", lambda: False)):
            with self.subTest(change=change):
                app, component, workers, callbacks = make_app()
                component.preview()
                workers[0]()
                change(app)
                drain(callbacks)
                app.view.show_sync_preview.assert_not_called()

    def test_stale_errors_are_ignored_but_current_errors_are_reported(self):
        app, component, workers, callbacks = make_app()
        app.server.list_directory.side_effect = OSError("scan failed")
        component.preview()
        workers[0]()
        component.preview()
        drain(callbacks)
        app.view.show_error.assert_not_called()
        workers[1]()
        drain(callbacks)
        app.view.show_error.assert_called_once_with("Directory Synchronization", "scan failed")

    def test_mixed_directions_require_separate_transfer_selection(self):
        app, component, _, _ = make_app()
        component.transfer_rows([{"action": "Upload", "local_path": "local/a"},
                                 {"action": "Download", "server_path": "/remote/b"}])
        app.view.show_message.assert_called_once()
        app._process_queued_drop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
