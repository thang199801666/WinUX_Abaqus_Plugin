"""Build a verified WinUx release in one fail-closed command.

This command is the canonical packaging path. It removes generated artifacts,
validates Python syntax and project structure, runs a small release smoke suite,
rebuilds the deployment manifest, creates FULL and CHANGES-ONLY archives, then
extracts the FULL archive and verifies every manifest hash again.

Examples:
    python tools/release.py --revision 51
    python tools/release.py --revision 51 --output-dir /tmp/releases
    python tools/release.py --revision 51 --label StableBuild
"""
from __future__ import print_function

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.clean_project import clean_generated, structural_errors
from winux_runtime.update.manifest import (
    MANIFEST_FILENAME,
    build_manifest,
    iter_deployment_files,
    load_manifest,
    source_descriptor,
    write_manifest,
)

DEFAULT_TESTS = (
    "tests/test_project_structure.py",
    "tests/test_runtime_revision.py",
    "tests/test_launcher.py",
    "tests/test_release_pipeline.py",
    "tests/test_digitizer_tick_cache_lifecycle.py",
    "tests/test_digitizer_smart_region.py",
    "tests/test_digitizer_project_save.py",
    "tests/test_dearuiqt_size_policy.py",
    "tests/test_dearuiqt_dependent_layouts.py",
    "tests/test_dearuiqt_metrics.py",
    "tests/test_dearuiqt_typography_layout.py",
    "tests/test_font_selector.py",
    "tests/test_dearuiqt_dpi_controls.py",
    "tests/test_dearuiqt_live_dpi.py",
)

GENERATED_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache"}
GENERATED_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".bak", ".orig", ".rej"}


def _read_existing_manifest():
    path = ROOT / MANIFEST_FILENAME
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _manifest_map(manifest):
    result = {}
    if not isinstance(manifest, dict):
        return result
    for entry in manifest.get("files", ()) or ():
        try:
            path = str(entry["path"]).replace("\\", "/")
            result[path] = (int(entry["size"]), str(entry["sha256"]).lower())
        except Exception:
            continue
    return result


def manifest_diff(previous, current):
    """Return changed/new and deleted deployment paths between manifests."""
    before = _manifest_map(previous)
    after = _manifest_map(current)
    changed = sorted(path for path, metadata in after.items()
                     if before.get(path) != metadata)
    deleted = sorted(path for path in before if path not in after)
    return changed, deleted


def _release_tree_map(root):
    """Hash actual release-tree files, including docs and update manifest."""
    root = Path(root)
    result = {}
    for path, relative in _iter_full_archive_files(root):
        data = path.read_bytes()
        result[relative.as_posix()] = (len(data), hashlib.sha256(data).hexdigest())
    return result


def _baseline_zip_map(path):
    """Hash actual files in a previous FULL archive, ignoring generated junk."""
    result = {}
    with zipfile.ZipFile(str(path), "r") as archive:
        members = [name for name in archive.namelist() if not name.endswith("/")]
        first_parts = {Path(name).parts[0] for name in members if Path(name).parts}
        strip_root = len(first_parts) == 1
        for name in members:
            parts = Path(name).parts
            if strip_root and len(parts) > 1:
                parts = parts[1:]
            if not parts:
                continue
            relative = Path(*parts)
            if any(part in GENERATED_NAMES for part in relative.parts):
                continue
            if relative.suffix.lower() in GENERATED_SUFFIXES:
                continue
            data = archive.read(name)
            result[relative.as_posix()] = (len(data), hashlib.sha256(data).hexdigest())
    return result


def actual_tree_diff(baseline, current_root=ROOT):
    """Diff real file bytes against a previous FULL zip or project folder."""
    baseline = Path(baseline).resolve()
    if baseline.is_dir():
        before = _release_tree_map(baseline)
    elif baseline.is_file() and zipfile.is_zipfile(str(baseline)):
        before = _baseline_zip_map(baseline)
    else:
        raise ValueError("Baseline must be a project directory or FULL zip: {}".format(baseline))
    after = _release_tree_map(current_root)
    changed = sorted(path for path, metadata in after.items() if before.get(path) != metadata)
    deleted = sorted(path for path in before if path not in after)
    return changed, deleted


