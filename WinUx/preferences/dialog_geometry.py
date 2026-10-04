"""Persistent geometry for native WinUX dialogs.

Qt's ``QWidget::saveGeometry``/``restoreGeometry`` keeps tool dialogs where the
user left them while still protecting against an unplugged monitor.  WinUX's
native Tk/QDialog compatibility layer stores the same small set of values in a
per-user JSON file and lets the platform host perform monitor-aware clamping.
"""

from __future__ import annotations

from .storage import JsonPreferenceStore


class DialogGeometryPreferences:
    """Store one normal-window rectangle per native dialog controller."""

    def __init__(self, root=None):
        self._store = JsonPreferenceStore("dialog_geometry.json", root=root)
        self.path = self._store.path

    @staticmethod
    def _clean_geometry(value):
        if not isinstance(value, dict):
            return None
        result = {}
        for key in ("x", "y", "width", "height"):
            try:
                result[key] = int(value[key])
            except (KeyError, TypeError, ValueError):
                return None
        state = str(value.get("state") or "normal").strip().lower()
        result["state"] = "zoomed" if state == "zoomed" else "normal"
        return result

    def load(self, key):
        key = str(key or "").strip()
        if not key:
            return None
        data = self._store.load()
        dialogs = data.get("dialogs", {}) if isinstance(data, dict) else {}
        if not isinstance(dialogs, dict):
            return None
        return self._clean_geometry(dialogs.get(key))

    def save(self, key, geometry):
        key = str(key or "").strip()
        cleaned = self._clean_geometry(geometry)
        if not key or cleaned is None:
            return False
        data = self._store.load()
        dialogs = data.get("dialogs")
        if not isinstance(dialogs, dict):
            dialogs = {}
        dialogs[key] = cleaned
        data["dialogs"] = dialogs
        return self._store.save(data, suppress_errors=True)

    def remove(self, key):
        key = str(key or "").strip()
        if not key:
            return False
        data = self._store.load()
        dialogs = data.get("dialogs")
        if not isinstance(dialogs, dict) or key not in dialogs:
            return False
        dialogs.pop(key, None)
        data["dialogs"] = dialogs
        return self._store.save(data, suppress_errors=True)


__all__ = ["DialogGeometryPreferences"]
