"""Report a stable, dependency-free refactor baseline for WinUx.

The report intentionally uses only the standard library so it can run with the
same Abaqus/embedded Python used by WinUx.  It is a measurement tool, not a
runtime dependency.
"""
from __future__ import print_function

import argparse
import ast
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "WinUx"


def _python_files(root):
    for path in root.rglob("*.py"):
        parts = set(path.parts)
        if "vendor" in parts or "__pycache__" in parts:
            continue
        yield path


def _module_metrics(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return {"lines": len(text.splitlines()), "classes": 0, "functions": 0,
                "methods": 0, "parse_error": True}
    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    methods = sum(
        1 for cls in classes for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    return {"lines": len(text.splitlines()), "classes": len(classes),
            "functions": len(functions), "methods": methods, "parse_error": False}


def build_report():
    modules = []
    for path in _python_files(PACKAGE):
        rel = path.relative_to(ROOT).as_posix()
        data = _module_metrics(path)
        data["path"] = rel
        modules.append(data)

    duplicate_root = PACKAGE / "WinUx"
    duplicate_files = []
    if duplicate_root.is_dir():
        for old_path in _python_files(duplicate_root):
            rel = old_path.relative_to(duplicate_root)
            current = PACKAGE / rel
            duplicate_files.append({
                "legacy": old_path.relative_to(ROOT).as_posix(),
                "current": current.relative_to(ROOT).as_posix(),
                "current_exists": current.exists(),
            })

    tests = sorted((ROOT / "tests").glob("test_*.py"))
    version_path = ROOT / "VERSION"
    return {
        "version": version_path.read_text(encoding="utf-8").strip() if version_path.exists() else "unknown",
        "python_files": len(modules),
        "python_lines": sum(item["lines"] for item in modules),
        "test_modules": len(tests),
        "duplicate_tree_files": duplicate_files,
        "largest_modules": sorted(modules, key=lambda item: item["lines"], reverse=True)[:20],
        "most_methods": sorted(modules, key=lambda item: item["methods"], reverse=True)[:20],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Measure the WinUx refactor baseline.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--output", help="write JSON report to this file")
    args = parser.parse_args(argv)
    report = build_report()
    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    if args.json:
        print(payload)
        return 0

    print("WinUx refactor baseline {}".format(report["version"]))
    print("Python files: {}".format(report["python_files"]))
    print("Python lines: {}".format(report["python_lines"]))
    print("Test modules: {}".format(report["test_modules"]))
    print("Duplicate-tree files: {}".format(len(report["duplicate_tree_files"])))
    print("\nLargest modules:")
    for item in report["largest_modules"][:10]:
        print("  {:6d} lines  {:4d} methods  {}".format(item["lines"], item["methods"], item["path"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
