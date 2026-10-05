"""Self-updating WinUx bootstrap store.

The Abaqus plug-in file is intentionally a tiny stable shim.  Bootstrap Python
modules live in a per-user immutable store and can be advanced independently of
that shim after a verified application update.  A broken bootstrap never blocks
WinUx: the shim falls back to a previous bootstrap or its bundled copy.
"""
from __future__ import print_function

import hashlib
import json
import os
import shutil
import tempfile

BOOTSTRAP_SCHEMA_VERSION = 1
BOOTSTRAP_STATE_FILENAME = "current.json"
DEFAULT_KEEP_PREVIOUS = 2
BOOTSTRAP_FILES = (
    "winux_launcher.py",
    "winux_updater.py",
    "winux_update_providers.py",
    "winux_update_manifest.py",
    "winux_update_lock.py",
    "winux_update_ui.py",
    "winux_update_installer.py",
    "winux_installation_state.py",
    "winux_bootstrap_state.py",
    "winux_health_check.py",
    "run_winux.py",
    "VERSION",
)
REQUIRED_BOOTSTRAP_FILES = (
    "winux_launcher.py",
    "winux_updater.py",
    "winux_installation_state.py",
    "run_winux.py",
    "VERSION",
)


def _text(value):
    try:
        text_type = unicode  # noqa: F821
    except NameError:
        text_type = str
    try:
        return text_type(value)
    except Exception:
        return str(value)


def _base(environ=None):
    environ = os.environ if environ is None else environ
    return os.path.join(
        os.path.abspath(environ.get("LOCALAPPDATA") or environ.get("APPDATA") or tempfile.gettempdir()),
        "WinUx", "bootstrap",
    )


def versions_root(environ=None):
    return os.path.join(_base(environ), "versions")


def state_path(environ=None):
    return os.path.join(_base(environ), "state", BOOTSTRAP_STATE_FILENAME)


def _version_name(version):
    value = _text(version or "").strip()
    safe = "".join(ch if ch.isalnum() or ch in "._+-" else "_" for ch in value)
    if not safe or safe in (".", ".."):
        raise ValueError("Invalid bootstrap version: {}".format(version))
    return safe


def version_dir(version, environ=None):
    return os.path.join(versions_root(environ), _version_name(version))


def _read_json(path):
    try:
        with open(path, "r") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _atomic_json(path, payload):
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    temp_path = path + ".tmp-{}".format(os.getpid())
    with open(temp_path, "w") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
    os.rename(temp_path, path)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def valid_bootstrap(path, expected_version=None):
    if not path or not os.path.isdir(path):
        return False
    for name in REQUIRED_BOOTSTRAP_FILES:
        if not os.path.isfile(os.path.join(path, name)):
            return False
    if expected_version is not None:
        try:
            with open(os.path.join(path, "VERSION"), "r") as handle:
                if handle.read().strip() != _text(expected_version).strip():
                    return False
        except Exception:
            return False
    return True


def load_state(environ=None):
    value = _read_json(state_path(environ))
    if int(value.get("schema_version", 0) or 0) != BOOTSTRAP_SCHEMA_VERSION:
        return {"schema_version": BOOTSTRAP_SCHEMA_VERSION, "active_version": None, "previous_versions": []}
    previous = value.get("previous_versions")
    value["previous_versions"] = previous if isinstance(previous, list) else []
    return value


def resolve_active_bootstrap(fallback_dir=None, environ=None):
    state = load_state(environ)
    candidates = []
    active = _text(state.get("active_version") or "").strip()
    if active:
        candidates.append((active, version_dir(active, environ)))
    for version in state.get("previous_versions", []):
        version = _text(version or "").strip()
        if version:
            candidates.append((version, version_dir(version, environ)))
    for version, path in candidates:
        if valid_bootstrap(path, version):
            return os.path.abspath(path)
    return os.path.abspath(fallback_dir) if valid_bootstrap(fallback_dir) else None


def _write_state(version, previous, environ=None):
    payload = {
        "schema_version": BOOTSTRAP_SCHEMA_VERSION,
        "active_version": _text(version),
        "previous_versions": list(previous),
    }
    _atomic_json(state_path(environ), payload)
    return payload


def install_from_deployment(deployment_dir, version, environ=None, keep_previous=DEFAULT_KEEP_PREVIOUS):
    """Copy verified bootstrap files from an already verified app deployment."""
    deployment_dir = os.path.abspath(deployment_dir)
    target = version_dir(version, environ)
    if valid_bootstrap(target, version):
        copied = False
    else:
        parent = versions_root(environ)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        stage = target + ".stage-{}".format(os.getpid())
        if os.path.exists(stage):
            shutil.rmtree(stage, ignore_errors=True)
        os.makedirs(stage)
        try:
            for name in BOOTSTRAP_FILES:
                source = os.path.join(deployment_dir, name)
                if not os.path.isfile(source):
                    if name in REQUIRED_BOOTSTRAP_FILES:
                        raise RuntimeError("Bootstrap source is missing {}".format(name))
                    continue
                destination = os.path.join(stage, name)
                shutil.copy2(source, destination)
                if _sha256(source) != _sha256(destination):
                    raise RuntimeError("Bootstrap copy verification failed: {}".format(name))
            if not valid_bootstrap(stage, version):
                raise RuntimeError("Staged WinUx bootstrap is incomplete.")
            if os.path.exists(target):
                shutil.rmtree(target, ignore_errors=True)
            os.rename(stage, target)
            copied = True
        finally:
            if os.path.exists(stage):
                shutil.rmtree(stage, ignore_errors=True)

    state = load_state(environ)
    old = _text(state.get("active_version") or "").strip()
    history = []
    if old and old != version:
        history.append(old)
    for item in state.get("previous_versions", []):
        item = _text(item or "").strip()
        if item and item != version and item not in history:
            history.append(item)
    history = history[:max(0, int(keep_previous))]
    _write_state(version, history, environ=environ)

    keep = set([_version_name(version)] + [_version_name(item) for item in history])
    root = versions_root(environ)
    try:
        for name in os.listdir(root):
            path = os.path.join(root, name)
            if name not in keep and os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass
    return {"version": version, "bootstrap_dir": target, "copied": copied}


__all__ = [
    "BOOTSTRAP_FILES", "DEFAULT_KEEP_PREVIOUS", "install_from_deployment",
    "load_state", "resolve_active_bootstrap", "state_path", "valid_bootstrap",
    "version_dir", "versions_root",
]
