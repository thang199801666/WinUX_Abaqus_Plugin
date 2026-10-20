"""Crash-safe runtime path helpers used during WinUx startup.

Abaqus/CAE can keep a process current directory on a project folder or mapped
network drive that is later deleted/disconnected.  On Windows both
``os.getcwd()`` and ``Path.cwd()`` can then raise before WinUx creates its first
window.  Startup callers should use :func:`safe_current_directory` instead of
assuming the inherited CWD is always valid.
"""
from __future__ import annotations

import os
from pathlib import Path


def safe_current_directory(fallback=None):
    """Return the inherited CWD, or a deterministic existing application path.

    The fallback path is intentionally derived from the installed package when
    no explicit value is supplied.  It is preferable to a user/network home
    during crash recovery because the package directory is already known to be
    readable if this module was imported successfully.
    """
    try:
        return Path.cwd()
    except (OSError, RuntimeError, ValueError):
        pass

    if fallback is not None:
        try:
            return Path(fallback).expanduser().resolve()
        except (OSError, RuntimeError, TypeError, ValueError):
            pass

    # WinUx/runtime/paths.py -> WinUx -> deployment root.  The package itself
    # has already been imported from here, so this is the safest startup anchor.
    try:
        return Path(__file__).resolve().parents[2]
    except Exception:
        # Last-ditch standard-library fallback.  Avoid calling Path.home()
        # first: enterprise home folders may themselves be disconnected shares.
        value = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or os.environ.get("TMP")
        if value:
            try:
                return Path(value)
            except Exception:
                pass
        return Path(".")


__all__ = ["safe_current_directory"]
