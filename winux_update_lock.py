"""Cross-process update lock for the WinUx local deployment."""
from __future__ import print_function

import datetime
import hashlib
import json
import os
import shutil
import tempfile
import time


DEFAULT_STALE_SECONDS = 30 * 60


class UpdateInProgress(RuntimeError):
    pass


def _lock_root(environ=None):
    environ = os.environ if environ is None else environ
    root = environ.get("LOCALAPPDATA") or environ.get("APPDATA") or tempfile.gettempdir()
    return os.path.join(root, "WinUx", "locks")


def _deployment_key(local_dir):
    value = os.path.normcase(os.path.abspath(local_dir))
    raw = value.encode("utf-8") if not isinstance(value, bytes) else value
    return hashlib.sha1(raw).hexdigest()[:20]


def lock_path_for(local_dir, environ=None):
    return os.path.join(_lock_root(environ), _deployment_key(local_dir) + ".lock")


def _ensure_directory(path):
    if os.path.isdir(path):
        return
    try:
        os.makedirs(path)
    except OSError:
        if not os.path.isdir(path):
            raise


def _remove_lock(path):
    try:
        shutil.rmtree(path)
    except OSError:
        if os.path.exists(path):
            raise


def _is_stale(path, stale_seconds):
    try:
        age = time.time() - os.path.getmtime(path)
    except OSError:
        return True
    return age > float(stale_seconds)


class UpdateLock(object):
    def __init__(self, local_dir, environ=None, stale_seconds=DEFAULT_STALE_SECONDS):
        self.local_dir = os.path.abspath(local_dir)
        self.environ = os.environ if environ is None else environ
        self.stale_seconds = stale_seconds
        self.path = lock_path_for(self.local_dir, self.environ)
        self.acquired = False

    def acquire(self):
        parent = os.path.dirname(self.path)
        _ensure_directory(parent)
        for _attempt in range(2):
            try:
                os.mkdir(self.path)
                self.acquired = True
                self._write_owner()
                return self
            except OSError:
                if os.path.isdir(self.path) and _is_stale(self.path, self.stale_seconds):
                    _remove_lock(self.path)
                    continue
                raise UpdateInProgress(
                    "Another WinUx update is already in progress for this local installation."
                )
        raise UpdateInProgress("Another WinUx update is already in progress.")

    def _write_owner(self):
        payload = {
            "pid": os.getpid(),
            "local_dir": self.local_dir,
            "started": datetime.datetime.now().isoformat(),
        }
        try:
            path = os.path.join(self.path, "owner.json")
            raw = json.dumps(payload, indent=2, sort_keys=True)
            if not isinstance(raw, bytes):
                raw = raw.encode("utf-8")
            with open(path, "wb") as handle:
                handle.write(raw)
                handle.write(b"\n")
        except Exception:
            pass

    def release(self):
        if not self.acquired:
            return
        try:
            _remove_lock(self.path)
        finally:
            self.acquired = False

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc_value, traceback):
        self.release()
        return False


__all__ = [
    "DEFAULT_STALE_SECONDS",
    "UpdateInProgress",
    "UpdateLock",
    "lock_path_for",
]
