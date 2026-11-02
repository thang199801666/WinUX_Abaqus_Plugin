"""File transfer orchestration extracted from the application controller.

Pointer/drag routing remains in ``WinUXController``.  This component owns the
I/O-facing half of transfer commands: source/destination normalization,
conflict checks, overwrite continuation, progress wiring and completion.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from ...services import presentation
from ...runtime.transfer_progress import TransferProgressDelivery
from ...services.transfer.conflicts import ConflictDecision, ConflictReview, local_transfer_metadata
from ...services.transfer.tree import TreeDecision, TreeReview, TreeReader, scan_tree
from ...services.transfer.timestamps import timestamp_options


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

    def _attach_retry(self, dialog, source_panel, target_panel, sources, destination, review=None):
        if dialog is None or not callable(getattr(dialog, 'set_retry', None)):
            return
        if isinstance(review, TreeDecision) or (isinstance(review, ConflictDecision) and review.renames):
            # A generic Retry must never replay a renamed copy at the original
            # name. Require an explicit fresh review until retry stores maps.
            dialog.set_retry(None)
            return
        sources = tuple(sources)
        endpoint = (getattr(self.server, 'host', ''), getattr(self.server, '_port', 22),
                    getattr(self.server, 'username', ''))

        def retry(task):
            if self.app._closing:
                task.retry_ready()
                return
            def confirmed(accepted):
                if not accepted or self.app._closing or not task.winfo_exists():
                    task.retry_ready()
                    return
                current = (getattr(self.server, 'host', ''), getattr(self.server, '_port', 22),
                           getattr(self.server, 'username', ''))
                if current != endpoint:
                    task.retry_ready()
                    self.view.show_error('Retry transfer', 'The SSH site changed. Start a new transfer for this site.')
                    return
                if not self.app._ensure_server_online():
                    task.retry_ready()
                    return
                # Retry is an explicit new copy, never a byte-level resume or
                # a replay of a move. Re-run source and overwrite checks using
                # the frozen destination, not whichever folder is open now.
                self.process_queued_drop(source_panel, target_panel, destination, True, sources)
                task.center.remove_task(task)
            self.view.confirm_action_async(
                'Retry transfer',
                'Restart this upload/download batch from the beginning? Already completed files may be sent again. '
                'Existing destination names will be checked again before replacing anything.',
                confirmed, primary_text='Retry', secondary_text='Cancel')
        dialog.set_retry(retry)

    def _confirm_conflicts(self, conflicts, callback, *, source_panel=None,
                           target_panel=None, sources=None, destination=None, cancel_event=None):
        show_review = getattr(self.view, 'confirm_transfer_conflicts_async', None)
        if (callable(show_review) and callable(getattr(self.app, '_submit_background', None))
                and source_panel is not None and target_panel is not None):
            connection = getattr(self.app, '_connection_generation', None)
            sources = tuple(sources)
            def current():
                return (not self.app._closing and
                        connection == getattr(self.app, '_connection_generation', None) and
                        not (cancel_event is not None and cancel_event.is_set()))
            def failed(error):
                report_error = current()
                callback(False, False)
                if report_error and not self.app._closing:
                    self.view.show_error('Review transfer conflicts', str(error))
            def ready(review):
                if current():
                    show_review(review, callback, on_review_contents=lambda dialog: self._review_contents(
                        review, dialog, current))
                else:
                    callback(False, False)
            def worker():
                try:
                    if not current():
                        self.view.after(0, callback, False, False)
                        return
                    left, right = self._conflict_metadata(source_panel.panel_id, target_panel.panel_id,
                                                          sources, destination)
                    if not current():
                        self.view.after(0, callback, False, False)
                        return
                    for source in sources:
                        if left[str(source)] is None:
                            raise FileNotFoundError('Source is no longer available: {}'.format(source.name))
                    review = ConflictReview(sources, left, right, destination,
                                            source_panel.panel_id, target_panel.panel_id, connection)
                    self.view.after(0, ready, review)
                except Exception as exc:
                    self.view.after(0, failed, str(exc))
            handle = self.app._submit_background('transfer-conflict-metadata', worker)
            if getattr(handle, 'state', None) == 'rejected':
                failed('Background queue is full; try again.')
            return
        self.view.confirm_action_checkbox_async(
            'Existing destination items',
            self.format_conflict_message(conflicts) +
            '\n\nContinue replaces existing items. Select the option below to skip whole conflicting items instead (including folders).',
            callback, checkbox_text='Skip existing items instead of replacing',
            checkbox_checked=False, primary_text='Continue', intent='warning')

    def _review_contents(self, review, dialog, current):
        event, token = dialog.begin_contents_scan()
        def publish(result=None, error=None):
            if not dialog._finished and dialog.winfo_exists() and dialog._scan_token is token:
                if current() and not event.is_set():
                    dialog.finish_contents_scan(result, error)
                else:
                    dialog.finish_contents_scan(error='Scan cancelled or connection changed. Start again.')
        def worker():
            try:
                result = scan_tree(review, TreeReader(review.source_panel, self.server),
                    TreeReader(review.target_panel, self.server), cancel=event, current=current)
                self.view.after(0, publish, result)
            except Exception as exc:
                self.view.after(0, publish, None, str(exc))
        handle = self.app._submit_background('recursive-conflict-review', worker)
        if getattr(handle, 'state', None) == 'rejected':
            publish(error='Background queue is full; try again.')

    def _conflict_metadata(self, source_panel, target_panel, sources, destination, target_names=None):
        destination = self.server.normalize(destination) if target_panel == 'server' else Path(destination)
        snapshot_source = self.server.transfer_metadata if source_panel == 'server' else local_transfer_metadata
        snapshot_target = self.server.transfer_metadata if target_panel == 'server' else local_transfer_metadata
        names = target_names or {}
        targets = [destination / names.get(str(source), source.name) for source in sources]
        left = snapshot_source(sources)
        right = snapshot_target(targets)
        return left, {str(source): right[str(target)] for source, target in zip(sources, targets)}

    def _validate_conflict_review(self, review, sources, cancel_event=None):
        if review is None:
            return
        decision = review if isinstance(review, ConflictDecision) else None
        baseline = decision.review if decision else review
        if baseline.connection != getattr(self.app, '_connection_generation', None):
            raise RuntimeError('Server connection changed; start the transfer again')
        if isinstance(baseline, TreeReview):
            current = lambda: not self.app._closing and baseline.connection == getattr(self.app, '_connection_generation', None)
            target_reader = TreeReader(baseline.target_panel, self.server)
            fresh = scan_tree(baseline.original, TreeReader(baseline.source_panel, self.server),
                              target_reader, cancel=cancel_event, current=current, limits=baseline.limits)
            if not baseline.same_snapshot(fresh):
                raise RuntimeError('Folder contents changed after recursive review. Scan and confirm again.')
            for key, name in decision.renames:
                relative = baseline.relative_paths[key].with_name(name)
                if target_reader.stat(target_reader.path(baseline.destination).joinpath(*relative.parts)) is not None:
                    raise RuntimeError('A renamed destination already exists. Scan and confirm again.')
            if not current():
                raise RuntimeError('Server connection changed; start the transfer again')
            return
        options = {'target_names': decision.target_names} if decision and decision.renames else {}
        left, right = self._conflict_metadata(baseline.source_panel, baseline.target_panel, sources,
                                              baseline.destination, **options)
        if baseline.connection != getattr(self.app, '_connection_generation', None):
            raise RuntimeError('Server connection changed; start the transfer again')
        review.validate(sources, left, right)

    @staticmethod
    def _review_context(decision):
        return decision if isinstance(decision, TreeDecision) or decision.renames else decision.review

    @staticmethod
    def _target_options(review):
        if isinstance(review, TreeDecision):
            return {'tree_decision': review}
        return {'target_names': review.target_names} if isinstance(review, ConflictDecision) and review.renames else {}

    @staticmethod
    def _progress_names(sources, review):
        if isinstance(review, TreeDecision):
            return [review.review.display_name(source) for source in sources]
        return [source.name for source in sources]

    @staticmethod
    def _without_conflicts(sources, conflicts, target_panel):
        folded = target_panel.panel_id == 'local' and os.name == 'nt'
        names = {str(name).casefold() if folded else str(name) for name in conflicts}
        return [source for source in sources
                if (source.name.casefold() if folded else source.name) not in names]

    def _schedule_start(self, callback, *args, progress_dialog=None, after_modal=True):
        connection = getattr(self.app, '_connection_generation', None)
        def start():
            if connection != getattr(self.app, '_connection_generation', None):
                self.transfer_failed('Server connection changed; start the transfer again', progress_dialog)
                return
            if self.app._closing:
                return
            callback(*args)
        self.view.after(self.app.POST_MODAL_TRANSFER_DELAY_MS if after_modal else 0, start)

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
        connection = getattr(self.app, '_connection_generation', None)

        def conflict_worker():
            try:
                if connection != getattr(self.app, '_connection_generation', None):
                    raise RuntimeError('Server connection changed; start the transfer again')
                conflicts = self.cross_panel_conflicts(target_panel, sources, destination)
            except Exception as exc:
                self.view.after(0, self.quick_conflict_failed, source_panel, str(exc))
                return
            def ready():
                if connection != getattr(self.app, '_connection_generation', None):
                    self.quick_conflict_failed(source_panel, 'Server connection changed; start the transfer again')
                    return
                self.quick_conflicts_ready(source_panel, target_panel, sources, destination, extension, action, conflicts)
            self.view.after(0, ready)

        self.app._submit_background("quick-transfer-conflicts", conflict_worker)

    def quick_conflict_failed(self, source_panel, error):
        source_panel.status.set("Quick transfer failed")
        self.view.show_error("Quick transfer", error)

    def quick_conflicts_ready(
            self, source_panel, target_panel, sources, destination,
            extension, action, conflicts):
        connection = getattr(self.app, '_connection_generation', None)
        if conflicts:
            def resolved(accepted, skip):
                if self.app._closing:
                    return
                if connection != getattr(self.app, '_connection_generation', None):
                    self.quick_conflict_failed(source_panel, 'Server connection changed; start the transfer again')
                    return
                decision = skip if isinstance(skip, ConflictDecision) else None
                chosen = list(decision.sources) if decision else (
                    self._without_conflicts(sources, conflicts, target_panel) if skip else list(sources))
                if accepted and not chosen:
                    source_panel.status.set('No items match the selected overwrite policy; nothing transferred')
                    return
                self.continue_quick_after_overwrite(
                    bool(accepted), source_panel, target_panel, chosen, destination, extension, action,
                    review=self._review_context(decision) if decision else None)
            self._confirm_conflicts(conflicts, resolved, source_panel=source_panel, target_panel=target_panel,
                                    sources=sources, destination=destination)
            return
        source_panel.status.set("Starting quick {}...".format(action.lower()))
        self._schedule_start(
            self.start_quick_transfer,
            source_panel, target_panel, list(sources), destination,
            extension, action, after_modal=False)

    def continue_quick_after_overwrite(
            self, accepted, source_panel, target_panel, sources, destination,
            extension, action, review=None):
        if not accepted:
            source_panel.status.set("Quick {} cancelled".format(action.lower()))
            return
        source_panel.status.set("Starting quick {}...".format(action.lower()))
        self._schedule_start(
            self.start_quick_transfer,
            source_panel, target_panel, list(sources), destination,
            extension, action, review)

    def start_quick_transfer(
            self, source_panel, target_panel, sources, destination,
            extension, action, review=None):
        cancel_event = threading.Event()
        connection = getattr(self.app, '_connection_generation', None)
        self.app.transfer_cancel = cancel_event
        progress_dialog = self.view.show_transfer_progress(
            action, cancel_event, items=self._progress_names(sources, review))
        self._attach_retry(progress_dialog, source_panel, target_panel, sources, destination, review)
        source_panel.status.set(
            "Quick {}: {} *{} file(s)...".format(
                action.lower(), len(sources), extension))
        target_panel.status.set("Receiving {} item(s)...".format(len(sources)))
        delivery = TransferProgressDelivery(self.view.after, progress_dialog.update_progress)
        setter = getattr(progress_dialog, 'set_progress_delivery', None)
        if callable(setter):
            setter(delivery)
        progress = delivery.progress
        transfer_options = {**self._target_options(review), **timestamp_options(self.view)}

        def worker():
            try:
                if self.app._closing or cancel_event.is_set():
                    raise RuntimeError('Operation cancelled')
                if connection != getattr(self.app, '_connection_generation', None):
                    raise RuntimeError('Server connection changed; retry the transfer for the original SSH site')
                self._validate_conflict_review(review, sources, cancel_event)
                if self.app._closing or cancel_event.is_set():
                    raise RuntimeError('Operation cancelled')
                if source_panel.panel_id == "local":
                    self.server.upload(
                        sources, destination, cancel=cancel_event, progress=progress,
                        **transfer_options)
                else:
                    self.server.download(
                        sources, Path(destination), cancel=cancel_event, progress=progress,
                        **transfer_options)
            except Exception as exc:
                delivery.finish(self.transfer_failed, str(exc), progress_dialog)
                return
            delivery.finish(self.transfer_succeeded, progress_dialog)

        handle = self.app._submit_transfer("quick-transfer", worker, cancel_event=cancel_event)
        if getattr(handle, 'state', None) == 'rejected':
            delivery.close()
            self.transfer_failed('Transfer queue is full', progress_dialog)

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
            # Upload/Download commands supply an explicit target. A missing
            # drag destination is cancellation, not permission to use the other
            # pane (which could download a Server -> Server drop).
            source_panel.status.set("Drop cancelled: no destination")
            if progress_dialog is not None:
                if cancel_event is not None:
                    cancel_event.set()
                progress_dialog.complete()
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
            # Internal drag/drop within the same pane uses invalidity as a
            # normal "no operation" signal (same folder, self target, or a
            # recursive target).  Keep that interaction completely silent.
            # Copy/Paste does not use this path and therefore still supports
            # duplicating an item inside its current folder.
            if source_panel.panel_id == target_panel.panel_id:
                if progress_dialog is not None:
                    progress_dialog.complete()
                return
            source_panel.status.set("Drop cancelled: invalid destination")
            if progress_dialog is not None:
                progress_dialog.fail("Drop cancelled: invalid destination")
            return
        cross_panel = source_panel.panel_id != target_panel.panel_id
        if cross_panel:
            # Show feedback before remote directory/conflict checks, not after
            # a potentially slow network round trip or recursive transfer scan.
            if cancel_event is None:
                cancel_event = threading.Event()
            if progress_dialog is None:
                action = "Upload" if source_panel.panel_id == "local" else "Download"
                progress_dialog = self.view.show_transfer_progress(
                    action, cancel_event, items=[source.name for source in sources])
            self.app.transfer_cancel = cancel_event
            progress_dialog.set_preparing("Checking destination for existing files...")
            self._attach_retry(progress_dialog, source_panel, target_panel, sources, destination)
            source_panel.status.set("Checking destination for existing files...")
            connection = getattr(self.app, '_connection_generation', None)

            def conflict_worker():
                try:
                    if connection != getattr(self.app, '_connection_generation', None):
                        raise RuntimeError('Server connection changed; start the transfer again')
                    if cancel_event.is_set():
                        conflicts = []
                    else:
                        if source_panel.panel_id == "local" and any(not path.exists() for path in sources):
                            raise FileNotFoundError("Source file is no longer available")
                        conflicts = self.cross_panel_conflicts(target_panel, sources, destination)
                except Exception as exc:
                    self.view.after(
                        0, self.drop_conflict_failed,
                        source_panel, str(exc), progress_dialog)
                    return
                def ready():
                    if connection != getattr(self.app, '_connection_generation', None):
                        self.drop_conflict_failed(source_panel, 'Server connection changed; start the transfer again', progress_dialog)
                        return
                    self.drop_conflicts_ready(source_panel, target_panel, list(sources), destination,
                                              copy_requested, conflicts, progress_dialog, cancel_event)
                self.view.after(0, ready)

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
        connection = getattr(self.app, '_connection_generation', None)
        if self.app._closing:
            if progress_dialog is not None:
                progress_dialog.complete()
            return
        if progress_dialog is not None and cancel_event is not None and cancel_event.is_set():
            progress_dialog.complete()
            source_panel.status.set("Copy cancelled")
            return
        if conflicts:
            if progress_dialog is not None:
                progress_dialog.set_preparing("Waiting for overwrite confirmation...")
            def resolved(accepted, skip):
                if connection != getattr(self.app, '_connection_generation', None):
                    self.drop_conflict_failed(source_panel, 'Server connection changed; start the transfer again', progress_dialog)
                    return
                if self.app._closing or (cancel_event is not None and cancel_event.is_set()):
                    if progress_dialog is not None:
                        progress_dialog.complete()
                    source_panel.status.set('Copy cancelled')
                    return
                decision = skip if isinstance(skip, ConflictDecision) else None
                chosen = list(decision.sources) if decision else (
                    self._without_conflicts(sources, conflicts, target_panel) if skip else list(sources))
                if accepted and (skip is True or isinstance(decision, TreeDecision) or (decision and decision.policy != 'replace')):
                    # The preparing handle contains the original selection.
                    # Replace it so skipped files are never marked Completed.
                    if progress_dialog is not None:
                        progress_dialog.center.remove_task(progress_dialog)
                    if not chosen:
                        source_panel.status.set('No items match the selected overwrite policy; nothing transferred')
                        if progress_dialog is not None:
                            progress_dialog.center._hide_if_idle()
                        return
                    action = 'Upload' if source_panel.panel_id == 'local' else 'Download'
                    context = self._review_context(decision) if decision else None
                    replacement = self.view.show_transfer_progress(action, cancel_event, items=self._progress_names(chosen, context))
                else:
                    replacement = progress_dialog
                self.continue_drop_after_overwrite(
                    bool(accepted), source_panel, target_panel, chosen,
                    destination, copy_requested, replacement, cancel_event,
                    review=self._review_context(decision) if decision else None)
            self._confirm_conflicts(conflicts, resolved, source_panel=source_panel, target_panel=target_panel,
                                    sources=sources, destination=destination, cancel_event=cancel_event)
            return
        self.start_drop_transfer(
            source_panel, target_panel, sources, destination, copy_requested,
            progress_dialog, cancel_event)

    @staticmethod
    def format_conflict_message(conflicts):
        return presentation.format_conflict_message(conflicts)

    def continue_drop_after_overwrite(
            self, accepted, source_panel, target_panel, sources, destination,
            copy_requested, progress_dialog=None, cancel_event=None, review=None):
        if not accepted:
            source_panel.status.set("Copy cancelled")
            if progress_dialog is not None:
                if cancel_event is not None:
                    cancel_event.set()
                progress_dialog.complete()
            return
        source_panel.status.set("Starting transfer...")
        self._schedule_start(
            self.start_drop_transfer,
            source_panel, target_panel, list(sources), destination,
            copy_requested, progress_dialog, cancel_event, review, progress_dialog=progress_dialog)

    def start_drop_transfer(
            self, source_panel, target_panel, sources, destination,
            copy_requested, progress_dialog=None, cancel_event=None, review=None):
        cross_panel = source_panel.panel_id != target_panel.panel_id
        connection = getattr(self.app, '_connection_generation', None)
        operation = "Copying" if cross_panel or copy_requested else "Moving"
        source_panel.status.set("{} {} item(s)...".format(operation, len(sources)))
        target_panel.status.set("Receiving {} item(s)...".format(len(sources)))
        if cancel_event is None:
            cancel_event = threading.Event()
        self.app.transfer_cancel = cancel_event
        progress_callback = None
        delivery = None
        if cross_panel:
            if progress_dialog is None:
                transfer_name = "Upload" if source_panel.panel_id == "local" else "Download"
                progress_dialog = self.view.show_transfer_progress(
                    transfer_name, cancel_event,
                    items=self._progress_names(sources, review))
            progress_dialog.set_preparing("Preparing files for transfer...")
            self._attach_retry(progress_dialog, source_panel, target_panel, sources, destination, review)
            delivery = TransferProgressDelivery(self.view.after, progress_dialog.update_progress)
            setter = getattr(progress_dialog, 'set_progress_delivery', None)
            if callable(setter):
                setter(delivery)
            progress_callback = delivery.progress

        transfer_options = {**self._target_options(review), **timestamp_options(self.view)}

        def transfer():
            try:
                if self.app._closing or cancel_event.is_set():
                    raise RuntimeError('Operation cancelled')
                if (source_panel.panel_id == 'server' or target_panel.panel_id == 'server') and connection != getattr(self.app, '_connection_generation', None):
                    raise RuntimeError('Server connection changed; start the transfer again')
                self._validate_conflict_review(review, sources, cancel_event)
                if self.app._closing or cancel_event.is_set():
                    raise RuntimeError('Operation cancelled')
                if source_panel.panel_id == "local" and target_panel.panel_id == "local":
                    self.model.transfer(sources, Path(destination), move=not copy_requested)
                elif source_panel.panel_id == "local" and target_panel.panel_id == "server":
                    self.server.upload(
                        sources, destination, move=False, cancel=cancel_event,
                        progress=progress_callback, **transfer_options)
                elif source_panel.panel_id == "server" and target_panel.panel_id == "local":
                    local_destination = Path(destination)
                    local_destination.mkdir(parents=True, exist_ok=True)
                    self.server.download(
                        sources, local_destination, move=False,
                        cancel=cancel_event, progress=progress_callback, **transfer_options)
                else:
                    self.server.transfer(
                        sources, destination, move=not copy_requested,
                        cancel=cancel_event)
            except Exception as exc:
                if delivery is not None:
                    delivery.finish(self.transfer_failed, str(exc), progress_dialog)
                else:
                    self.view.after(0, self.transfer_failed, str(exc), progress_dialog)
                return
            if delivery is not None:
                delivery.finish(self.transfer_succeeded, progress_dialog)
            else:
                self.view.after(0, self.transfer_succeeded, progress_dialog)

        handle = self.app._submit_transfer("file-transfer", transfer, cancel_event=cancel_event)
        if getattr(handle, 'state', None) == 'rejected':
            if delivery is not None:
                delivery.close()
            self.transfer_failed('Transfer queue is full', progress_dialog)

    def cross_panel_conflicts(self, target_panel, sources, destination):
        names = [source.name if hasattr(source, "name") else Path(source).name for source in sources]
        if target_panel.panel_id == "server":
            remote_destination = self.server.normalize(destination)
            existing = set(self.server.list_directory_names(remote_destination))
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
        if ('server' in (source_panel.panel_id, target_panel.panel_id)
                and not self.server.connected):
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
