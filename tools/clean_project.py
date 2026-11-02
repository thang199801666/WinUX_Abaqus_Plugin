"""Remove generated project artifacts and validate the package layout.

This tool is intentionally conservative: it deletes only generated/cache files.
Source-tree layout errors are reported rather than auto-rewritten.
"""
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache"}
JUNK_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".bak", ".orig", ".rej"}


def clean_generated(root=ROOT):
    removed = []
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_dir() and path.name in CACHE_DIRS:
            shutil.rmtree(str(path), ignore_errors=True)
            removed.append(path)
        elif path.is_file() and path.suffix.lower() in JUNK_SUFFIXES:
            try:
                path.unlink()
                removed.append(path)
            except OSError:
                pass
    return removed


def structural_errors(root=ROOT):
    errors = []
    if not (root / "DearUIQt" / "__init__.py").is_file():
        errors.append("DearUIQt must be a root-level package beside WinUx.")
    if (root / "WinUx" / "DearUIQt").exists():
        errors.append("Duplicate WinUx/DearUIQt package must not exist.")
    if not (root / "WinUx" / "__init__.py").is_file():
        errors.append("WinUx application package is missing WinUx/__init__.py.")
    return errors


def main():
    removed = clean_generated()
    errors = structural_errors()
    print("Removed {} generated artifact(s).".format(len(removed)))
    if errors:
        for error in errors:
            print("ERROR: {}".format(error))
        return 1
    print("Project layout OK: WinUx and DearUIQt are sibling packages.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
