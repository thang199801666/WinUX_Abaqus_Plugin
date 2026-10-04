"""File transfer orchestration extracted from the application controller.

Pointer/drag routing remains in ``WinUXController``.  This component owns the
I/O-facing half of transfer commands: source/destination normalization,
conflict checks, overwrite continuation, progress wiring and completion.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from ..services import presentation


class TransferController:
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

    def transfer_selected(self, source_panel, paths=None):
        """Upload/download every selected file or folder as one batch."""
        if not self.app._ensure_server_online():
            return
        sources = list(paths if paths is not None else source_panel.selected_transfer_paths())
        if not sources:
            action = "Upload" if source_panel.panel_id == "local" else "Download"
            self.view.show_message(action, "Select one or more files or folders first.")
            return
        if source_panel.panel_id == "local":
            sources = [Path(path) for path in sources]
            target_panel = self.view.right
            action = "Upload"
        else:
            sources = [self.server.normalize(path) for path in sources]
            target_panel = self.view.left
            action = "Download"
        destination = target_panel.current_path
        source_panel.status.set("{}: {} item(s) selected...".format(action, len(sources)))
        self.process_queued_drop(source_panel, target_panel, destination, True, sources)

    def quick_transfer(self, source_panel, extension):
        if not self.app._ensure_server_online():
            return
        extension = str(extension).casefold()
        sources = list(source_panel.visible_files(extension))
        action = "Upload" if source_panel.panel_id == "local" else "Download"
        if not sources:
            self.view.show_message(
                "Quick {}".format(action),
                "No *{} files were found in the current folder.".format(extension))
            return
        target_panel = self.view.right if source_panel.panel_id == "local" else self.view.left
        destination = target_panel.current_path
        if source_panel.panel_id == "server":
            sources = [self.server.normalize(path) for path in sources]
        else:
            sources = [Path(path) for path in sources]
        source_panel.status.set("Checking destination for existing files...")

        def conflict_worker():
            try:
                conflicts = self.cross_panel_conflicts(target_panel, sources, destination)
            except Exception as exc:
                self.view.after(0, self.quick_conflict_failed, source_panel, str(exc))
                return
            self.view.after(
                0, self.quick_conflicts_ready,
                source_panel, target_panel, sources, destination,
                extension, action, conflicts)

        self.app._submit_background("quick-transfer-conflicts", conflict_worker)

    def quick_conflict_failed(self, source_panel, error):
        source_panel.status.set("Quick transfer failed")
        self.view.show_error("Quick transfer", error)

    def quick_conflicts_ready(
            self, source_panel, target_panel, sources, destination,
            extension, action, conflicts):
        if conflicts:
            self.view.confirm_action_async(
                "Overwrite?", self.format_conflict_message(conflicts),
                lambda accepted: self.continue_quick_after_overwrite(
                    bool(accepted), source_panel, target_panel,
                    list(sources), destination, extension, action))
            return
        source_panel.status.set("Starting quick {}...".format(action.lower()))
        self.view.after(
            self.app.POST_MODAL_TRANSFER_DELAY_MS,
            self.start_quick_transfer,
            source_panel, target_panel, list(sources), destination,
            extension, action)

    def continue_quick_after_overwrite(
            self, accepted, source_panel, target_panel, sources, destination,
            extension, action):
        if not accepted:
            source_panel.status.set("Quick {} cancelled".format(action.lower()))
            return
        source_panel.status.set("Starting quick {}...".format(action.lower()))
        self.view.after(
            self.app.POST_MODAL_TRANSFER_DELAY_MS,
            self.start_quick_transfer,
            source_panel, target_panel, list(sources), destination,
            extension, action)

    def start_quick_transfer(
            self, source_panel, target_panel, sources, destination,
            extension, action):
        cancel_event = threading.Event()
        self.app.transfer_cancel = cancel_event
        progress_dialog = self.view.show_transfer_progress(
            action, cancel_event, items=[source.name for source in sources])
        source_panel.status.set(
            "Quick {}: {} *{} file(s)...".format(
                action.lower(), len(sources), extension))
        target_panel.status.set("Receiving {} item(s)...".format(len(sources)))
        last_update = [0.0]

        def progress(name, current_done, current_total, overall_done, overall_total):
            now = time.monotonic()
            if now - last_update[0] < 0.1 and overall_done < overall_total:
                return
            last_update[0] = now
            self.view.after(
                0, progress_dialog.update_progress, name, current_done,
                current_total, overall_done, overall_total)

        def worker():
            try:
                if source_panel.panel_id == "local":
                    self.server.upload(
                        sources, destination, cancel=cancel_event, progress=progress)
                else:
                    self.server.download(
                        sources, Path(destination), cancel=cancel_event, progress=progress)
            except Exception as exc:
                self.view.after(
                    0, lambda error=str(exc): self.transfer_failed(error, progress_dialog))
                return
            self.view.after(0, self.transfer_succeeded, progress_dialog)

        self.app._submit_transfer("quick-transfer", worker, cancel_event=cancel_event)

    def opposite_panel(self, source_panel):
        panels = list(getattr(self.view, "panels", ()) or ())
        return next(
            (panel for panel in panels
             if panel is not source_panel and panel.panel_id != source_panel.panel_id),
            None)

    def process_queued_drop(
            self, source_panel, target_panel, destination, copy_requested,
            raw_sources, progress_dialog=None, cancel_event=None):
        if not target_panel or destination is None:
            target_panel = self.opposite_panel(source_panel)
            destination = target_panel.current_path if target_panel is not None else None
            if target_panel is None or destination is None:
                source_panel.status.set("Drop cancelled: file panels unavailable")
                if progress_dialog is not None:
                    progress_dialog.fail("Drop cancelled: file panels unavailable")
                return
        if source_panel.panel_id == "server":
            sources = [self.server.normalize(path) for path in raw_sources]
        else:
            sources = [Path(path) for path in raw_sources]
        if not sources:
            if progress_dialog is not None:
                progress_dialog.fail("Drop cancelled: no files selected")
            return
        if not self.drop_is_valid(source_panel, target_panel, sources, destination):
            source_panel.status.set("Drop cancelled: invalid destination")
            if progress_dialog is not None:
                progress_dialog.fail("Drop cancelled: invalid destination")
            return
        cross_panel = source_panel.panel_id != target_panel.panel_id
        if cross_panel:
            source_panel.status.set("Checking destination for existing files...")

            def conflict_worker():
                try:
                    conflicts = self.cross_panel_conflicts(target_panel, sources, destination)
                except Exception as exc:
                    self.view.after(
                        0, self.drop_conflict_failed,
                        source_panel, str(exc), progress_dialog)
                    return
                self.view.after(
                    0, self.drop_conflicts_ready,
                    source_panel, target_panel, list(sources), destination,
                    copy_requested, conflicts, progress_dialog, cancel_event)

            self.app._submit_background("drop-conflicts", conflict_worker)
            return
        self.start_drop_transfer(
            source_panel, target_panel, sources, destination, copy_requested,
            progress_dialog, cancel_event)

    def drop_conflict_failed(self, source_panel, error, progress_dialog=None):
        source_panel.status.set("Transfer failed")
        if progress_dialog is not None:
            progress_dialog.fail(error)
        self.view.show_error("Transfer failed", error)

    def drop_conflicts_ready(
            self, source_panel, target_panel, sources, destination,
            copy_requested, conflicts, progress_dialog=None, cancel_event=None):
        if self.app._closing:
            if progress_dialog is not None:
                progress_dialog.complete()
            return
        if progress_dialog is not None and cancel_event is not None and cancel_event.is_set():
            progress_dialog.complete()
            source_panel.status.set("Copy cancelled")
            return
        if conflicts:
            self.view.confirm_action_async(
                "Overwrite?", self.format_conflict_message(conflicts),
                lambda accepted: self.continue_drop_after_overwrite(
                    bool(accepted), source_panel, target_panel, list(sources),
                    destination, copy_requested, progress_dialog, cancel_event))
            return
        self.start_drop_transfer(
            source_panel, target_panel, sources, destination, copy_requested,
            progress_dialog, cancel_event)

    @staticmethod
    def format_conflict_message(conflicts):
        return presentation.format_conflict_message(conflicts)

    def continue_drop_after_overwrite(
            self, accepted, source_panel, target_panel, sources, destination,
            copy_requested, progress_dialog=None, cancel_event=None):
        if not accepted:
            source_panel.status.set("Copy cancelled")
            if progress_dialog is not None:
                if cancel_event is not None:
                    cancel_event.set()
                progress_dialog.complete()
            return
        source_panel.status.set("Starting transfer...")
        self.view.after(
            self.app.POST_MODAL_TRANSFER_DELAY_MS,
            self.start_drop_transfer,
            source_panel, target_panel, list(sources), destination,
            copy_requested, progress_dialog, cancel_event)

    def start_drop_transfer(
            self, source_panel, target_panel, sources, destination,
            copy_requested, progress_dialog=None, cancel_event=None):
        cross_panel = source_panel.panel_id != target_panel.panel_id
        operation = "Copying" if cross_panel or copy_requested else "Moving"
        source_panel.status.set("{} {} item(s)...".format(operation, len(sources)))
        target_panel.status.set("Receiving {} item(s)...".format(len(sources)))
        if cancel_event is None:
            cancel_event = threading.Event()
        self.app.transfer_cancel = cancel_event
        progress_callback = None
        if cross_panel:
            if progress_dialog is None:
                transfer_name = "Upload" if source_panel.panel_id == "local" else "Download"
                progress_dialog = self.view.show_transfer_progress(
                    transfer_name, cancel_event,
                    items=[source.name for source in sources])
            last_update = [0.0]

            def progress_callback(name, current_done, current_total, overall_done, overall_total):
                now = time.monotonic()
                if now - last_update[0] < 0.1 and overall_done < overall_total:
                    return
                last_update[0] = now
                self.view.after(
                    0, progress_dialog.update_progress, name, current_done,
                    current_total, overall_done, overall_total)

        def transfer():
            try:
                if source_panel.panel_id == "local" and target_panel.panel_id == "local":
                    self.model.transfer(sources, Path(destination), move=not copy_requested)
                elif source_panel.panel_id == "local" and target_panel.panel_id == "server":
                    self.server.upload(
                        sources, destination, move=False, cancel=cancel_event,
                        progress=progress_callback)
                elif source_panel.panel_id == "server" and target_panel.panel_id == "local":
                    local_destination = Path(destination)
                    local_destination.mkdir(parents=True, exist_ok=True)
                    self.server.download(
                        sources, local_destination, move=False,
                        cancel=cancel_event, progress=progress_callback)
                else:
                    self.server.transfer(
                        sources, destination, move=not copy_requested,
                        cancel=cancel_event)
            except Exception as exc:
                self.view.after(
                    0, lambda error=str(exc), dialog=progress_dialog:
                    self.transfer_failed(error, dialog))
                return
            self.view.after(0, self.transfer_succeeded, progress_dialog)

        self.app._submit_transfer("file-transfer", transfer, cancel_event=cancel_event)

    def cross_panel_conflicts(self, target_panel, sources, destination):
        names = [source.name if hasattr(source, "name") else Path(source).name for source in sources]
        if target_panel.panel_id == "server":
            remote_destination = self.server.normalize(destination)
            existing = {item.name for item in self.server.list_directory(remote_destination)}
            return [name for name in names if name in existing]
        local_destination = Path(destination)
        with os.scandir(str(local_destination)) as entries:
            existing = {entry.name for entry in entries}
        if os.name == "nt":
            existing_folded = {name.casefold() for name in existing}
            return [name for name in names if name.casefold() in existing_folded]
        return [name for name in names if name in existing]

    def drop_target(self, x_root, y_root):
        panel, point = self.view.panel_and_point_at(x_root, y_root)
        if not panel:
            return None, None, None
        return panel, panel.drop_destination_at(point[0], point[1]), point

    def drop_is_valid(self, source_panel, target_panel, sources, destination):
        if not target_panel or destination is None or not sources:
            return False
        if target_panel.panel_id == "server" and not self.server.connected:
            return False
        if source_panel.panel_id != target_panel.panel_id:
            return True
        if source_panel.panel_id == "server":
            normalized_sources = [self.server.normalize(source) for source in sources]
            normalized_destination = self.server.normalize(destination)
        else:
            normalized_sources = [self.model.normalize(source) for source in sources]
            normalized_destination = self.model.normalize(destination)
        for source in normalized_sources:
            if source == normalized_destination or source.parent == normalized_destination:
                return False
            try:
                normalized_destination.relative_to(source)
            except ValueError:
                continue
            return False
        return True

    def transfer_failed(self, error, progress_dialog=None):
        if progress_dialog:
            progress_dialog.fail(error)
        self.app._refresh_all()
        if error == "Operation cancelled":
            return
        self.view.show_error("Transfer failed", error)

    def transfer_succeeded(self, progress_dialog=None):
        if progress_dialog:
            progress_dialog.complete()
        self.app._refresh_all()
