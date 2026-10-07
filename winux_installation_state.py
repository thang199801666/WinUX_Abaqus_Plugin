"""Versioned WinUx installation state and crash-safe active-version selection.

This module is deliberately standard-library only and Python 2/3 compatible so
it can be imported by the Abaqus plug-in bootstrap before WinUx/vendor modules.

The historical flat plug-in folder remains a valid fallback deployment.  Once a
versioned update succeeds, the bootstrap can launch the active immutable copy
from ``<install-root>/versions/<version>`` while user data/settings stay outside
that managed tree.
"""
from __future__ import print_function

import datetime
import json
import os
import re
import shutil
import tempfile

from winux_update_manifest import read_version, required_files_present, compare_versions


STATE_SCHEMA_VERSION = 1
STATE_FILENAME = "current.json"
TRANSACTION_FILENAME = "transaction.json"
QUARANTINE_FILENAME = "quarantine.json"
DEFAULT_KEEP_PREVIOUS = 2
INSTALL_MODE_VERSIONED = "versioned"
INSTALL_MODE_LEGACY = "legacy"
INSTALL_MODE_KEY = "update_install_mode"


def _text(value):
    try:
        text_type = unicode  # noqa: F821 - Python 2 only
    except NameError:
        text_type = str
    try:
        return text_type(value)
    except Exception:
        return str(value)


def _utc_now():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _mkdir(path):
    if not os.path.isdir(path):
        try:
            os.makedirs(path)
        except OSError:
            if not os.path.isdir(path):
                raise
    return path


def _replace_file(temporary, target):
    replace = getattr(os, "replace", None)
    if replace is not None:
        replace(temporary, target)
        return
    if os.name == "nt":
        # Python 2 used by older Abaqus releases has no os.replace(). Use the
        # Win32 atomic replace primitive instead of delete+rename so current.json
        # is never observed half-written or temporarily absent.
        try:
            import ctypes
            MOVEFILE_REPLACE_EXISTING = 0x00000001
            MOVEFILE_WRITE_THROUGH = 0x00000008
            result = ctypes.windll.kernel32.MoveFileExW(
                _text(temporary), _text(target),
                MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
            )
            if not result:
                raise ctypes.WinError()
            return
        except Exception:
            # Last-resort compatibility path. A missing pointer is still safe
            # because launcher resolution falls back to the bundled deployment.
            pass
    if os.path.exists(target):
        os.remove(target)
    os.rename(temporary, target)


def _atomic_json(path, payload):
    directory = _mkdir(os.path.dirname(os.path.abspath(path)))
    temporary = os.path.join(directory, ".{}.{}.tmp".format(os.path.basename(path), os.getpid()))
    raw = json.dumps(payload, indent=2, sort_keys=True)
    if not isinstance(raw, bytes):
        raw = raw.encode("utf-8")
    with open(temporary, "wb") as handle:
        handle.write(raw)
        handle.write(b"\n")
        try:
            handle.flush()
            os.fsync(handle.fileno())
        except Exception:
            pass
    _replace_file(temporary, path)
    return path


def _read_json(path):
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
        if not raw:
            return None
        try:
            raw = raw.decode("utf-8")
        except AttributeError:
            pass
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except (IOError, OSError, ValueError, TypeError):
        return None


def normalize_install_mode(value, platform_name=None):
    platform_name = os.name if platform_name is None else platform_name
    if value is None or not _text(value).strip():
        # Production Windows launches get the crash-safe versioned store by
        # default. Portable/Linux test runs keep the historical flat installer
        # unless they explicitly exercise versioned mode.
        return INSTALL_MODE_VERSIONED if platform_name == "nt" else INSTALL_MODE_LEGACY
    value = _text(value).strip().lower()
    aliases = {
        "managed": INSTALL_MODE_VERSIONED,
        "atomic": INSTALL_MODE_VERSIONED,
        "versions": INSTALL_MODE_VERSIONED,
        "flat": INSTALL_MODE_LEGACY,
        "in-place": INSTALL_MODE_LEGACY,
        "inplace": INSTALL_MODE_LEGACY,
    }
    value = aliases.get(value, value)
    if value not in (INSTALL_MODE_VERSIONED, INSTALL_MODE_LEGACY):
        raise ValueError("Unsupported WinUx install mode: {}".format(value))
    return value


