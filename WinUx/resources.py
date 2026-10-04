"""Application resource discovery helpers.

All UI code should resolve images, icons and bundled documents through this
module instead of building paths relative to the current working directory.
This keeps resources working when WinUX is started with ``python -m WinUx``,
from another directory, or from a PyInstaller bundle.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable

try:
    import tkinter as tk
except Exception:  # pragma: no cover - Tk may be unavailable in headless CI
    tk = None


PACKAGE_DIR = Path(__file__).resolve().parent


def _candidate_resource_dirs() -> Iterable[Path]:
    """Yield resource directories from most to least specific."""
    # PyInstaller extracts bundled data below ``sys._MEIPASS`` at runtime.
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        yield Path(bundle_root) / "Resources"
        yield Path(bundle_root) / "WinUx" / "Resources"

    # Normal source/package layout: WinUx/resources.py + WinUx/Resources/.
    yield PACKAGE_DIR / "Resources"

    # Support deployments that keep Resources next to the executable.
    try:
        yield Path(sys.executable).resolve().parent / "Resources"
    except Exception:
        pass

    # Last-resort compatibility for legacy launch scripts.
    yield Path.cwd() / "Resources"


def _resolve_resource_dir() -> Path:
    candidates = list(_candidate_resource_dirs())
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    # Preserve a deterministic path even when the folder was accidentally
    # omitted, so error messages identify the expected package location.
    return (PACKAGE_DIR / "Resources").resolve()


RESOURCE_DIR = _resolve_resource_dir()


def resource_path(name: str | os.PathLike[str], *, required: bool = False) -> Path:
    """Return an absolute path inside :data:`RESOURCE_DIR`.

    A case-insensitive fallback is included so the same resource names behave
    consistently on Windows and case-sensitive development/test systems.
    """
    relative = Path(os.fspath(name))
    path = relative if relative.is_absolute() else RESOURCE_DIR / relative

    if path.exists():
        return path.resolve()

    if not relative.is_absolute() and RESOURCE_DIR.is_dir():
        wanted = relative.name.casefold()
        try:
            match = next(
                (entry for entry in RESOURCE_DIR.iterdir()
                 if entry.name.casefold() == wanted),
                None,
            )
        except OSError:
            match = None
        if match is not None:
            return match.resolve()

    if required:
        raise FileNotFoundError("WinUX resource was not found: {}".format(path))
    return path.resolve()


def apply_tk_app_icon(window) -> bool:
    """Apply the WinUx application icon to a Tk/Toplevel window.

    Uses the bundled ``WinUx.ico`` on Windows and falls back to ``WinUx.png``
    via ``iconphoto`` when ``iconbitmap`` is unavailable.  The created
    ``PhotoImage`` is stored on the window to keep the Tk image alive for the
    lifetime of the dialog.
    """
    if window is None:
        return False
    applied = False
    try:
        icon = resource_path("WinUx.ico", required=True)
        window.iconbitmap(str(icon))
        applied = True
    except Exception:
        pass

    if tk is None:
        return applied
    try:
        png = resource_path("WinUx.png", required=True)
        photo = tk.PhotoImage(file=str(png))
        window._winux_icon_photo = photo
        window.iconphoto(True, photo)
        applied = True
    except Exception:
        pass
    return applied


def icon_path(name: str | os.PathLike[str], *, required: bool = False) -> Path:
    """Resolve a PNG icon name, accepting names with or without ``.png``."""
    value = os.fspath(name)
    filename = value if value.lower().endswith(".png") else "{}.png".format(value)
    return resource_path(filename, required=required)


__all__ = ["PACKAGE_DIR", "RESOURCE_DIR", "resource_path", "icon_path", "apply_tk_app_icon"]
