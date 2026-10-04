"""Streaming coordination, retries and transactional-save routing."""
from pathlib import PurePosixPath
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from WinUx.controllers.server_notepad import ServerNotepadController
from WinUx.services.server_text import RemoteTextConflictError


def fixture():
    workers, callbacks, submissions = [], [], []
    def submit(name, worker, **kwargs):
        workers.append(worker)
        submissions.append((name, kwargs))
        return SimpleNamespace(state="pending")
    def stream(path, begin, chunk, end):
        begin({"path": str(path)})
        chunk("first", 5)
        chunk("second", 11)
        end({"path": str(path), "signature": "sig"})
    app = SimpleNamespace(
        _closing=False, _connection_generation=1,
        server=SimpleNamespace(connected=True, normalize=PurePosixPath,
                               stream_text_snapshot=Mock(side_effect=stream),
                               write_text_snapshot=Mock(return_value={"path": "/file"})),
        view=SimpleNamespace(right=SimpleNamespace(status=Mock(), current_path="/"),
                             after=lambda delay, callback, *args: callbacks.append((callback, args)),
                             show_error=Mock(), show_server_notepad=Mock()),
        _ensure_server_online=lambda: True, _submit_background=submit, open_path=Mock(),
    )
    component = ServerNotepadController(app)
    app._server_notepad_stream_finished = component.stream_finished
    app._server_notepad_saved = component.saved
    app._load_server_notepad = component.load
    app._save_server_notepad = component.save
    app._reload_server_notepad = component.reload
    dialog = SimpleNamespace(winfo_exists=lambda: True, stream_begin=Mock(return_value=True),
                             stream_chunk=Mock(return_value=True), stream_end=Mock(return_value=True),
                             operation_failed=Mock(), save_conflict=Mock(), save_succeeded=Mock())
    return app, component, dialog, workers, callbacks, submissions


def drain(callbacks):
    while callbacks:
        callback, args = callbacks.pop(0)
        callback(*args)


class NotepadControllerTests(unittest.TestCase):
    def test_load_and_reload_share_ordered_stream_without_full_text_snapshot(self):
        for operation in ("load", "reload"):
            with self.subTest(operation=operation):
                app, component, dialog, workers, callbacks, _ = fixture()
                getattr(component, operation)(dialog, "/file")
                dialog.stream_begin.assert_not_called()
                workers[0]()
                dialog.stream_begin.assert_called_once_with(operation, {"path": "/file"})
                self.assertEqual(dialog.stream_chunk.call_args_list[0].args, (operation, "/file", "first", 5))
                self.assertEqual(dialog.stream_chunk.call_args_list[1].args, (operation, "/file", "second", 11))
                self.assertGreaterEqual(dialog.stream_end.call_args.args[1]["load_seconds"], 0)
                drain(callbacks)
                self.assertEqual(component._reads, {})

    def test_new_read_cancels_old_read_before_wire_io(self):
        app, component, dialog, workers, callbacks, _ = fixture()
        component.load(dialog, "/file")
        component.reload(dialog, "/file")
        workers[0]()
        app.server.stream_text_snapshot.assert_not_called()
        workers[1]()
        drain(callbacks)
        dialog.stream_begin.assert_called_once_with("reload", {"path": "/file"})
        self.assertEqual(component._reads, {})

    def test_reconnect_rejects_queued_read_and_reports_error(self):
        app, component, dialog, workers, callbacks, _ = fixture()
        component.load(dialog, "/file")
        app._connection_generation += 1
        workers[0]()
        drain(callbacks)
        app.server.stream_text_snapshot.assert_not_called()
        self.assertIn("connection changed", dialog.operation_failed.call_args.args[0])

    def test_missing_file_retry_is_bounded(self):
        app, component, dialog, workers, callbacks, _ = fixture()
        app.server.stream_text_snapshot.side_effect = FileNotFoundError("missing")
        component.load(dialog, "/file")
        workers[0]()
        drain(callbacks)
        self.assertEqual(app.server.stream_text_snapshot.call_count, 2)
        dialog.operation_failed.assert_called_once()

    def test_reload_does_not_retry_missing_file(self):
        app, component, dialog, workers, callbacks, _ = fixture()
        app.server.stream_text_snapshot.side_effect = FileNotFoundError("missing")
        component.reload(dialog, "/file")
        workers[0]()
        drain(callbacks)
        app.server.stream_text_snapshot.assert_called_once()

    def test_closed_dialog_stops_stream_and_drops_callback(self):
        app, component, dialog, workers, callbacks, _ = fixture()
        component.load(dialog, "/file")
        dialog.winfo_exists = lambda: False
        workers[0]()
        drain(callbacks)
        app.server.stream_text_snapshot.assert_not_called()
        dialog.operation_failed.assert_not_called()

    def test_pipe_backpressure_failure_stops_read(self):
        app, component, dialog, workers, callbacks, _ = fixture()
        dialog.stream_chunk.return_value = False
        component.load(dialog, "/file")
        workers[0]()
        drain(callbacks)
        dialog.stream_end.assert_not_called()
        self.assertEqual(component._reads, {})

    def test_queue_rejection_reports_load_and_save(self):
        app, component, dialog, _, _, _ = fixture()
        app._submit_background = lambda *args, **kwargs: SimpleNamespace(state="rejected")
        component.load(dialog, "/file")
        self.assertEqual(component._reads, {})
        self.assertIn("queue is full", dialog.operation_failed.call_args.args[0])
        component.save(dialog, "/file", "text", "utf-8", "sig", False)
        self.assertEqual(dialog.operation_failed.call_args.args[-1], "save")

    def test_save_passes_signature_encoding_and_force_and_refreshes_pane(self):
        app, component, dialog, workers, callbacks, _ = fixture()
        component.save(dialog, "/file", "text", "utf-8", "sig", True)
        workers[0]()
        app.server.write_text_snapshot.assert_called_once_with("/file", "text", "sig", encoding="utf-8", force=True)
        drain(callbacks)
        dialog.save_succeeded.assert_called_once_with({"path": "/file"})
        app.open_path.assert_called_once_with(app.view.right, "/", False)

    def test_save_conflict_routes_to_conflict_dialog(self):
        app, component, dialog, workers, callbacks, _ = fixture()
        app.server.write_text_snapshot.side_effect = RemoteTextConflictError("changed")
        component.save(dialog, "/file", "text", "utf-8", "sig", False)
        workers[0]()
        drain(callbacks)
        dialog.save_conflict.assert_called_once_with("changed", "/file")

    def test_session_change_prevents_queued_save(self):
        app, component, dialog, workers, callbacks, _ = fixture()
        component.save(dialog, "/file", "text", "utf-8", "sig", False)
        app._connection_generation += 1
        workers[0]()
        drain(callbacks)
        app.server.write_text_snapshot.assert_not_called()
        dialog.operation_failed.assert_called_once()

    def test_close_releases_pending_reads_and_prevents_io(self):
        app, component, dialog, workers, callbacks, _ = fixture()
        component.load(dialog, "/file")
        component.close()
        workers[0]()
        drain(callbacks)
        app.server.stream_text_snapshot.assert_not_called()
        self.assertEqual(component._reads, {})

    def test_session_change_discards_queued_stream_completion(self):
        app, component, dialog, workers, callbacks, _ = fixture()
        component.load(dialog, "/file")
        workers[0]()
        app._connection_generation += 1
        drain(callbacks)
        dialog.operation_failed.assert_called_once()