def baseline_generated_cleanup_paths(baseline):
    """Return generated paths that should be removed when merging onto baseline."""
    baseline = Path(baseline).resolve()
    cleanup = set()
    if baseline.is_dir():
        for path in baseline.rglob("*"):
            relative = path.relative_to(baseline)
            if path.is_dir() and path.name in GENERATED_NAMES:
                cleanup.add(relative.as_posix() + "/")
            elif path.is_file() and path.suffix.lower() in GENERATED_SUFFIXES:
                if not any(part in GENERATED_NAMES for part in relative.parts):
                    cleanup.add(relative.as_posix())
        return sorted(cleanup)
    if baseline.is_file() and zipfile.is_zipfile(str(baseline)):
        with zipfile.ZipFile(str(baseline), "r") as archive:
            members = archive.namelist()
            first_parts = {Path(name).parts[0] for name in members if Path(name).parts}
            strip_root = len(first_parts) == 1
            for name in members:
                parts = list(Path(name).parts)
                if strip_root and len(parts) > 1:
                    parts = parts[1:]
                if not parts:
                    continue
                for index, part in enumerate(parts):
                    if part in GENERATED_NAMES:
                        cleanup.add(Path(*parts[:index + 1]).as_posix() + "/")
                        break
                else:
                    relative = Path(*parts)
                    if relative.suffix.lower() in GENERATED_SUFFIXES:
                        cleanup.add(relative.as_posix())
        return sorted(cleanup)
    raise ValueError("Baseline must be a project directory or FULL zip: {}".format(baseline))


def validate_python_tree(root=ROOT):
    failures = []
    count = 0
    for path in sorted(root.rglob("*.py")):
        if any(part in GENERATED_NAMES for part in path.parts):
            continue
        count += 1
        try:
            text = path.read_text(encoding="utf-8")
            ast.parse(text, filename=str(path))
        except Exception as exc:
            failures.append((path.relative_to(root).as_posix(), str(exc)))
    if failures:
        lines = ["{}: {}".format(path, message) for path, message in failures]
        raise RuntimeError("Python syntax validation failed:\n" + "\n".join(lines))
    return count


def assert_clean_tree(root=ROOT):
    offenders = []
    for path in root.rglob("*"):
        if path.name in GENERATED_NAMES or (path.is_file() and path.suffix.lower() in GENERATED_SUFFIXES):
            offenders.append(path.relative_to(root).as_posix())
    if offenders:
        raise RuntimeError("Generated artifacts remain after clean: {}".format(", ".join(offenders[:20])))


def run_smoke_tests(test_paths=DEFAULT_TESTS):
    env = dict(os.environ)
    local = Path(tempfile.mkdtemp(prefix="winux_release_localappdata_"))
    try:
        (local / "Temp" / "opencode").mkdir(parents=True, exist_ok=True)
        env["LOCALAPPDATA"] = str(local)
        command = [sys.executable, "-m", "unittest"] + list(test_paths)
        completed = subprocess.run(command, cwd=str(ROOT), env=env)
        if completed.returncode:
            raise RuntimeError("Release smoke tests failed with exit code {}.".format(completed.returncode))
    finally:
        shutil.rmtree(str(local), ignore_errors=True)


def _iter_full_archive_files(root=ROOT):
    # FULL archive intentionally contains update_manifest.json even though that
    # file is excluded from the manifest's own package digest.
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in GENERATED_NAMES for part in relative.parts):
            continue
        if path.suffix.lower() in GENERATED_SUFFIXES:
            continue
        yield path, relative


