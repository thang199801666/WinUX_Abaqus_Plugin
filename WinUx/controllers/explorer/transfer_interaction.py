"""Explorer-facing drag/drop interaction for the WinUX controller facade."""
from __future__ import annotations

import threading
import math
from pathlib import Path

from ...diagnostics import log_event
from ...services import presentation, windows_shell_dragdrop


class ExplorerTransferInteractionMixin:
    """Own drag-session state, Windows Explorer handoff and drop queueing.

    Transfer execution and conflict resolution remain owned by
    :class:`TransferController`; this mixin only translates pointer/native-shell
    interactions into those existing operations.
    """

    def drag_start(self, _source_panel):
        """Begin a fresh drag session and discard any previous target."""
        self._drag_target_panel = None
        self._drag_target_destination = None
        self._drag_target_point = None
        self._drag_source_panel = _source_panel
        paths = getattr(_source_panel, 'drag_transfer_paths', None)
        self._drag_source_paths = tuple(paths() if callable(paths) else
                                        _source_panel.selected_transfer_paths())
        self._drag_connection_generation = getattr(self, '_connection_generation', None)
        self._drag_highlight_panel = None
        self._drag_feedback_key = None
        self._drag_feedback_valid = False
        for panel in self.view.panels:
            panel.clear_external_drop_highlight()
        prepare = getattr(self.view, "_prewarm_transfer_center", None)
        if callable(prepare):
            # Reuse an existing retained shell without hiding active transfers.
            # The view defers cold construction while a live drag owns input.
            self.view.after(0, prepare)

    def external_drop_missed(self, target_panel):
        """Show a concise hint when an Explorer drop misses a file pane."""
        if getattr(target_panel, "panel_id", None) == "server":
            target_panel.status.set(
                "Drop Explorer files inside the Server pane to upload")
        else:
            target_panel.status.set(
                "Drop Explorer files inside the Local pane to copy")

    def shell_drag(self, source_panel, dragged_items, owner_hwnd=None):
        """Hand a Local selection to Windows Explorer as a native Shell drag."""
        if getattr(source_panel, "panel_id", None) != "local":
            return windows_shell_dragdrop.DROPEFFECT_NONE
        paths = []
        for item in list(dragged_items or []):
            try:
                if getattr(item, "data", {}).get("parent"):
                    continue
                value = getattr(item, "data", {}).get("path") or item.path
                path = Path(value)
            except Exception:
                continue
            if path.exists():
                paths.append(path)
        if not paths:
            source_panel.status.set("Nothing to drag to Windows Explorer")
            return windows_shell_dragdrop.DROPEFFECT_NONE

        source_panel.status.set(
            "Dragging {} item(s) to Windows Explorer...".format(len(paths)))
        try:
            effect = windows_shell_dragdrop.drag_files(paths, owner_hwnd)
        except Exception as exc:
            source_panel.status.set("Windows Explorer drag failed")
            self.view.show_error("Drag to Windows Explorer", str(exc))
            return windows_shell_dragdrop.DROPEFFECT_NONE

        # Explorer owns the actual copy/move. Refresh because a same-volume
        # MOVE can remove the source files from the Local folder.
        self._refresh_all()
        if effect == windows_shell_dragdrop.DROPEFFECT_MOVE:
            source_panel.status.set(
                "Moved {} item(s) with Windows Explorer".format(len(paths)))
        elif effect in (
                windows_shell_dragdrop.DROPEFFECT_COPY,
                windows_shell_dragdrop.DROPEFFECT_LINK):
            source_panel.status.set(
                "Dropped {} item(s) in Windows Explorer".format(len(paths)))
        else:
            source_panel.status.set("Windows Explorer drag cancelled")
        return effect

    def _external_drop_to_local(self, target_panel, sources, destination):
        """Copy Explorer filesystem items into the Local pane off the UI thread."""
        target_panel.status.set(
            "Copying {} item(s) from Windows Explorer...".format(len(sources)))

        def worker():
            try:
                if any(not path.exists() for path in sources):
                    raise FileNotFoundError("Dropped file is no longer available")
                self.model.transfer(
                    list(sources), Path(destination), move=False)
            except Exception as exc:
                self.view.after(
                    0, self._external_local_drop_failed,
                    target_panel, str(exc))
                return
            self.view.after(
                0, self._external_local_drop_finished,
                target_panel, len(sources))

        self._submit_background("explorer-local-drop", worker)

    def _external_local_drop_failed(self, target_panel, error):
        target_panel.status.set("Copy from Windows Explorer failed")
        self.view.show_error("Windows Explorer drop", error)
        self._refresh_all()

    def _external_local_drop_finished(self, target_panel, count):
        self._refresh_all()
        target_panel.status.set(
            "Copied {} item(s) from Windows Explorer".format(int(count)))

    def external_drop(self, target_panel, paths, x=None, y=None):
        """Accept Windows Explorer files in either Local or Server pane."""
        log_event("external_drop: {} path(s) on {}".format(
            len(paths or []), getattr(target_panel, "panel_id", "?")))
        if not paths:
            return
        sources = [Path(path) for path in paths]

        destination = target_panel.current_path
        if x is not None and y is not None:
            try:
                destination = target_panel.drop_destination_at(
                    float(x), float(y))
            except Exception:
                destination = target_panel.current_path

        if target_panel.panel_id == "local":
            self._external_drop_to_local(target_panel, sources, destination)
            return

        if target_panel.panel_id != "server":
            return
        if not self.server.connected:
            target_panel.status.set("SSH server is not connected")
            return
        target_panel.status.set(
            "Uploading {} item(s) from Windows Explorer...".format(
                len(sources)))
        cancel_event = threading.Event()
        self.transfer_cancel = cancel_event
        progress_dialog = self.view.show_transfer_progress(
            "Upload", cancel_event,
            items=[source.name for source in sources])
        self.view.after(
            0, self._process_queued_drop, self.view.left, target_panel,
            destination, True, sources, progress_dialog, cancel_event)

    def drag_motion(self, source_panel, x_root, y_root):
        target_panel, destination, target_point = self._drop_target(
            x_root, y_root)
        if getattr(self, '_drag_source_panel', None) is not source_panel:
            self._drag_source_panel = source_panel
            self._drag_source_paths = tuple(source_panel.drag_transfer_paths())
            self._drag_connection_generation = getattr(self, '_connection_generation', None)
            self._drag_feedback_key = None

        key = (id(target_panel), str(destination),
               getattr(self, '_connection_generation', None), bool(self.server.connected))
        if key != getattr(self, '_drag_feedback_key', None):
            self._drag_feedback_key = key
            self._drag_feedback_valid = False
            changed_connection = (
                getattr(self, '_drag_connection_generation', None) !=
                getattr(self, '_connection_generation', None) and
                (source_panel.panel_id == 'server' or
                 getattr(target_panel, 'panel_id', None) == 'server'))
            if not changed_connection:
                self._drag_feedback_valid = self._drop_is_valid(
                    source_panel, target_panel, self._drag_source_paths, destination)
        valid = self._drag_feedback_valid

        if valid:
            self._drag_target_panel = target_panel
            self._drag_target_destination = destination
            self._drag_target_point = (float(x_root), float(y_root))
        else:
            self._drag_target_panel = None
            self._drag_target_destination = None
            self._drag_target_point = None

        highlight_panel = target_panel if valid and target_panel is not source_panel else None
        previous = getattr(self, '_drag_highlight_panel', None)
        if previous is not None and previous is not highlight_panel:
            previous.clear_external_drop_highlight()
        self._drag_highlight_panel = highlight_panel
        if highlight_panel is not None:
            highlight_panel.set_external_drop_highlight_at(
                target_point[0], target_point[1], True)
        return self._destination_display_name(destination) if valid else False

    @staticmethod
    def _destination_display_name(destination):
        """Return the exact folder label shown by the drag preview."""
        return presentation.destination_display_name(destination)

    def drop(self, source_panel, x_root, y_root, copy_requested,
             dragged_items=None):
        """Queue a completed drag for processing after mouse release."""
        for panel in self.view.panels:
            panel.clear_external_drop_highlight()
        snapshot = (getattr(self, '_drag_source_paths', None)
                    if getattr(self, '_drag_source_panel', None) is source_panel else None)
        connection_generation = getattr(self, '_drag_connection_generation', None)
        self._drag_source_panel = None
        self._drag_source_paths = None
        self._drag_highlight_panel = None
        self._drag_feedback_key = None
        self._drag_target_panel = None
        self._drag_target_destination = None
        self._drag_target_point = None

        if dragged_items is not None:
            raw_sources = [
                item.data.get("path") or item.path
                for item in list(dragged_items)
                if not item.data.get("parent")
            ]
        elif snapshot is not None:
            raw_sources = list(snapshot)
        else:
            raw_sources = list(source_panel.selected_transfer_paths())
        if not raw_sources:
            source_panel.status.set("Drop cancelled: no files selected")
            return

        try:
            x_root, y_root = float(x_root), float(y_root)
        except (TypeError, ValueError, OverflowError):
            return
        # Only the release position authorizes a destination. Hover feedback
        # can be stale after returning to the source pane, and an unresolved
        # drop must never silently turn into an upload/download to the opposite
        # pane. Negative desktop coordinates are valid on secondary monitors.
        if (not math.isfinite(x_root) or not math.isfinite(y_root)
                or (x_root == 0.0 and y_root == 0.0)):
            return
        target_panel, destination, _target_point = self._drop_target(x_root, y_root)
        if target_panel is None or destination is None:
            return
        if (snapshot is not None and
                (source_panel.panel_id == 'server' or target_panel.panel_id == 'server') and
                connection_generation != getattr(self, '_connection_generation', None)):
            source_panel.status.set('Drop cancelled: SSH connection changed during drag')
            return

        # Explorer semantics: dropping a selection back into the same folder
        # is a silent no-op.  The destination has already been classified as
        # invalid by drop_is_valid(), so do not enqueue transfer work merely to
        # show an "invalid destination" warning.  Explicit Copy/Paste remains
        # separate and is still allowed to create an Explorer-style duplicate.
        if not self._drop_is_valid(
                source_panel, target_panel, list(raw_sources), destination):
            return

        self.view.after(
            0,
            self._process_queued_drop,
            source_panel,
            target_panel,
            destination,
            bool(copy_requested),
            list(raw_sources),
        )
