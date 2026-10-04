"""Run widget tests with an isolated native DPG build for the host Python.

This runner never changes or replaces production vendor files. Preload the test
backend before WinUx adds its Abaqus-specific vendor directory to sys.path.
"""
import argparse
import importlib
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-deps", required=True)
    parser.add_argument("--pytest-deps", required=True)
    args, pytest_args = parser.parse_known_args()
    sys.path.insert(0, str(Path(args.pytest_deps).resolve()))
    sys.path.insert(0, str(Path(args.native_deps).resolve()))
    # Load the host Pillow package before WinUx's older ABI vendor is selected.
    importlib.import_module("PIL.Image")
    backend = importlib.import_module("dearpygui.dearpygui")
    package = importlib.import_module("dearpygui")
    root = Path(__file__).resolve().parents[1]
    vendor_version = (root / "vendor/dearpygui/__init__.py").read_text(encoding="utf-8")
    version = package.__version__
    if repr(version) not in vendor_version and '"{}"'.format(version) not in vendor_version:
        raise RuntimeError("test Dear PyGui version must match the production vendor version")
    print(json.dumps({"python": sys.version.split()[0], "dearpygui": version,
                      "backend": backend.__file__, "scope": "isolated native test build; production ABI unverified"}))
    sys.path.insert(0, str(root))
    import pytest
    return pytest.main(pytest_args or ["-q", "tests/test_native_widget_wrappers.py", "tests/test_dpg_dialog_migration.py"])


if __name__ == "__main__":
    raise SystemExit(main())
