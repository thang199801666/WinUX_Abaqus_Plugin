"""Persistent last-used folders for the local and SSH file panels."""

from __future__ import annotations

from .storage import JsonPreferenceStore


class NavigationPreferences:
    """Store navigation state without mixing it with encrypted credentials."""

    SORT_COLUMNS = ("#0", "type", "size", "modified")

    def __init__(self, root=None):
        self._store = JsonPreferenceStore("navigation.json", root=root)
        self.path = self._store.path

    def load_local(self):
        value = self._load().get("local")
        return str(value) if value else None

    def save_local(self, folder):
        data = self._load()
        data["local"] = str(folder)
        self._save(data)

    def load_server(self, host, username):
        value = self._load().get("servers", {}).get(self._server_key(host, username))
        return str(value) if value else None

    def save_server(self, host, username, folder):
        data = self._load()
        servers = data.setdefault("servers", {})
        servers[self._server_key(host, username)] = str(folder)
        self._save(data)


    def load_bookmarks(self, panel_id, host=None, username=None):
        """Return persisted navigation bookmarks for Local or one SSH site."""
        data = self._load().get("bookmarks", {})
        if str(panel_id) == "server":
            servers = data.get("servers", {}) if isinstance(data, dict) else {}
            values = servers.get(self._server_key(host or "", username or ""), [])
        else:
            values = data.get("local", []) if isinstance(data, dict) else []
        result = []
        for item in values if isinstance(values, list) else []:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            if not path:
                continue
            label = str(item.get("label") or path).strip() or path
            result.append({"label": label, "path": path})
        return result

    def add_bookmark(self, panel_id, path, label=None, host=None, username=None):
        """Add or update a bookmark, de-duplicated by exact path."""
        path = str(path or "").strip()
        if not path:
            return False
        label = str(label or "").strip() or path
        data = self._load()
        bookmarks = data.setdefault("bookmarks", {})
        if str(panel_id) == "server":
            servers = bookmarks.setdefault("servers", {})
            key = self._server_key(host or "", username or "")
            values = servers.setdefault(key, [])
        else:
            values = bookmarks.setdefault("local", [])
        if not isinstance(values, list):
            values = []
            if str(panel_id) == "server":
                bookmarks.setdefault("servers", {})[self._server_key(host or "", username or "")] = values
            else:
                bookmarks["local"] = values
        normalized = []
        found = False
        for item in values:
            if not isinstance(item, dict):
                continue
            current = str(item.get("path") or "")
            if current == path:
                normalized.append({"label": label, "path": path})
                found = True
            else:
                normalized.append({
                    "label": str(item.get("label") or current),
                    "path": current,
                })
        if not found:
            normalized.append({"label": label, "path": path})
        # Keep the feature bounded so a long-lived profile never makes the
        # manager slow or unwieldy.
        normalized = normalized[-80:]
        if str(panel_id) == "server":
            bookmarks.setdefault("servers", {})[self._server_key(host or "", username or "")] = normalized
        else:
            bookmarks["local"] = normalized
        self._save(data)
        return True

    def remove_bookmark(self, panel_id, path, host=None, username=None):
        path = str(path or "")
        data = self._load()
        bookmarks = data.setdefault("bookmarks", {})
        if str(panel_id) == "server":
            servers = bookmarks.setdefault("servers", {})
            key = self._server_key(host or "", username or "")
            values = servers.get(key, [])
            servers[key] = [
                item for item in values if isinstance(item, dict)
                and str(item.get("path") or "") != path
            ]
        else:
            values = bookmarks.get("local", [])
            bookmarks["local"] = [
                item for item in values if isinstance(item, dict)
                and str(item.get("path") or "") != path
            ]
        self._save(data)

    def rename_bookmark(self, panel_id, path, label, host=None, username=None):
        path = str(path or "")
        label = str(label or "").strip()
        if not path or not label:
            return False
        values = self.load_bookmarks(panel_id, host=host, username=username)
        if not any(item["path"] == path for item in values):
            return False
        return self.add_bookmark(
            panel_id, path, label=label, host=host, username=username)

    def load_sort(self, panel_id):
        """Return the saved ``(column, descending)`` state for one panel."""
        value = self._load().get("sort", {}).get(str(panel_id), {})
        column = value.get("column") if isinstance(value, dict) else None
        if column not in self.SORT_COLUMNS:
            return None
        return column, bool(value.get("descending", False))

    def save_sort(self, panel_id, column, descending):
        """Persist the active sort independently for Local and Server."""
        if column not in self.SORT_COLUMNS:
            return
        data = self._load()
        sort = data.setdefault("sort", {})
        sort[str(panel_id)] = {
            "column": column,
            "descending": bool(descending),
        }
        self._save(data)

    def _load(self):
        return self._store.load()

    def _save(self, data):
        # Navigation must continue even if the profile is read-only.
        self._store.save(data, suppress_errors=True)

    @staticmethod
    def _server_key(host, username):
        return "{}|{}".format(str(host).casefold(), str(username).casefold())
