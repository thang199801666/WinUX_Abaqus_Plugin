"""Transfer, synchronization and drag/drop execution facade methods."""
from __future__ import annotations



def _record_user_activity(controller):
    method = getattr(controller, "user_activity", None)
    if callable(method):
        return method()
    from ..controller import WinUXController
    return WinUXController.user_activity(controller)


class TransferFacadeMixin:
    def _sync_preview_controller(self):
        component = getattr(self, "_sync_preview", None)
        if component is None:
            from ...controllers.transfer.sync_preview import SyncPreviewController
            component = SyncPreviewController(self)
            self._sync_preview = component
        return component
    @staticmethod
    def _sync_item_fields(item):
        from ...controllers.transfer.sync_preview import SyncPreviewController
        return SyncPreviewController.item_fields(item)
    @classmethod
    def _build_sync_rows(cls, local_items, server_items, local_root, server_root):
        from ...controllers.transfer.sync_preview import SyncPreviewController
        return SyncPreviewController.build_rows(
            local_items, server_items, local_root, server_root)
    def sync_preview(self):
        _record_user_activity(self)
        return self._sync_preview_controller().preview()
    def _sync_preview_ready(self, rows, local_root, server_root):
        return self._sync_preview_controller().ready(rows, local_root, server_root)
    def _sync_transfer_rows(self, rows):
        _record_user_activity(self)
        return self._sync_preview_controller().transfer_rows(rows)
    def _clipboard_transfer_controller(self):
        component = getattr(self, "_clipboard_transfer", None)
        if component is None:
            from ...controllers.transfer.clipboard import ClipboardTransferController
            component = ClipboardTransferController(self)
            self._clipboard_transfer = component
        return component
    def _start_clipboard_transfer(self, target_panel, source_panel_id, sources, move, internal, source_sequence):
        return self._clipboard_transfer_controller().start(target_panel, source_panel_id, sources, move, internal, source_sequence)
    def _clipboard_transfer_failed(self, target_panel, progress_dialog, error):
        return self._clipboard_transfer_controller().failed(target_panel, progress_dialog, error)
    def _clipboard_transfer_finished(self, target_panel, progress_dialog, move, internal, source_sequence):
        return self._clipboard_transfer_controller().finished(target_panel, progress_dialog, move, internal, source_sequence)
    def transfer_selected(self, source_panel, paths=None):
        return self._transfer_controller().transfer_selected(source_panel, paths)
    def quick_transfer(self, source_panel, extension):
        return self._transfer_controller().quick_transfer(source_panel, extension)
    def _quick_transfer_conflict_failed(self, source_panel, error):
        return self._transfer_controller().quick_conflict_failed(source_panel, error)
    def _quick_transfer_conflicts_ready(
            self, source_panel, target_panel, sources, destination,
            extension, action, conflicts):
        return self._transfer_controller().quick_conflicts_ready(
            source_panel, target_panel, sources, destination,
            extension, action, conflicts)
    def _continue_quick_transfer_after_overwrite(
            self, accepted, source_panel, target_panel, sources, destination,
            extension, action):
        return self._transfer_controller().continue_quick_after_overwrite(
            accepted, source_panel, target_panel, sources, destination,
            extension, action)
    def _start_quick_transfer(
            self, source_panel, target_panel, sources, destination,
            extension, action):
        return self._transfer_controller().start_quick_transfer(
            source_panel, target_panel, sources, destination,
            extension, action)
    def _opposite_panel(self, source_panel):
        return self._transfer_controller().opposite_panel(source_panel)
    def _process_queued_drop(
            self, source_panel, target_panel, destination, copy_requested,
            raw_sources, progress_dialog=None, cancel_event=None):
        return self._transfer_controller().process_queued_drop(
            source_panel, target_panel, destination, copy_requested,
            raw_sources, progress_dialog, cancel_event)
    def _drop_conflict_failed(self, source_panel, error, progress_dialog=None):
        return self._transfer_controller().drop_conflict_failed(
            source_panel, error, progress_dialog)
    def _drop_conflicts_ready(
            self, source_panel, target_panel, sources, destination,
            copy_requested, conflicts, progress_dialog=None,
            cancel_event=None):
        return self._transfer_controller().drop_conflicts_ready(
            source_panel, target_panel, sources, destination, copy_requested,
            conflicts, progress_dialog, cancel_event)
    @staticmethod
    def _format_conflict_message(conflicts):
        from ...controllers.transfer.controller import TransferController
        return TransferController.format_conflict_message(conflicts)
    def _continue_drop_after_overwrite(
            self, accepted, source_panel, target_panel, sources, destination,
            copy_requested, progress_dialog=None, cancel_event=None):
        return self._transfer_controller().continue_drop_after_overwrite(
            accepted, source_panel, target_panel, sources, destination,
            copy_requested, progress_dialog, cancel_event)
    def _start_drop_transfer(
            self, source_panel, target_panel, sources, destination,
            copy_requested, progress_dialog=None, cancel_event=None):
        return self._transfer_controller().start_drop_transfer(
            source_panel, target_panel, sources, destination, copy_requested,
            progress_dialog, cancel_event)
    def _cross_panel_conflicts(self, target_panel, sources, destination):
        return self._transfer_controller().cross_panel_conflicts(
            target_panel, sources, destination)
    def _drop_target(self, x_root, y_root):
        return self._transfer_controller().drop_target(x_root, y_root)
    def _drop_is_valid(self, source_panel, target_panel, sources, destination):
        return self._transfer_controller().drop_is_valid(
            source_panel, target_panel, sources, destination)
    def _transfer_failed(self, error, progress_dialog=None):
        return self._transfer_controller().transfer_failed(error, progress_dialog)
    def _transfer_succeeded(self, progress_dialog=None):
        return self._transfer_controller().transfer_succeeded(progress_dialog)