def install_mode(settings=None, environ=None, platform_name=None):
    settings = settings if isinstance(settings, dict) else {}
    environ = os.environ if environ is None else environ
    explicit = environ.get("WINUX_INSTALL_MODE")
    if explicit is None:
        explicit = settings.get(INSTALL_MODE_KEY)
    return normalize_install_mode(explicit, platform_name=platform_name)


def versioned_install_enabled(settings=None, environ=None, platform_name=None):
    return install_mode(settings, environ, platform_name) == INSTALL_MODE_VERSIONED


def install_root(environ=None):
    environ = os.environ if environ is None else environ
    explicit = environ.get("WINUX_INSTALL_ROOT")
    if explicit:
        return os.path.abspath(os.path.expanduser(os.path.expandvars(_text(explicit))))
    base = (
        environ.get("LOCALAPPDATA")
        or environ.get("APPDATA")
        or tempfile.gettempdir()
    )
    return os.path.join(os.path.abspath(base), "WinUx", "runtime")


def versions_root(environ=None):
    return os.path.join(install_root(environ), "versions")


def state_root(environ=None):
    return os.path.join(install_root(environ), "state")


def state_path(environ=None):
    return os.path.join(state_root(environ), STATE_FILENAME)


def transaction_path(environ=None):
    return os.path.join(state_root(environ), TRANSACTION_FILENAME)


def quarantine_path(environ=None):
    return os.path.join(state_root(environ), QUARANTINE_FILENAME)


def _version_folder_name(version):
    value = _text(version or "").strip()
    if not value:
        raise ValueError("WinUx version is missing.")
    # Semantic versions only need dots/dashes/plus, but sanitize defensively so
    # release metadata can never escape the versions root.
    safe = re.sub(r"[^A-Za-z0-9._+-]", "_", value)
    if safe in ("", ".", ".."):
        raise ValueError("Invalid WinUx version folder name: {}".format(version))
    return safe


def version_dir(version, environ=None):
    return os.path.join(versions_root(environ), _version_folder_name(version))


def valid_deployment(path, expected_version=None):
    if not path or not os.path.isdir(path):
        return False
    version = read_version(path)
    if not version:
        return False
    if expected_version is not None and _text(version) != _text(expected_version):
        return False
    return required_files_present(path)


def load_transaction(environ=None):
    """Return the current update transaction journal, if one exists."""
    payload = _read_json(transaction_path(environ))
    return payload if isinstance(payload, dict) else {}


def load_state(environ=None):
    payload = _read_json(state_path(environ)) or {}
    if int(payload.get("schema_version", 0) or 0) != STATE_SCHEMA_VERSION:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "active_version": None,
            "previous_versions": [],
        }
    previous = payload.get("previous_versions")
    if not isinstance(previous, list):
        previous = []
    result = dict(payload)
    result["previous_versions"] = [_text(item) for item in previous if _text(item).strip()]
    return result



def load_quarantine(environ=None):
    payload = _read_json(quarantine_path(environ)) or {}
    entries = payload.get("entries")
    return entries if isinstance(entries, dict) else {}


def is_quarantined(version, package_sha256=None, environ=None):
    version = _text(version or "").strip()
    if not version:
        return False
    entry = load_quarantine(environ).get(version)
    if not isinstance(entry, dict):
        return False
    recorded = _text(entry.get("package_sha256") or "").strip().lower()
    current = _text(package_sha256 or "").strip().lower()
    # A republished package with a different checksum is eligible for retry.
    if current and recorded and current != recorded:
        return False
    return True


