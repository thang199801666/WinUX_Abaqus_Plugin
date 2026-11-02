from __future__ import annotations

import threading
from pathlib import Path

from ...services import windows_clipboard
from ...runtime.transfer_progress import TransferProgressDelivery
from ...services.transfer.timestamps import timestamp_options


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
            "{} {} item(s){}...".format(
                "Moving" if move else "Copying", len(sources),
                " on server" if (source_panel_id == "server" and target_panel.panel_id == "server") else " from clipboard"))
        cancel_event = threading.Event()
        self.app.transfer_cancel = cancel_event
        uses_server = (
            source_panel_id == "server" or target_panel.panel_id == "server")
        server_to_server = (
            source_panel_id == "server" and target_panel.panel_id == "server")
        progress_dialog = None
        progress_callback = None
        delivery = None

        # Same-server clipboard operations never move file bytes through the
        # client, so a Transfer Center dialog would be misleading noise.  Keep
        # progress UI only for real upload/download operations.
        if uses_server and not server_to_server:
            if source_panel_id == "local" and target_panel.panel_id == "server":
                transfer_name = "Upload"
            else:
                transfer_name = "Download"
            progress_dialog = self.view.show_transfer_progress(
                transfer_name, cancel_event,
                items=self.app._clipboard_item_names(sources))
            delivery = TransferProgressDelivery(self.view.after, progress_dialog.update_progress)
            setter = getattr(progress_dialog, 'set_progress_delivery', None)
            if callable(setter):
                setter(delivery)
            progress_callback = delivery.progress

        transfer_options = timestamp_options(self.view)

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
                        cancel=cancel_event, progress=progress_callback, **transfer_options)
                elif source_panel_id == "server" and target_panel.panel_id == "local":
                    local_destination = Path(destination)
                    local_destination.mkdir(parents=True, exist_ok=True)
                    self.server.download(
                        sources, local_destination, move=move,
                        cancel=cancel_event, progress=progress_callback, **transfer_options)
                else:
                    self.server.transfer(
                        sources, destination, move=move,
                        cancel=cancel_event)
            except Exception as exc:
                if delivery is not None:
                    delivery.finish(self.app._clipboard_transfer_failed, target_panel, progress_dialog, str(exc))
                else:
                    self.view.after(0, self.app._clipboard_transfer_failed, target_panel, progress_dialog, str(exc))
                return
            args = (target_panel, progress_dialog, bool(move), bool(internal), int(source_sequence), clipboard_generation)
            if delivery is not None:
                delivery.finish(self._deliver_finished, *args)
            else:
                self.view.after(0, self._deliver_finished, *args)

        handle = self.app._submit_transfer("clipboard-transfer", worker, cancel_event=cancel_event)
        if getattr(handle, "state", None) == "rejected":
            if delivery is not None:
                delivery.close()
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