def create_full_zip(target, root=ROOT):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    project_name = root.name
    with zipfile.ZipFile(str(target), "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, relative in _iter_full_archive_files(root):
            archive.write(str(path), arcname=(Path(project_name) / relative).as_posix())
    return target


def create_changes_zip(target, changed_paths, deleted_paths, root=ROOT):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    with zipfile.ZipFile(str(target), "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        included = set()
        for relative_text in sorted(changed_paths):
            path = root / Path(relative_text)
            if path.is_file():
                archive.write(str(path), arcname=relative_text.replace("\\", "/"))
                included.add(relative_text.replace("\\", "/"))
        # The manifest must always accompany a changes-only package because it
        # is the authoritative post-merge integrity descriptor.
        manifest_path = root / MANIFEST_FILENAME
        if MANIFEST_FILENAME not in included and manifest_path.is_file():
            archive.write(str(manifest_path), arcname=MANIFEST_FILENAME)
        if deleted_paths:
            archive.writestr("DELETE_THESE_PATHS.txt", "\n".join(deleted_paths) + "\n")
        # Never overwrite a deployment document with generic package notes:
        # its actual bytes may be covered by update_manifest.json.
        if "CHANGES_ONLY_README.txt" not in included:
            readme = root / "CHANGES_ONLY_README.txt"
            if readme.is_file():
                archive.write(str(readme), arcname="CHANGES_ONLY_README.txt")
            else:
                archive.writestr(
                    "CHANGES_ONLY_README.txt",
                    "WinUx CHANGES-ONLY package\n"
                    "Apply every included file using its relative path.\n"
                    "Delete paths listed in DELETE_THESE_PATHS.txt when present.\n"
                    "update_manifest.json describes the complete resulting deployment.\n",
                )
    return target


def verify_full_archive(path):
    with tempfile.TemporaryDirectory(prefix="winux_release_verify_") as temp:
        with zipfile.ZipFile(str(path), "r") as archive:
            bad = archive.testzip()
            if bad:
                raise RuntimeError("Corrupt FULL archive member: {}".format(bad))
            archive.extractall(temp)
        extracted = Path(temp) / ROOT.name
        source_descriptor(str(extracted), verify_hashes=True)
        assert_clean_tree(extracted)
    return True


def verify_changes_archive(path):
    with zipfile.ZipFile(str(path), "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError("Corrupt CHANGES-ONLY archive member: {}".format(bad))
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise RuntimeError("Duplicate CHANGES-ONLY archive members")
        if MANIFEST_FILENAME not in names:
            raise RuntimeError("CHANGES-ONLY archive is missing update_manifest.json")
        forbidden = [name for name in names if any(part in GENERATED_NAMES for part in Path(name).parts)
                     or Path(name).suffix.lower() in GENERATED_SUFFIXES]
        if forbidden:
            raise RuntimeError("Generated artifacts found in CHANGES-ONLY: {}".format(forbidden[:10]))
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", type=int, help="Positive package revision. Defaults to previous revision + 1.")
    parser.add_argument("--output-dir", default=str(ROOT.parent), help="Directory for generated ZIP archives.")
    parser.add_argument("--label", default="VerifiedRelease", help="Archive label after version.")
    parser.add_argument("--baseline", help="Previous FULL zip or project folder for exact CHANGES-ONLY diff.")
    parser.add_argument("--skip-tests", action="store_true", help="Skip smoke tests (not recommended for publishing).")
    args = parser.parse_args(argv)

    previous_manifest = _read_existing_manifest()
    previous_revision = int((previous_manifest or {}).get("package_revision") or 0)
    revision = args.revision if args.revision is not None else previous_revision + 1
    if revision < 1:
        parser.error("revision must be positive")
    if revision <= previous_revision:
        parser.error("revision must be greater than previous revision {}".format(previous_revision))

    removed = clean_generated(ROOT)
    errors = structural_errors(ROOT)
    if errors:
        raise RuntimeError("Project structure invalid:\n" + "\n".join(errors))
    assert_clean_tree(ROOT)
    parsed = validate_python_tree(ROOT)

    # Build a provisional manifest before the smoke suite because the structure
    # tests intentionally verify manifest/source integrity.  After tests run we
    # clean generated artifacts and rebuild the final manifest once more.
    manifest = build_manifest(str(ROOT), package_revision=revision)
    write_manifest(str(ROOT), manifest=manifest)
    source_descriptor(str(ROOT), verify_hashes=True)

    if not args.skip_tests:
        run_smoke_tests()

    # Tests may create ignored bytecode/cache artifacts. Remove them, rebuild the
    # manifest from the exact tree that will be packaged, then verify every hash.
    clean_generated(ROOT)
    assert_clean_tree(ROOT)
    manifest = build_manifest(str(ROOT), package_revision=revision)
    write_manifest(str(ROOT), manifest=manifest)
    source_descriptor(str(ROOT), verify_hashes=True)

    if args.baseline:
        changed, deleted = actual_tree_diff(args.baseline, ROOT)
        deleted = sorted(set(deleted) | set(baseline_generated_cleanup_paths(args.baseline)))
    else:
        changed, deleted = manifest_diff(previous_manifest, manifest)
    # update_manifest.json is deliberately excluded from deployment file hashes,
    # but must be present in every changes package.

    version = manifest["version"]
    label = str(args.label).strip().replace(" ", "-") or "VerifiedRelease"
    output = Path(args.output_dir).resolve()
    full = output / "WinUx-{}-{}-FULL.zip".format(version, label)
    changes = output / "WinUx-{}-{}-CHANGES-ONLY.zip".format(version, label)

    create_full_zip(full)
    create_changes_zip(changes, changed, deleted)
    verify_full_archive(full)
    verify_changes_archive(changes)

    print("VERIFIED RELEASE")
    print("  version: {}".format(version))
    print("  revision: {}".format(revision))
    print("  python files parsed: {}".format(parsed))
    print("  generated artifacts removed: {}".format(len(removed)))
    print("  manifest files: {}".format(manifest["file_count"]))
    print("  changed/new: {}".format(len(changed)))
    print("  deleted: {}".format(len(deleted)))
    print("  FULL: {}".format(full))
    print("  CHANGES-ONLY: {}".format(changes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
