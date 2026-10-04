from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from WinUx.controllers.clipboard_transfer import ClipboardTransferController
from WinUx.controllers.file_clipboard import FileClipboardController
from WinUx.services.clipboard_cache import ClipboardCache
from WinUx.services.server_cut_monitor import ServerCutMonitor


class CutMonitorTests(unittest.TestCase):
    def fixture(self):
        now = [0.0]
        callbacks = []
        app = SimpleNamespace(_closing=False, _connection_generation=1,
                              server=SimpleNamespace(connected=True, delete=Mock(), exists=Mock(return_value=True)),
                              view=SimpleNamespace(after=lambda delay, cb, *args: callbacks.append((cb, args))),
                              _server_cut_committed_to_explorer=Mock())
        monitor = ServerCutMonitor(app, clock=lambda: now[0])
        return app, monitor, now, callbacks

    def register(self, monitor, staged):
        with patch("WinUx.services.server_cut_monitor.threading.Thread"):
            return monitor.register(["/source"], [staged])

    def test_idle_snapshots_do_not_query_server(self):
        app, monitor, now, _ = self.fixture()
        self.register(monitor, Mock(exists=Mock(return_value=True)))
        for value in range(60):
            now[0] = value
            monitor._poll_once()
        app.server.delete.assert_not_called()
        app.server.exists.assert_not_called()

    def test_disappeared_stage_commits_and_announces(self):
        app, monitor, _, callbacks = self.fixture()
        self.register(monitor, Mock(exists=Mock(return_value=False)))
        monitor._poll_once()
        app.server.delete.assert_called_once_with(["/source"])
        callback, args = callbacks.pop()
        callback(*args)
        app._server_cut_committed_to_explorer.assert_called_once_with(1)
        self.assertEqual(monitor._batches, {})

    def test_failed_deletes_back_off_instead_of_hot_loop(self):
        app, monitor, now, _ = self.fixture()
        app.server.delete.side_effect = OSError("permission denied")
        self.register(monitor, Mock(exists=Mock(return_value=False)))
        for value in range(60):
            now[0] = value
            monitor._poll_once()
        self.assertEqual(app.server.delete.call_count, 6)
        self.assertEqual(app.server.exists.call_count, 6)

    def test_reconnect_drops_old_cut_without_deleting(self):
        app, monitor, _, _ = self.fixture()
        self.register(monitor, Mock(exists=Mock(return_value=False)))
        app._connection_generation += 1
        monitor._poll_once()
        app.server.delete.assert_not_called()
        self.assertEqual(monitor._batches, {})

    def test_one_thread_for_many_cuts_and_close_is_nonblocking(self):
        _, monitor, _, _ = self.fixture()
        with patch("WinUx.services.server_cut_monitor.threading.Thread") as thread:
            for _ in range(100):
                monitor.register(["/source"], [Mock(exists=Mock(return_value=True))])
            thread.assert_called_once()
            monitor.close()
            thread.return_value.join.assert_not_called()
        self.assertEqual(monitor._batches, {})

    def test_expired_snapshots_do_not_delete_server_sources(self):
        app, monitor, now, _ = self.fixture()
        self.register(monitor, Mock(exists=Mock(return_value=False)))
        now[0] = 24 * 60 * 60
        monitor._poll_once()
        app.server.delete.assert_not_called()


def transfer_fixture():
    workers, callbacks = [], []
    app = SimpleNamespace(
        _closing=False, _clipboard_generation=1, _connection_generation=1,
        model=SimpleNamespace(transfer=Mock()), server=SimpleNamespace(upload=Mock()),
        view=SimpleNamespace(after=lambda delay, cb, *args: callbacks.append((cb, args)),
                             show_transfer_progress=Mock(return_value=Mock()), show_error=Mock()),
        _submit_transfer=lambda name, worker, **kwargs: workers.append(worker),
        _clipboard_item_names=lambda paths: [str(path) for path in paths],
        _reset_internal_clipboard=Mock(), _refresh_all=Mock(), _transfer_failed=Mock(),
    )
    transfer = ClipboardTransferController(app)
    app._clipboard_transfer_finished = transfer.finished
    app._clipboard_transfer_failed = transfer.failed
    target = SimpleNamespace(panel_id="local", current_path=Path("destination"), status=Mock())
    return app, transfer, target, workers, callbacks


