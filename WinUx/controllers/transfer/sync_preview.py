"""Current-directory comparison and sync-preview orchestration."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import math
import stat


class SyncPreviewController:
    """Own scans and transfer routing while the app remains a callback facade."""

    def __init__(self, app):
        self.app = app
        self._generation = 0
        self._connection_generation = None
        self._scan_dialog = None
        self._scan_pending = False

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
        size, mtime, known = 0, 0.0, True
        try:
            raw_size = getattr(item, 'size', None)
            raw_mtime = getattr(item, 'modified', getattr(item, 'mtime', None))
            if raw_size is None or raw_mtime is None:
                known = False
            else:
                size, mtime = int(raw_size), float(raw_mtime)
                known = size >= 0 and math.isfinite(mtime)
        except (TypeError, ValueError, OverflowError):
            known = False
        mode, attributes = getattr(item, 'mode', None), getattr(item, 'attributes', None)
        link = (bool(getattr(item, 'is_symlink', False)) or
                (isinstance(mode, int) and stat.S_ISLNK(mode)) or
                (isinstance(attributes, int) and bool(attributes & 0x400)))
        special = (isinstance(mode, int) and stat.S_IFMT(mode) != 0 and
                   not (stat.S_ISREG(mode) or stat.S_ISDIR(mode) or stat.S_ISLNK(mode)))
        return {
            "name": str(getattr(item, "name", "") or ""),
            "is_dir": bool(getattr(item, "is_dir", False)),
            "size": size if known else 0,
            "mtime": mtime if known else 0.0,
            "metadata_known": known,
            "kind": 'Link' if link else 'Special' if special else 'Folder' if bool(getattr(item, 'is_dir', False)) else 'File',
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
            present = [entry for entry in (left, right) if entry is not None]
            review_status = None
            if any(entry['kind'] in ('Link', 'Special') for entry in present):
                review_status = 'Link/special entry not compared'
            elif left and right and left['is_dir'] != right['is_dir']:
                review_status = 'File/folder conflict'
            elif any(entry['is_dir'] for entry in present):
                review_status = 'Directory not compared'
            elif not all(entry['metadata_known'] for entry in present):
                review_status = 'Incomplete metadata'
            if review_status is not None:
                rows.append({
                    'name': name, 'status': review_status,
                    'local_exists': left is not None, 'server_exists': right is not None,
                    'local_size': left['size'] if left else 0, 'server_size': right['size'] if right else 0,
                    'local_kind': left['kind'] if left else '', 'server_kind': right['kind'] if right else '',
                    'local_metadata_known': left['metadata_known'] if left else False,
                    'server_metadata_known': right['metadata_known'] if right else False,
                    'local_path': str(local_root / name), 'server_path': str(server_root / name),
                    'action': 'Review', 'transfer_allowed': False,
                })
                continue
            if left is None:
                rows.append({
                    "name": name, "status": "Missing locally",
                    "local_exists": False, "server_exists": True,
                    "local_size": 0, "server_size": right["size"],
                    "action": "Download", "transfer_allowed": True,
                    "local_path": str(local_root / name),
                    "server_path": str(server_root / name),
                })
                continue
            if right is None:
                rows.append({
                    "name": name, "status": "Missing on server",
                    "local_exists": True, "server_exists": False,
                    "local_size": left["size"], "server_size": 0,
                    "action": "Upload", "transfer_allowed": True,
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
                "action": action, "transfer_allowed": action in ('Upload', 'Download'),
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
        dialog = getattr(self.view, "sync_preview_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            dialog.lift()
        else:
            dialog = self.view.show_sync_preview(
                [], local_root, server_root, self.app.sync_preview, self.app._sync_transfer_rows)
        self._scan_dialog = dialog
        self._scan_pending = True
        dialog.begin_scan(local_root, server_root)

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

        def submit():
            if self._can_publish(generation, local_root, server_root):
                self.app._submit_background(
                    "sync-preview", worker, key="sync-preview", replace=True)

        # A fast scan/result must not fill a large table before the user has
        # seen its shell. Both in-process and native controllers expose this.
        dialog.after_first_present(submit)

    def _scan_is_current(self, generation):
        return (
            generation == self._generation
            and not self.app._closing
            and getattr(self.app, "_connection_generation", None) == self._connection_generation
        )

    def _can_publish(self, generation, local_root, server_root):
        if not self._scan_is_current(generation) or not self.view.winfo_exists():
            return False
        dialog = self._scan_dialog
        if dialog is not None:
            if (getattr(self.view, "sync_preview_dialog", None) is not dialog
                    or not dialog.winfo_exists()):
                return False
            visible = getattr(dialog, "isVisible", None)
            if not (visible() if callable(visible) else getattr(dialog, "_visible", False)):
                return False
        return (
            self.server.connected
            and Path(self.view.left.current_path) == local_root
            and self.server.normalize(self.view.right.current_path) == server_root
        )

    def _scan_ready(self, generation, rows, local_root, server_root):
        if self._can_publish(generation, local_root, server_root):
            self._scan_pending = False
            self.app._sync_preview_ready(rows, local_root, server_root)

    def _scan_failed(self, generation, local_root, server_root, error):
        if self._can_publish(generation, local_root, server_root):
            self._scan_dialog.set_status("Scan failed: {}. Refresh to retry.".format(error))
            self.view.show_error("Directory Synchronization", error)

    def ready(self, rows, local_root, server_root):
        self.app._sync_local_root = Path(local_root)
        self.app._sync_server_root = self.server.normalize(server_root)
        self.view.show_sync_preview(
            rows, local_root, server_root,
            self.app.sync_preview, self.app._sync_transfer_rows)

    def transfer_rows(self, rows):
        if self._scan_pending:
            dialog = getattr(self.view, "sync_preview_dialog", None)
            if dialog is not None and dialog.winfo_exists():
                dialog.set_status("Wait for the current scan to finish before transferring.")
            return
        transferable = [row for row in rows if row.get('transfer_allowed', True)
                        and row.get('action') in ('Upload', 'Download')]
        if not transferable:
            dialog = getattr(self.view, "sync_preview_dialog", None)
            if dialog is not None and dialog.winfo_exists():
                dialog.set_status("Selected rows require review; no automatic action was started.")
            return
        if not self.app._ensure_server_online():
            return
        uploads = [Path(row["local_path"]) for row in transferable if row.get("action") == "Upload"]
        downloads = [self.server.normalize(row["server_path"]) for row in transferable if row.get("action") == "Download"]
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
