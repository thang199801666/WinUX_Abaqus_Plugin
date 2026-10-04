from __future__ import annotations

import threading
import time
from pathlib import Path

from ..services import windows_clipboard


class ClipboardTransferController:
    """Execute a frozen paste request and reconcile clipboard after completion."""

    def __init__(self, app):
        self.app = app

    @property
    def view(self):
        return self.app.view

    @property
    def server(self):
        return self.app.server

    @property
    def model(self):
        return self.app.model

    def start(
            self, target_panel, source_panel_id, sources, move,
            internal, source_sequence):
        sources = list(sources)
        destination = target_panel.current_path
        clipboard_generation = self.app._clipboard_generation
        connection = getattr(self.app, "_connection_generation", None)
        target_panel.status.set(
            "{} {} item(s) from clipboard...".format(
                "Moving" if move else "Copying", len(sources)))
        cancel_event = threading.Event()
        self.app.transfer_cancel = cancel_event
        uses_server = (
            source_panel_id == "server" or target_panel.panel_id == "server")
        progress_dialog = None
        progress_callback = None

        if uses_server:
            if source_panel_id == "local" and target_panel.panel_id == "server":
                transfer_name = "Upload"
            elif source_panel_id == "server" and target_panel.panel_id == "local":
                transfer_name = "Download"
            else:
                transfer_name = "Server Move" if move else "Server Copy"
            progress_dialog = self.view.show_transfer_progress(
                transfer_name, cancel_event,
                items=self.app._clipboard_item_names(sources))
            last_update = [0.0]

            def progress_callback(name, current_done, current_total,
                                  overall_done, overall_total):
                now = time.monotonic()
                if now - last_update[0] < 0.1 and overall_done < overall_total:
                    return
                last_update[0] = now
                self.view.after(
                    0, progress_dialog.update_progress, name,
                    current_done, current_total, overall_done, overall_total)

        def worker():
            try:
                if self.app._closing or cancel_event.is_set():
                    raise RuntimeError("Operation cancelled")
                if uses_server and connection != getattr(self.app, "_connection_generation", None):
                    raise RuntimeError("Server connection changed; paste the selection again")
                if source_panel_id == "local" and target_panel.panel_id == "local":
                    self.model.transfer(
                        sources, Path(destination), move=move)
                elif source_panel_id == "local" and target_panel.panel_id == "server":
                    self.server.upload(
                        sources, destination, move=move,
                        cancel=cancel_event, progress=progress_callback)
                elif source_panel_id == "server" and target_panel.panel_id == "local":
                    local_destination = Path(destination)
                    local_destination.mkdir(parents=True, exist_ok=True)
                    self.server.download(
                        sources, local_destination, move=move,
                        cancel=cancel_event, progress=progress_callback)
                else:
                    self.server.transfer(
                        sources, destination, move=move,
                        cancel=cancel_event)
            except Exception as exc:
                self.view.after(
                    0, self.app._clipboard_transfer_failed,
                    target_panel, progress_dialog, str(exc))
                return
            self.view.after(
                0, self._deliver_finished,
                target_panel, progress_dialog, bool(move), bool(internal),
                int(source_sequence), clipboard_generation)

        handle = self.app._submit_transfer("clipboard-transfer", worker, cancel_event=cancel_event)
        if getattr(handle, "state", None) == "rejected":
            self.failed(target_panel, progress_dialog, "Transfer queue is full")

    def _deliver_finished(self, panel, dialog, move, internal, sequence, generation):
        if self.app._closing:
            return
        internal = internal and generation == self.app._clipboard_generation
        self.app._clipboard_transfer_finished(panel, dialog, move, internal, sequence)

    def failed(
            self, target_panel, progress_dialog, error):
        if self.app._closing:
            return
        target_panel.status.set("Clipboard transfer failed")
        self.app._transfer_failed(error, progress_dialog)

    def finished(
            self, target_panel, progress_dialog, move, internal,
            source_sequence):
        if self.app._closing:
            return
        if progress_dialog:
            progress_dialog.complete()
        target_panel.status.set("Clipboard transfer completed")
        if move:
            if internal:
                self.app._reset_internal_clipboard()
            # Clear only the exact clipboard used to start this transfer. A
            # newer Ctrl+C performed while a long upload/download was running
            # must remain untouched.
            if windows_clipboard.sequence_number() == source_sequence:
                try:
                    windows_clipboard.clear()
                except OSError:
                    pass
        self.app._refresh_all()

