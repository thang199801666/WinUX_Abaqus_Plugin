"""Read-only updater diagnostics shared by Settings and support tooling.

The module is deliberately standard-library only. It never contacts GitHub or
S:, never mutates installation state, and can therefore be used while WinUx is
running or while an update provider is unavailable.
"""
from __future__ import print_function

import os
import tempfile

from winux_installation_state import (
    install_root,
    load_quarantine,
    load_state,
    load_transaction,
    valid_deployment,
    version_dir,
    versions_root,
)
from winux_update_manifest import read_version


def _text(value):
    try:
        text_type = unicode  # noqa: F821
    except NameError:
        text_type = str
    try:
        return text_type(value)
    except Exception:
        return str(value)


def _human_bytes(value):
    value = float(value or 0)
    units = ("B", "KB", "MB", "GB")
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return "{:.0f} {}".format(value, unit) if unit == "B" else "{:.1f} {}".format(value, unit)
        value /= 1024.0


def _default_cache_dir(environ):
    root = environ.get("LOCALAPPDATA") or environ.get("APPDATA") or tempfile.gettempdir()
    return os.path.join(root, "WinUx", "cache", "updates")


def _default_log_path(environ):
    root = environ.get("LOCALAPPDATA") or environ.get("APPDATA") or tempfile.gettempdir()
    return os.path.join(root, "WinUx", "logs", "winux_update.log")


def installed_versions(environ=None):
    environ = os.environ if environ is None else environ
    root = versions_root(environ)
    result = []
    if not os.path.isdir(root):
        return result
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        version = read_version(path) or name
        result.append({
            "version": _text(version),
            "path": os.path.abspath(path),
            "valid": bool(valid_deployment(path, expected_version=version)),
        })
    result.sort(key=lambda item: item["version"], reverse=True)
    return result


def cache_summary(environ=None, cache_dir=None):
    environ = os.environ if environ is None else environ
    cache_dir = os.path.abspath(cache_dir or _default_cache_dir(environ))
    packages = []
    partials = []
    total = 0
    if os.path.isdir(cache_dir):
        for name in os.listdir(cache_dir):
            path = os.path.join(cache_dir, name)
            if not os.path.isfile(path):
                continue
            try:
                size = int(os.path.getsize(path))
                mtime = float(os.path.getmtime(path))
            except OSError:
                continue
            total += size
            item = {"name": name, "path": path, "size": size, "mtime": mtime}
            if name.lower().endswith(".partial"):
                partials.append(item)
            elif name.lower().endswith(".zip"):
                packages.append(item)
    return {
        "path": cache_dir,
        "packages": packages,
        "partials": partials,
        "bytes": total,
        "display_size": _human_bytes(total),
    }


def collect_update_diagnostics(environ=None, fallback_dir=None):
    environ = os.environ if environ is None else environ
    state = load_state(environ)
    active = _text(state.get("active_version") or "").strip() or None
    active_path = version_dir(active, environ) if active else None
    fallback_version = read_version(fallback_dir) if fallback_dir else None
    return {
        "install_root": install_root(environ),
        "active_version": active,
        "active_path": active_path,
        "active_valid": bool(active_path and valid_deployment(active_path, active)),
        "previous_versions": list(state.get("previous_versions") or []),
        "installed_versions": installed_versions(environ),
        "quarantine": load_quarantine(environ),
        "transaction": load_transaction(environ),
        "cache": cache_summary(environ),
        "fallback_version": fallback_version,
        "fallback_dir": os.path.abspath(fallback_dir) if fallback_dir else None,
        "update_log": _default_log_path(environ),
    }


def format_update_diagnostics(snapshot):
    snapshot = snapshot or {}
    active = snapshot.get("active_version") or "Flat/bundled deployment"
    previous = snapshot.get("previous_versions") or []
    installed = snapshot.get("installed_versions") or []
    quarantine = snapshot.get("quarantine") or {}
    transaction = snapshot.get("transaction") or {}
    cache = snapshot.get("cache") or {}

    lines = ["Active: {}".format(active)]
    if previous:
        lines.append("Previous known-good: {}".format(", ".join(previous)))
    else:
        lines.append("Previous known-good: none")
    if installed:
        labels = []
        for item in installed:
            label = item.get("version") or "unknown"
            if not item.get("valid"):
                label += " (invalid)"
            labels.append(label)
        lines.append("Installed versions: {}".format(", ".join(labels)))
    else:
        lines.append("Installed versions: none (using bundled/legacy layout)")
    if quarantine:
        labels = []
        for version in sorted(quarantine):
            entry = quarantine.get(version) or {}
            when = entry.get("quarantined_at") or "unknown time"
            labels.append("{} ({})".format(version, when))
        lines.append("Quarantined: {}".format(", ".join(labels)))
    else:
        lines.append("Quarantined: none")
    if transaction:
        lines.append("Transaction: {} -> {} ({})".format(
            transaction.get("previous_version") or "?",
            transaction.get("target_version") or "?",
            transaction.get("status") or "unknown",
        ))
    else:
        lines.append("Transaction: none")
    lines.append("Update cache: {} ({} package(s), {} partial)".format(
        cache.get("display_size") or "0 B",
        len(cache.get("packages") or []),
        len(cache.get("partials") or []),
    ))
    return "\n".join(lines)


__all__ = [
    "cache_summary",
    "collect_update_diagnostics",
    "format_update_diagnostics",
    "installed_versions",
]