def quarantine_version(version, package_sha256=None, reason=None, environ=None):
    version = _text(version or "").strip()
    if not version:
        return None
    entries = load_quarantine(environ)
    entries[version] = {
        "package_sha256": _text(package_sha256 or "").strip().lower(),
        "reason": _text(reason or "candidate failed verification/health check"),
        "quarantined_at": _utc_now(),
    }
    payload = {"schema_version": STATE_SCHEMA_VERSION, "entries": entries, "updated_at": _utc_now()}
    _atomic_json(quarantine_path(environ), payload)
    return entries[version]


def clear_quarantine(version=None, environ=None):
    path = quarantine_path(environ)
    if version is None:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
        return True
    version = _text(version or "").strip()
    entries = load_quarantine(environ)
    if version not in entries:
        return False
    entries.pop(version, None)
    if entries:
        _atomic_json(path, {"schema_version": STATE_SCHEMA_VERSION, "entries": entries, "updated_at": _utc_now()})
    else:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
    return True

def write_state(active_version, previous_versions=None, environ=None, reason=None):
    active_version = _text(active_version).strip()
    if not active_version:
        raise ValueError("Active WinUx version is required.")
    history = []
    for item in previous_versions or []:
        item = _text(item).strip()
        if item and item != active_version and item not in history:
            history.append(item)
    payload = {
        "schema_version": STATE_SCHEMA_VERSION,
        "active_version": active_version,
        "previous_versions": history,
        "updated_at": _utc_now(),
    }
    if reason:
        payload["reason"] = _text(reason)
    _atomic_json(state_path(environ), payload)
    return payload


def begin_transaction(previous_version, target_version, target_dir, source_label=None, environ=None):
    payload = {
        "schema_version": STATE_SCHEMA_VERSION,
        "status": "preparing",
        "previous_version": _text(previous_version or ""),
        "target_version": _text(target_version or ""),
        "target_dir": os.path.abspath(target_dir),
        "source": _text(source_label or ""),
        "started_at": _utc_now(),
    }
    _atomic_json(transaction_path(environ), payload)
    return payload


def update_transaction(status, environ=None, **values):
    payload = _read_json(transaction_path(environ)) or {
        "schema_version": STATE_SCHEMA_VERSION,
        "started_at": _utc_now(),
    }
    payload["status"] = _text(status)
    payload["updated_at"] = _utc_now()
    for key, value in values.items():
        payload[key] = value
    _atomic_json(transaction_path(environ), payload)
    return payload


def clear_transaction(environ=None):
    path = transaction_path(environ)
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def activate_version(version, environ=None, keep_previous=DEFAULT_KEEP_PREVIOUS, reason="update"):
    version = _text(version).strip()
    target = version_dir(version, environ)
    if not valid_deployment(target, expected_version=version):
        raise RuntimeError("Cannot activate incomplete WinUx version: {}".format(target))

    state = load_state(environ)
    old_active = _text(state.get("active_version") or "").strip()
    history = []
    if old_active and old_active != version:
        history.append(old_active)
    for item in state.get("previous_versions", []):
        if item and item != version and item not in history:
            history.append(item)
    keep_previous = max(0, int(keep_previous))
    history = history[:keep_previous]
    return write_state(version, history, environ=environ, reason=reason)


def _recover_from_history(state, environ=None):
    for version in state.get("previous_versions", []):
        candidate = version_dir(version, environ)
        if valid_deployment(candidate, expected_version=version):
            remaining = [item for item in state.get("previous_versions", []) if item != version]
            write_state(version, remaining, environ=environ, reason="automatic rollback")
            return candidate
    return None


