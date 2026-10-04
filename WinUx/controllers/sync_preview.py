"""Current-directory comparison and sync-preview orchestration."""
from __future__ import annotations

from pathlib import Path, PurePosixPath


class SyncPreviewController:
    """Own scans and transfer routing while the app remains a callback facade."""

    def __init__(self, app):
        self.app = app
        self._generation = 0
        self._connection_generation = None

    @property
    def view(self):
        return self.app.view

    @property
    def server(self):
        return self.app.server

    @property
    def model(self):
        return self.app.model

    @staticmethod
    def item_fields(item):
        return {
            "name": str(getattr(item, "name", "") or ""),
            "is_dir": bool(getattr(item, "is_dir", False)),
            "size": int(getattr(item, "size", 0) or 0),
            "mtime": float(
                getattr(item, "modified", getattr(item, "mtime", 0.0)) or 0.0),
            "path": getattr(item, "path", None),
        }

    @classmethod
    def build_rows(cls, local_items, server_items, local_root, server_root):
        def index(items):
            result = {}
            for item in items:
                if getattr(item, "name", None):
                    fields = cls.item_fields(item)
                    result[fields["name"]] = fields
            return result

        local = index(local_items)
        server = index(server_items)
        local_root = Path(local_root)
        server_root = PurePosixPath(server_root)
        rows = []
        for name in sorted(set(local) | set(server), key=str.casefold):
            left = local.get(name)
            right = server.get(name)
            if (left and left["is_dir"]) or (right and right["is_dir"]):
                # Phase 1 synchronization intentionally compares files only;
                # recursively synchronizing directories needs a separate scan
                # policy and explicit delete semantics.
                continue
            if left is None:
                rows.append({
                    "name": name, "status": "Missing locally",
                    "local_exists": False, "server_exists": True,
                    "local_size": 0, "server_size": right["size"],
                    "action": "Download",
                    "local_path": str(local_root / name),
                    "server_path": str(server_root / name),
                })
                continue
            if right is None:
                rows.append({
                    "name": name, "status": "Missing on server",
                    "local_exists": True, "server_exists": False,
                    "local_size": left["size"], "server_size": 0,
                    "action": "Upload",
                    "local_path": str(local_root / name),
                    "server_path": str(server_root / name),
                })
                continue
            time_delta = left["mtime"] - right["mtime"]
            if left["size"] == right["size"] and abs(time_delta) <= 2.0:
                continue
            if abs(time_delta) > 2.0:
                if time_delta > 0:
                    status, action = "Local is newer", "Upload"
                else:
                    status, action = "Server is newer", "Download"
            elif left["size"] != right["size"]:
                status, action = "Different size", "Review"
            else:
                status, action = "Different metadata", "Review"
            rows.append({
                "name": name, "status": status,
                "local_exists": True, "server_exists": True,
                "local_size": left["size"], "server_size": right["size"],
                "action": action,
                "local_path": str(local_root / name),
                "server_path": str(server_root / name),
            })
        return rows

    def preview(self):
        self._generation += 1
        generation = self._generation
        if self.app._closing or not self.app._ensure_server_online():
            return
        self._connection_generation = getattr(self.app, "_connection_generation", None)
        local_root = Path(self.view.left.current_path)
        server_root = self.server.normalize(self.view.right.current_path)
        existing = getattr(self.view, "sync_preview_dialog", None)
        if existing is not None and existing.winfo_exists():
            existing.set_status("Scanning Local and Server folders...")

        def worker():
            if not self._scan_is_current(generation):
                return
            try:
                local_items = list(self.model.list_directory(local_root))
                if not self._scan_is_current(generation):
                    return
                server_items = list(self.server.list_directory(server_root))
                if not self._scan_is_current(generation):
                    return
                rows = self.build_rows(
                    local_items, server_items, local_root, server_root)
            except Exception as exc:
                self.view.after(
                    0, self._scan_failed,
                    generation, local_root, server_root, str(exc))
                return
            self.view.after(
                0, self._scan_ready,
                generation, rows, local_root, server_root)

        self.app._submit_background(
            "sync-preview", worker, key="sync-preview", replace=True)

    def _scan_is_current(self, generation):
        return (
            generation == self._generation
            and not self.app._closing
            and getattr(self.app, "_connection_generation", None) == self._connection_generation
        )

    def _can_publish(self, generation, local_root, server_root):
        return (
            self._scan_is_current(generation)
            and self.view.winfo_exists()
            and self.server.connected
            and Path(self.view.left.current_path) == local_root
            and self.server.normalize(self.view.right.current_path) == server_root
        )

    def _scan_ready(self, generation, rows, local_root, server_root):
        if self._can_publish(generation, local_root, server_root):
            self.app._sync_preview_ready(rows, local_root, server_root)

    def _scan_failed(self, generation, local_root, server_root, error):
        if self._can_publish(generation, local_root, server_root):
            self.view.show_error("Directory Synchronization", error)

    def ready(self, rows, local_root, server_root):
        self.app._sync_local_root = Path(local_root)
        self.app._sync_server_root = self.server.normalize(server_root)
        self.view.show_sync_preview(
            rows, local_root, server_root,
            self.app.sync_preview, self.app._sync_transfer_rows)

    def transfer_rows(self, rows):
        if not self.app._ensure_server_online():
            return
        uploads = [Path(row["local_path"]) for row in rows
                   if row.get("action") == "Upload"]
        downloads = [self.server.normalize(row["server_path"]) for row in rows
                     if row.get("action") == "Download"]
        if not uploads and not downloads:
            dialog = getattr(self.view, "sync_preview_dialog", None)
            if dialog is not None and dialog.winfo_exists():
                dialog.set_status("Selected rows require review; no automatic action was started.")
            return
        if uploads and downloads:
            self.view.show_message(
                "Directory Synchronization",
                "The current selection contains both Upload and Download actions.\n\n"
                "Select one direction at a time so overwrite confirmations and transfer "
                "progress remain deterministic.")
            return
        if uploads:
            self.app._process_queued_drop(
                self.view.left, self.view.right,
                getattr(self.app, "_sync_server_root", self.view.right.current_path),
                True, uploads)
        if downloads:
            self.app._process_queued_drop(
                self.view.right, self.view.left,
                getattr(self.app, "_sync_local_root", self.view.left.current_path),
                True, downloads)
        dialog = getattr(self.view, "sync_preview_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.set_status(
                "Started {} upload{} and {} download{}. Refresh after transfers finish.".format(
                    len(uploads), "" if len(uploads) == 1 else "s",
                    len(downloads), "" if len(downloads) == 1 else "s"))

