from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from ..services import windows_clipboard
from ..services.server_cut_monitor import ServerCutMonitor
from ..services.clipboard_cache import ClipboardCache


class FileClipboardController:
    """Own file clipboard publication/resolution and remote snapshot preparation."""

    def __init__(self, app):
        self.app = app
        self._cut_monitor = ServerCutMonitor(app)
        self._cache = ClipboardCache(app._clipboard_cache_root)

    @property
    def view(self):
        return self.app.view

    @property
    def server(self):
        return self.app.server

    def cleanup_cache(self):
        return self._cache.cleanup()

    def _discard_stage(self, stage_dir):
        self.app._submit_background("clipboard-snapshot-cleanup", self._cache.discard,
                                    stage_dir, key=("clipboard-cleanup", str(stage_dir)), coalesce=True)

    def reset(self):
        cancel = self.app._clipboard_prepare_cancel
        if cancel is not None:
            cancel.set()
        # Invalidate callbacks from an in-flight remote clipboard snapshot.
        self.app._clipboard_generation += 1
        self.app._clipboard_prepare_cancel = None
        self.app._clipboard_prepare_pending = False
        self.app.clipboard = []
        self.app.clipboard_move = False
        self.app.clipboard_panel_id = None
        self.app._clipboard_token = None
        self.app._clipboard_source_connection = None
        self.app._clipboard_expected_sequence = windows_clipboard.sequence_number()

    def begin(self, panel_id, paths, move):
        cancel = self.app._clipboard_prepare_cancel
        if cancel is not None:
            cancel.set()
        self.app._clipboard_generation += 1
        self.app.clipboard = list(paths)
        self.app.clipboard_move = bool(move)
        self.app.clipboard_panel_id = str(panel_id)
        self.app._clipboard_token = uuid.uuid4().hex
        self.app._clipboard_source_connection = (
            getattr(self.app, "_connection_generation", None) if panel_id == "server" else None)
        self.app._clipboard_prepare_cancel = None
        self.app._clipboard_prepare_pending = False
        self.app._clipboard_expected_sequence = windows_clipboard.sequence_number()
        return self.app._clipboard_generation, self.app._clipboard_token

    @staticmethod
    def item_names(paths):
        return [
            getattr(path, "name", None) or Path(str(path)).name
            for path in paths
        ]

    def publish(self, panel, paths, move):
        """Publish a WinUX selection to both the app and Windows Explorer."""
        generation, token = self.app._begin_internal_clipboard(
            panel.panel_id, paths, move)
        operation = "cut" if move else "copy"

        if panel.panel_id == "local":
            try:
                self.app._clipboard_expected_sequence = windows_clipboard.set_file_drop(
                    [str(path) for path in paths], move=move, token=token)
            except (OSError, ValueError) as exc:
                # Internal local/server paste still works even when another
                # process temporarily owns the Windows clipboard.
                panel.status.set(
                    "{} item(s) ready to {}; Windows clipboard unavailable".format(
                        len(paths), operation))
                self.view.show_error("Clipboard", str(exc))
                return
            panel.status.set(
                "{} item(s) ready to {}; paste in WinUX or Explorer".format(
                    len(paths), operation))
            return

        if not windows_clipboard.is_supported():
            panel.status.set(
                "{} item(s) ready to {} inside WinUX".format(
                    len(paths), operation))
            return

        self.app._prepare_server_file_clipboard(
            panel, list(paths), bool(move), generation, token)

    def prepare_server(
            self, panel, remote_paths, move, generation, token):
        """Download remote items to a private snapshot before CF_HDROP."""
        cancel_event = threading.Event()
        self.app._clipboard_prepare_cancel = cancel_event
        self.app._clipboard_prepare_pending = True
        start_sequence = windows_clipboard.sequence_number()
        self.app._clipboard_expected_sequence = start_sequence
        stage_dir = self.app._clipboard_cache_root / (
            "{}-{}".format(int(time.time() * 1000), token))
        connection = getattr(self.app, "_connection_generation", None)

        dialog = self.view.show_transfer_progress(
            "Preparing Clipboard", cancel_event,
            items=self.app._clipboard_item_names(remote_paths))
        panel.status.set(
            "Preparing {} server item(s) for Windows clipboard...".format(
                len(remote_paths)))
        last_update = [0.0]

        def progress(name, current_done, current_total,
                     overall_done, overall_total):
            now = time.monotonic()
            if now - last_update[0] < 0.1 and overall_done < overall_total:
                return
            last_update[0] = now
            self.view.after(
                0, dialog.update_progress, name, current_done, current_total,
                overall_done, overall_total)

        def worker():
            try:
                if (cancel_event.is_set() or self.app._closing or
                        generation != self.app._clipboard_generation):
                    raise RuntimeError("Operation cancelled")
                if connection != getattr(self.app, "_connection_generation", None):
                    raise RuntimeError("Server connection changed; copy the selection again")
                stage_dir.mkdir(parents=True, exist_ok=False)
                self.server.download(
                    remote_paths, stage_dir, move=False,
                    cancel=cancel_event, progress=progress)
                staged_paths = [
                    stage_dir / (getattr(path, "name", None)
                                 or Path(str(path)).name)
                    for path in remote_paths
                ]
            except Exception as exc:
                self.view.after(
                    0, self.app._server_clipboard_prepare_failed,
                    panel, generation, stage_dir, dialog, str(exc))
                return
            self.view.after(
                0, self._publish_prepared, connection,
                panel, generation, token, start_sequence,
                list(remote_paths), staged_paths, bool(move), stage_dir, dialog)

        handle = self.app._submit_transfer(
            "server-clipboard", worker,
            cancel_event=self.app._clipboard_prepare_cancel)
        if getattr(handle, "state", None) == "rejected":
            self.prepare_failed(panel, generation, stage_dir, dialog, "Transfer queue is full")

    def _publish_prepared(self, connection, panel, generation, token, start_sequence,
                          remote_paths, staged_paths, move, stage_dir, dialog):
        if connection != getattr(self.app, "_connection_generation", None):
            self.prepare_failed(panel, generation, stage_dir, dialog,
                                "Server connection changed; copy the selection again")
            return
        self.app._server_clipboard_prepare_finished(
            panel, generation, token, start_sequence, remote_paths, staged_paths,
            move, stage_dir, dialog)

    def prepare_failed(
            self, panel, generation, stage_dir, dialog, error):
        self._discard_stage(stage_dir)
        if self.app._closing:
            return
        if generation != self.app._clipboard_generation:
            # A newer Copy/Cut command owns the clipboard now.
            dialog.complete()
            return
        self.app._clipboard_prepare_pending = False
        self.app._clipboard_prepare_cancel = None
        if error == "Operation cancelled":
            dialog.complete()
            panel.status.set("Clipboard preparation cancelled")
            return
        dialog.fail(error)
        panel.status.set("Could not prepare server items for clipboard")
        self.view.show_error("Clipboard", error)

    def prepare_finished(
            self, panel, generation, token, start_sequence, remote_paths,
            staged_paths, move, stage_dir, dialog):
        if self.app._closing:
            self._discard_stage(stage_dir)
            return
        if generation != self.app._clipboard_generation:
            self._discard_stage(stage_dir)
            dialog.complete()
            return

        # Do not replace a newer selection copied by Explorer while a large
        # remote download was still being prepared.
        if windows_clipboard.sequence_number() != start_sequence:
            self._discard_stage(stage_dir)
            self.app._reset_internal_clipboard()
            dialog.complete()
            panel.status.set(
                "Clipboard changed; prepared server copy was discarded")
            return

        try:
            sequence = windows_clipboard.set_file_drop(
                staged_paths, move=move, token=token)
        except (OSError, ValueError) as exc:
            self._discard_stage(stage_dir)
            self.app._clipboard_prepare_pending = False
            self.app._clipboard_prepare_cancel = None
            dialog.fail(str(exc))
            panel.status.set("Windows clipboard unavailable")
            self.view.show_error("Clipboard", str(exc))
            return

        self.app._clipboard_expected_sequence = sequence
        self.app._clipboard_prepare_pending = False
        self.app._clipboard_prepare_cancel = None
        dialog.complete()
        panel.status.set(
            "{} server item(s) ready to {}; paste in WinUX or Explorer".format(
                len(remote_paths), "cut" if move else "copy"))

        if move:
            self.monitor_cut(remote_paths, staged_paths)

    def cut_committed(self, count):
        self.view.right.status.set(
            "Moved {} server item(s) to Windows Explorer".format(count))
        self.app._refresh_all()

    def resolve(self):
        """Return ``(source, paths, move, internal, sequence)`` for paste."""
        if (self.app.clipboard_panel_id == "server" and
                getattr(self.app, "_clipboard_source_connection", None) !=
                getattr(self.app, "_connection_generation", None)):
            self.app._reset_internal_clipboard()
        current_sequence = windows_clipboard.sequence_number()
        try:
            payload = windows_clipboard.get_file_drop()
        except OSError:
            payload = None

        if self.app.clipboard:
            if payload is not None and payload.token == self.app._clipboard_token:
                return (
                    self.app.clipboard_panel_id, list(self.app.clipboard),
                    bool(self.app.clipboard_move), True, current_sequence)
            if current_sequence == self.app._clipboard_expected_sequence:
                return (
                    self.app.clipboard_panel_id, list(self.app.clipboard),
                    bool(self.app.clipboard_move), True, current_sequence)

        if payload is None:
            return None
        return (
            "local", [Path(path) for path in payload.paths],
            bool(payload.move), False, current_sequence)

    def paste(self, target_panel):
        resolved = self.app._resolve_file_clipboard()
        if resolved is None:
            target_panel.status.set(
                "Clipboard does not contain files or folders")
            return
        source_panel_id, sources, move, internal, source_sequence = resolved
        if not sources:
            return
        if (internal and source_panel_id == "server"
                and self.app._clipboard_prepare_pending):
            target_panel.status.set(
                "Please wait until the server clipboard is ready")
            return
        if target_panel.panel_id == "server" and not self.server.connected:
            self.view.show_error("Paste", "SSH server is not connected")
            return
        self.app._start_clipboard_transfer(
            target_panel, source_panel_id, sources, move,
            internal, source_sequence)

    def monitor_cut(self, remote_paths, staged_paths):
        return self._cut_monitor.register(remote_paths, staged_paths)

    def close(self):
        self._cut_monitor.close()

