#!/usr/bin/env python3
"""Copy the standalone root-level :mod:`DearUIQt` package to another tree.

The package is already independent from WinUx, so exporting is a straight copy;
no source rewriting or compatibility-shim removal is required.
"""
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

DEFAULT_IMPORT_PACKAGE = "DearUIQt"
DEFAULT_PROJECT_NAME = "dearuiqt"


def _python_package_name(value: str) -> str:
    value = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise argparse.ArgumentTypeError("import package must be a valid Python identifier")
    return value


def export_framework(
    destination: Path,
    *,
    import_package: str = DEFAULT_IMPORT_PACKAGE,
    project_name: str = DEFAULT_PROJECT_NAME,
    overwrite: bool = False,
) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    source = repo_root / "DearUIQt"
    if not source.is_dir():
        raise FileNotFoundError(source)

    destination = Path(destination).resolve()
    if destination.exists():
        if not overwrite:
            raise FileExistsError(
                f"destination already exists: {destination}; pass --overwrite"
            )
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    package_dir = destination / import_package
    shutil.copytree(
        source,
        package_dir,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "*.md", "*.markdown"),
    )

    version = "0.0.0"
    init_source = (source / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', init_source, re.M)
    if match:
        version = match.group(1)

    (destination / "pyproject.toml").write_text(
        "\n".join([
            "[build-system]",
            'requires = ["setuptools>=68"]',
            'build-backend = "setuptools.build_meta"',
            "",
            "[project]",
            f'name = "{project_name}"',
            f'version = "{version}"',
            'description = "Qt-style Dear PyGui/Dear ImGui UI wrappers"',
            'requires-python = ">=3.10"',
            'dependencies = ["dearpygui", "Pillow"]',
            "",
            "[tool.setuptools.packages.find]",
            f'include = ["{import_package}*"]',
            "",
        ]),
        encoding="utf-8",
    )
    # Runtime exports intentionally contain no Markdown documentation.
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument(
        "--import-package", type=_python_package_name,
        default=DEFAULT_IMPORT_PACKAGE,
        help=f"Python package name (default: {DEFAULT_IMPORT_PACKAGE})",
    )
    parser.add_argument(
        "--project-name", default=DEFAULT_PROJECT_NAME,
        help=f"distribution name (default: {DEFAULT_PROJECT_NAME})",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    output = export_framework(
        args.destination,
        import_package=args.import_package,
        project_name=args.project_name,
        overwrite=args.overwrite,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
