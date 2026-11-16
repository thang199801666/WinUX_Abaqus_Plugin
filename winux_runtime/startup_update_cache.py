"""Small persistent cache for WinUx startup update discovery.

The cache exists only to keep Plug-ins -> WinUx launches off the network when
this exact deployed build was already confirmed current recently.  Explicit
Update Now / forced checks never use it, and changing VERSION/package_revision
invalidates it automatically.

Keep this module standard-library-only and Python-2/3 compatible because it is
imported by the ``abaqus python`` bootstrap before the application/vendor tree.
"""
from __future__ import print_function

import json
import os
import tempfile
import time


DEFAULT_STARTUP_UPDATE_CACHE_SECONDS = 6 * 60 * 60
CACHE_FILENAME = "startup_update_check.json"


def _text(value):
    try:
        text_type = unicode  # noqa: F821 - Python 2 only
    except NameError:
        text_type = str
    try:
        return text_type(value)
    except Exception:
        return str(value)


def _cache_path(environ=None):
    environ = os.environ if environ is None else environ
    root = (environ.get("LOCALAPPDATA") or environ.get("APPDATA")
            or tempfile.gettempdir())
    return os.path.join(os.path.abspath(root), "WinUx", "cache", CACHE_FILENAME)


def _settings_stamp(environ=None):
    environ = os.environ if environ is None else environ
    root = (environ.get("APPDATA") or environ.get("LOCALAPPDATA")
            or os.path.expanduser("~") or tempfile.gettempdir())
    path = os.path.join(os.path.abspath(root), "WinUX", "settings.json")
    try:
        stat = os.stat(path)
        return "{}:{}".format(int(stat.st_mtime), int(stat.st_size))
    except Exception:
        return "missing"


def _identity(project_dir, environ=None):
    environ = os.environ if environ is None else environ
    project_dir = os.path.abspath(project_dir)
    version = ""
    revision = -1
    manifest_version = ""
    package_sha256 = ""
    try:
        with open(os.path.join(project_dir, "VERSION"), "r") as handle:
            version = _text(handle.read()).strip()
    except Exception:
        pass
    try:
        with open(os.path.join(project_dir, "update_manifest.json"), "r") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            manifest_version = _text(payload.get("version", "")).strip()
            # A stale manifest belongs to another build and must not contribute
            # revision/hash identity to the startup update cache.
            if manifest_version == version and version:
                value = payload.get("package_revision", -1)
                if not isinstance(value, bool):
                    parsed_revision = int(value)
                    if parsed_revision >= 0:
                        revision = parsed_revision
                digest = _text(payload.get("package_sha256", "")).strip().lower()
                if len(digest) == 64 and all(ch in "0123456789abcdef" for ch in digest):
                    package_sha256 = digest
    except Exception:
        revision = -1
        package_sha256 = ""
    return {
        "project_dir": os.path.normcase(project_dir),
        "version": version,
        "manifest_version": manifest_version,
        "package_revision": revision,
        "package_sha256": package_sha256,
        "settings_stamp": _settings_stamp(environ),
        "update_provider_env": _text(environ.get("WINUX_UPDATE_PROVIDER", "")),
        "update_repository_env": _text(environ.get("WINUX_GITHUB_REPOSITORY", "")),
        "update_channel_env": _text(environ.get("WINUX_UPDATE_CHANNEL", "")),
        "update_api_base_env": _text(environ.get("WINUX_GITHUB_API_BASE", "")),
    }


def _ttl_seconds(environ=None):
    environ = os.environ if environ is None else environ
    raw = _text(environ.get("WINUX_STARTUP_UPDATE_CACHE_SECONDS", "")).strip()
    if not raw:
        return float(DEFAULT_STARTUP_UPDATE_CACHE_SECONDS)
    try:
        return max(0.0, float(raw))
    except Exception:
        return float(DEFAULT_STARTUP_UPDATE_CACHE_SECONDS)


def _forced(environ=None):
    environ = os.environ if environ is None else environ
    value = _text(environ.get("WINUX_FORCE_UPDATE_CHECK", "")).strip().lower()
    return value in ("1", "true", "yes", "on", "force")


def cached_startup_status(project_dir, environ=None, now=None):
    """Return a normalized no-update status when a fresh cache is reusable."""
    environ = os.environ if environ is None else environ
    if _forced(environ) or _ttl_seconds(environ) <= 0.0:
        return None
    # Explicit source overrides are administrative/development intent and must
    # never be hidden behind a prior automatic discovery result.
    if environ.get("WINUX_UPDATE_SOURCE"):
        return None
    path = _cache_path(environ)
    try:
        with open(path, "r") as handle:
            payload = json.load(handle)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    # Do not reuse historical shared-folder/S: discovery after the updater
    # migrated to GitHub-only normal launches.
    if _text(payload.get("provider") or "").strip().lower() == "folder":
        return None
    identity = _identity(project_dir, environ)
    for key in ("project_dir", "version", "manifest_version",
                "package_revision", "package_sha256", "settings_stamp",
                "update_provider_env", "update_repository_env",
                "update_channel_env", "update_api_base_env"):
        if payload.get(key) != identity.get(key):
            return None
    try:
        checked_at = float(payload.get("checked_at", 0.0))
    except Exception:
        return None
    current = time.time() if now is None else float(now)
    age = max(0.0, current - checked_at)
    if age > _ttl_seconds(environ):
        return None
    return {
        "local_dir": os.path.abspath(project_dir),
        "active_dir": os.path.abspath(project_dir),
        "local_version": identity.get("version"),
        "server_version": payload.get("server_version"),
        "provider": payload.get("provider"),
        "source_label": payload.get("source_label"),
        "available": False,
        "updated": False,
        "cancelled": False,
        "error": None,
        "cached": True,
        "cache_age_seconds": age,
        "reason": "recent startup update check reused",
    }


def _cacheable_status(status):
    if not isinstance(status, dict):
        return False
    if status.get("available") or status.get("updated") or status.get("cancelled"):
        return False
    if status.get("error") or status.get("manifest_error"):
        return False
    provider = _text(status.get("provider") or "").strip().lower()
    # Normal startup cache is GitHub-only; never preserve a legacy shared-drive
    # result that could mask GitHub discovery on a later launch.
    if provider == "folder":
        return False
    return bool(status.get("local_version"))


def record_startup_status(project_dir, status, environ=None, now=None):
    """Persist a successful no-update discovery for this exact deployment."""
    environ = os.environ if environ is None else environ
    if not _cacheable_status(status):
        return False
    payload = _identity(project_dir, environ)
    payload.update({
        "checked_at": time.time() if now is None else float(now),
        "provider": status.get("provider"),
        "source_label": status.get("source_label") or status.get("server_dir"),
        "server_version": status.get("server_version"),
    })
    path = _cache_path(environ)
    directory = os.path.dirname(path)
    temporary = path + ".tmp"
    try:
        if not os.path.isdir(directory):
            os.makedirs(directory)
        with open(temporary, "w") as handle:
            json.dump(payload, handle, sort_keys=True)
        if os.path.exists(path):
            os.remove(path)
        os.rename(temporary, path)
        return True
    except Exception:
        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except Exception:
            pass
        return False


def invalidate_startup_cache(environ=None):
    try:
        os.remove(_cache_path(environ))
        return True
    except OSError:
        return False


__all__ = [
    "DEFAULT_STARTUP_UPDATE_CACHE_SECONDS",
    "cached_startup_status",
    "record_startup_status",
    "invalidate_startup_cache",
]