def recover_interrupted_transaction(environ=None):
    """Resolve stale transaction metadata without risking the last good build."""
    transaction = _read_json(transaction_path(environ))
    if not transaction:
        return None
    status = _text(transaction.get("status") or "")
    target_version = _text(transaction.get("target_version") or "").strip()
    target_dir = transaction.get("target_dir") or (version_dir(target_version, environ) if target_version else None)
    state = load_state(environ)
    active = _text(state.get("active_version") or "").strip()

    # If activation completed before the process died, the state pointer is the
    # source of truth. A valid active target means the transaction can be
    # committed/cleared on the next launch.
    if target_version and active == target_version and valid_deployment(target_dir, target_version):
        clear_transaction(environ)
        return "committed"

    # Any pre-activation crash leaves the old state pointer untouched. Remove a
    # partial target only when it cannot be validated; a fully verified copy is
    # harmless and may be reused by a later retry.
    if target_dir and os.path.exists(target_dir) and not valid_deployment(target_dir, target_version or None):
        try:
            if os.path.isdir(target_dir) and not os.path.islink(target_dir):
                shutil.rmtree(target_dir)
            else:
                os.remove(target_dir)
        except Exception:
            pass
    clear_transaction(environ)
    return status or "recovered"


def resolve_active_installation(fallback_dir=None, environ=None, recover=True):
    """Return a valid active version, automatically rolling back if necessary.

    ``fallback_dir`` is the historical flat plug-in deployment. It remains a
    first-class compatibility path for users that have not yet completed a
    versioned update or intentionally force ``WINUX_INSTALL_MODE=legacy``.
    """
    if recover:
        try:
            recover_interrupted_transaction(environ)
        except Exception:
            # State recovery must never prevent the bundled fallback from
            # launching; invalid pointers are handled below.
            pass
    state = load_state(environ)
    active = _text(state.get("active_version") or "").strip()
    fallback_valid = valid_deployment(fallback_dir)
    fallback_version = read_version(fallback_dir) if fallback_valid else None
    if active:
        candidate = version_dir(active, environ)
        if valid_deployment(candidate, expected_version=active):
            # A newer bundled release (for example a locally deployed hotfix)
            # must not be hidden behind an older immutable LocalAppData cache.
            # Older or same-version bundled trees still defer to the managed
            # active deployment, preserving normal production update behavior.
            try:
                if fallback_version and compare_versions(fallback_version, active) > 0:
                    return os.path.abspath(fallback_dir)
            except (TypeError, ValueError):
                pass
            return candidate
        recovered = _recover_from_history(state, environ)
        if recovered:
            try:
                recovered_version = read_version(recovered)
                if (fallback_version and recovered_version and
                        compare_versions(fallback_version, recovered_version) > 0):
                    return os.path.abspath(fallback_dir)
            except (TypeError, ValueError):
                pass
            return recovered
    if fallback_valid:
        return os.path.abspath(fallback_dir)
    return None


def cleanup_versions(environ=None, keep_previous=DEFAULT_KEEP_PREVIOUS):
    """Remove unmanaged old version directories after a successful activation."""
    root = versions_root(environ)
    if not os.path.isdir(root):
        return []
    state = load_state(environ)
    keep = set()
    active = _text(state.get("active_version") or "").strip()
    if active:
        keep.add(_version_folder_name(active))
    for version in state.get("previous_versions", [])[:max(0, int(keep_previous))]:
        keep.add(_version_folder_name(version))
    removed = []
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if name in keep or not os.path.isdir(path):
            continue
        try:
            shutil.rmtree(path)
            removed.append(path)
        except Exception:
            pass
    return removed


__all__ = [
    "DEFAULT_KEEP_PREVIOUS",
    "INSTALL_MODE_KEY",
    "INSTALL_MODE_LEGACY",
    "INSTALL_MODE_VERSIONED",
    "activate_version",
    "begin_transaction",
    "cleanup_versions",
    "clear_quarantine",
    "clear_transaction",
    "install_mode",
    "install_root",
    "load_state",
    "load_transaction",
    "load_quarantine",
    "is_quarantined",
    "quarantine_version",
    "quarantine_path",
    "normalize_install_mode",
    "recover_interrupted_transaction",
    "resolve_active_installation",
    "state_path",
    "transaction_path",
    "update_transaction",
    "valid_deployment",
    "version_dir",
    "versioned_install_enabled",
    "versions_root",
    "write_state",
]
