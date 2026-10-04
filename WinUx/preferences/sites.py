"""Named SSH site profiles used by the WinUx Site Manager."""

from __future__ import annotations

from .storage import JsonPreferenceStore


class SitePreferences:
    """Persist non-secret connection profiles.

    Passwords remain owned by :class:`LoginPreferences` and DPAPI.  A site
    profile only stores the host/port/user and preferred initial remote folder,
    so copying ``sites.json`` can never expose a credential.
    """

    MAX_SITES = 80

    def __init__(self, root=None):
        self._store = JsonPreferenceStore("sites.json", root=root)
        self.path = self._store.path

    def load(self):
        data = self._store.load()
        raw = data.get("sites", []) if isinstance(data, dict) else []
        result = []
        for index, item in enumerate(raw if isinstance(raw, list) else []):
            if not isinstance(item, dict):
                continue
            host = str(item.get("host") or "").strip()
            username = str(item.get("username") or "").strip()
            if not host:
                continue
            try:
                port = int(item.get("port", 22))
            except (TypeError, ValueError):
                port = 22
            if not 1 <= port <= 65535:
                port = 22
            name = str(item.get("name") or "").strip()
            if not name:
                name = "{}@{}".format(username, host) if username else host
            result.append({
                "id": str(item.get("id") or "site-{}".format(index + 1)),
                "name": name,
                "host": host,
                "port": port,
                "username": username,
                "remote_path": str(item.get("remote_path") or "").strip(),
            })
        return result

    def save_site(self, site):
        site = dict(site or {})
        host = str(site.get("host") or "").strip()
        if not host:
            raise ValueError("Host is required")
        try:
            port = int(site.get("port", 22))
        except (TypeError, ValueError):
            raise ValueError("Port must be a number from 1 to 65535")
        if not 1 <= port <= 65535:
            raise ValueError("Port must be a number from 1 to 65535")
        username = str(site.get("username") or "").strip()
        name = str(site.get("name") or "").strip()
        if not name:
            name = "{}@{}".format(username, host) if username else host
        remote_path = str(site.get("remote_path") or "").strip()
        site_id = str(site.get("id") or "").strip()

        values = self.load()
        if not site_id:
            used = {item["id"] for item in values}
            number = 1
            while "site-{}".format(number) in used:
                number += 1
            site_id = "site-{}".format(number)
        normalized = {
            "id": site_id,
            "name": name,
            "host": host,
            "port": port,
            "username": username,
            "remote_path": remote_path,
        }
        replaced = False
        output = []
        for item in values:
            if item["id"] == site_id:
                output.append(normalized)
                replaced = True
            else:
                output.append(item)
        if not replaced:
            output.append(normalized)
        self._store.save({"sites": output[-self.MAX_SITES:]}, suppress_errors=True)
        return normalized

    def delete(self, site_id):
        site_id = str(site_id or "")
        values = [item for item in self.load() if item["id"] != site_id]
        self._store.save({"sites": values}, suppress_errors=True)

    def clear(self):
        self._store.clear()
