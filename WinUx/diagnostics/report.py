from __future__ import annotations

import importlib.metadata
import os
import platform
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List

from .crash_logging import get_log_paths


PACKAGE_NAMES = ("dearpygui", "Pillow", "paramiko")


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not installed"
    except Exception as exc:
        return "unavailable ({})".format(exc)


def _module_location(name: str) -> str:
    module = sys.modules.get(name)
    if module is None:
        return "not loaded"
    return str(getattr(module, "__file__", "embedded"))


def _vendor_roots() -> List[Path]:
    package_root = Path(__file__).resolve().parents[2]
    candidates = [package_root / "vendor", package_root.parent / "vendor"]
    candidates.extend(
        Path(value) for value in sys.path
        if value and Path(value).name.casefold() == "vendor"
    )
    result = []
    seen = set()
    for path in candidates:
        try:
            path = path.resolve()
        except Exception:
            path = Path(path)
        key = str(path).casefold()
        if key not in seen and path.is_dir():
            seen.add(key)
            result.append(path)
    return result


def find_winux_plugins(roots: Iterable[Path] | None = None) -> List[str]:
    """Find likely WinUX Abaqus entry points to expose duplicate installs."""
    if roots is None:
        roots = [Path.home() / "abaqus_plugins"]
    matches = []
    skipped_directories = {
        ".git", "__pycache__", "vendor", "winux_vendor", "site-packages",
    }
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        try:
            for directory, child_dirs, names in os.walk(str(root)):
                child_dirs[:] = [
                    name for name in child_dirs
                    if name.casefold() not in skipped_directories]
                for name in names:
                    if not name.casefold().endswith("_plugin.py"):
                        continue
                    path = Path(directory) / name
                    likely_name = any(
                        token in name.casefold() for token in ("winux", "wixux"))
                    if not likely_name:
                        try:
                            sample = path.read_text(
                                encoding="utf-8", errors="ignore")[:32768].casefold()
                        except OSError:
                            continue
                        likely_name = "winux" in sample or "wixux" in sample
                    if likely_name:
                        matches.append(str(path.resolve()))
        except OSError:
            continue
    return sorted(set(matches), key=str.casefold)


def collect_diagnostics(plugin_roots: Iterable[Path] | None = None) -> Dict[str, object]:
    """Collect a dependency-free support snapshot without changing app state."""
    try:
        cwd = str(Path.cwd())
    except Exception as exc:
        cwd = "unavailable ({})".format(exc)
    package_root = Path(__file__).resolve().parents[1]
    vendor_roots = _vendor_roots()
    native_modules = []
    for root in vendor_roots:
        try:
            native_modules.extend(str(path) for path in root.rglob("*.pyd"))
        except OSError:
            pass
    return {
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "python": sys.version.replace("\n", " "),
        "executable": sys.executable or "embedded",
        "prefix": sys.prefix,
        "cwd": cwd,
        "package_root": str(package_root),
        "packages": {name: _package_version(name) for name in PACKAGE_NAMES},
        "modules": {
            "dearpygui": _module_location("dearpygui.dearpygui"),
            "PIL": _module_location("PIL"),
            "paramiko": _module_location("paramiko"),
        },
        "vendor_roots": [str(path) for path in vendor_roots],
        "native_modules": sorted(native_modules, key=str.casefold),
        "logs": get_log_paths(),
        "plugins": find_winux_plugins(plugin_roots),
        "environment": {
            name: os.environ.get(name, "")
            for name in ("WINUX_PYTHON", "WINUX_LOG_DIR", "LOCALAPPDATA", "APPDATA")
        },
    }


def format_diagnostics(data: Dict[str, object]) -> str:
    lines = [
        "WinUX Diagnostics",
        "Generated: {}".format(data.get("generated", "")),
        "",
        "Runtime",
        "  Platform: {}".format(data.get("platform", "")),
        "  Python: {}".format(data.get("python", "")),
        "  Executable: {}".format(data.get("executable", "")),
        "  Prefix: {}".format(data.get("prefix", "")),
        "  Working directory: {}".format(data.get("cwd", "")),
        "  WinUX package: {}".format(data.get("package_root", "")),
        "",
        "Packages",
    ]
    for name, value in dict(data.get("packages", {})).items():
        lines.append("  {}: {}".format(name, value))
    lines.extend(("", "Loaded modules"))
    for name, value in dict(data.get("modules", {})).items():
        lines.append("  {}: {}".format(name, value))

    sections = (
        ("Vendor roots", data.get("vendor_roots", [])),
        ("Native vendor modules", data.get("native_modules", [])),
        ("WinUX Abaqus plug-ins", data.get("plugins", [])),
    )
    for title, values in sections:
        values = list(values or [])
        lines.extend(("", title))
        lines.extend("  {}".format(value) for value in values)
        if not values:
            lines.append("  none found")

    lines.extend(("", "Diagnostic logs"))
    logs = dict(data.get("logs", {}))
    if logs:
        lines.extend("  {}: {}".format(key, value) for key, value in logs.items())
    else:
        lines.append("  logging has not been initialized")

    lines.extend(("", "Relevant environment"))
    for name, value in dict(data.get("environment", {})).items():
        lines.append("  {}={}".format(name, value or "<not set>"))
    return "\n".join(lines) + "\n"


def build_diagnostics_report(plugin_roots: Iterable[Path] | None = None) -> str:
    return format_diagnostics(collect_diagnostics(plugin_roots))
