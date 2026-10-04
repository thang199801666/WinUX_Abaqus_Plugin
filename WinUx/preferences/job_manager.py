"""Persistent last-used choices for the Abaqus Job Manager."""

from __future__ import annotations

from .storage import JsonPreferenceStore


class JobManagerPreferences:
    def __init__(self, root=None):
        self._store = JsonPreferenceStore("job_manager.json", root=root)
        self.path = self._store.path

    def load(self):
        return self._store.load()

    def save(self, version, cpus, precision, overwrite):
        data = {
            "version": str(version).strip(),
            "cpus": int(cpus),
            "precision": str(precision),
            "overwrite": bool(overwrite),
        }
        self._store.save(data, suppress_errors=True)
