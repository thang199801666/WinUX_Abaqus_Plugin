"""Small, dependency-free JSON preference storage.

Feature-specific preference classes own validation and migration.  This module
only centralizes profile-path selection and atomic UTF-8 JSON persistence.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def user_profile_path(filename, root=None):
    """Return a per-user WinUX settings path.

    ``root`` is primarily useful for tests and portable deployments.  On
    Windows, roaming AppData remains compatible with the existing releases.
    """
    app_root = (
        root
        or os.environ.get("APPDATA")
        or os.environ.get("LOCALAPPDATA")
    )
    return Path(app_root or Path.home()) / "WinUX" / str(filename)


class JsonPreferenceStore:
    """Read and atomically replace one dictionary-shaped JSON document."""

    def __init__(self, filename=None, root=None, path=None):
        if path is None and filename is None:
            raise ValueError("filename or path is required")
        self.path = (
            Path(path)
            if path is not None
            else user_profile_path(filename, root=root)
        )

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, data, suppress_errors=False):
        if not isinstance(data, dict):
            raise TypeError("preference data must be a dictionary")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(data, indent=2),
                encoding="utf-8",
            )
            temporary.replace(self.path)
            return True
        except (OSError, TypeError, ValueError):
            if not suppress_errors:
                raise
            return False

    def clear(self):
        try:
            self.path.unlink()
            return True
        except FileNotFoundError:
            return False