class ClipboardTransferTests(unittest.TestCase):
    def test_destination_and_sources_are_frozen_at_paste_time(self):
        app, transfer, target, workers, _ = transfer_fixture()
        sources = [Path("source")]
        transfer.start(target, "local", sources, False, True, 10)
        sources.clear()
        target.current_path = Path("other")
        workers[0]()
        app.model.transfer.assert_called_once_with([Path("source")], Path("destination"), move=False)

    def test_newer_internal_clipboard_survives_old_move_completion(self):
        app, transfer, target, workers, callbacks = transfer_fixture()
        transfer.start(target, "local", [Path("source")], True, True, 10)
        app._clipboard_generation = 2
        workers[0]()
        callback, args = callbacks.pop()
        with patch("WinUx.controllers.clipboard_transfer.windows_clipboard.sequence_number", return_value=11), \
             patch("WinUx.controllers.clipboard_transfer.windows_clipboard.clear") as clear:
            callback(*args)
        app._reset_internal_clipboard.assert_not_called()
        clear.assert_not_called()

    def test_session_change_prevents_queued_upload(self):
        app, transfer, target, workers, callbacks = transfer_fixture()
        target.panel_id = "server"
        transfer.start(target, "local", [Path("source")], False, True, 10)
        app._connection_generation += 1
        workers[0]()
        app.server.upload.assert_not_called()
        callback, args = callbacks.pop()
        callback(*args)
        app._transfer_failed.assert_called_once()

    def test_queue_rejection_reports_failure(self):
        app, transfer, target, _, _ = transfer_fixture()
        app._submit_transfer = lambda *args, **kwargs: SimpleNamespace(state="rejected")
        transfer.start(target, "local", [Path("source")], False, True, 10)
        app._transfer_failed.assert_called_once_with("Transfer queue is full", None)


class ClipboardCacheTests(unittest.TestCase):
    def test_discard_removes_only_direct_snapshot_child(self):
        with TemporaryDirectory() as root:
            cache = ClipboardCache(Path(root) / "cache")
            snapshot = cache.root / "snapshot"
            snapshot.mkdir(parents=True)
            (snapshot / "file").write_text("data")
            cache.discard(snapshot)
            self.assertFalse(snapshot.exists())
            self.assertTrue(cache.root.exists())
            with self.assertRaises(ValueError):
                cache.discard(cache.root)
            with self.assertRaises(ValueError):
                cache.discard(Path(root) / "outside")

    def test_cleanup_expires_old_snapshots_and_keeps_fresh_ones(self):
        import os
        with TemporaryDirectory() as root:
            cache = ClipboardCache(root)
            old, fresh = Path(root) / "old", Path(root) / "fresh"
            old.write_text("old")
            fresh.write_text("fresh")
            os.utime(old, (1, 1))
            cache.cleanup()
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())

    def test_preparation_rejection_releases_pending_clipboard(self):
        with TemporaryDirectory() as root:
            app, _, target, _, _ = transfer_fixture()
            app._clipboard_cache_root = Path(root)
            app._submit_background = Mock()
            app._submit_transfer = lambda *args, **kwargs: SimpleNamespace(state="rejected")
            clipboard = FileClipboardController(app)
            with patch("WinUx.controllers.file_clipboard.windows_clipboard.sequence_number", return_value=0):
                clipboard.prepare_server(target, [Path("source")], False, 1, "token")
            self.assertFalse(app._clipboard_prepare_pending)
            app._submit_background.assert_called_once()
            app.view.show_transfer_progress.return_value.fail.assert_called_once_with("Transfer queue is full")

    def test_old_connection_preparation_is_not_published(self):
        with TemporaryDirectory() as root:
            app, _, target, _, _ = transfer_fixture()
            app._clipboard_cache_root = Path(root)
            app._submit_background = Mock()
            app._server_clipboard_prepare_finished = Mock()
            clipboard = FileClipboardController(app)
            dialog = Mock()
            clipboard._publish_prepared(0, target, 1, "token", 10,
                                        ["/source"], [Path(root) / "stage/file"],
                                        True, Path(root) / "stage", dialog)
            app._server_clipboard_prepare_finished.assert_not_called()
            dialog.fail.assert_called_once_with("Server connection changed; copy the selection again")

    def test_stale_server_source_is_not_used_after_reconnect(self):
        with TemporaryDirectory() as root:
            app, _, _, _, _ = transfer_fixture()
            app._clipboard_cache_root = Path(root)
            app.clipboard = ["/source"]
            app.clipboard_panel_id = "server"
            app._clipboard_source_connection = 0
            app._reset_internal_clipboard.side_effect = lambda: setattr(app, "clipboard", [])
            clipboard = FileClipboardController(app)
            with patch("WinUx.controllers.file_clipboard.windows_clipboard.sequence_number", return_value=11), \
                 patch("WinUx.controllers.file_clipboard.windows_clipboard.get_file_drop", return_value=None):
                self.assertIsNone(clipboard.resolve())
            app._reset_internal_clipboard.assert_called_once()
