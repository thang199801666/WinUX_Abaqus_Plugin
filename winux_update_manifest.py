"""Version and integrity manifest support for WinUx deployments.

The updater treats ``update_manifest.json`` as the publish marker for a release.
The manifest is deliberately standard-library only and Python 2/3 compatible so
it can be consumed by Abaqus Python before WinUx/vendor packages are imported.
"""
from __future__ import print_function

import datetime
import hashlib
import json
import os


MANIFEST_FILENAME = "update_manifest.json"
MANIFEST_SCHEMA_VERSION = 1
VERSION_FILENAME = "VERSION"

IGNORED_DIRECTORIES = {
    "__pycache__",
    ".git",
    ".pytest_cache",
    ".mypy_cache",
}
IGNORED_SUFFIXES = (".pyc", ".pyo")
REQUIRED_FILES = (
    VERSION_FILENAME,
    "WinUx_plugin.py",
    "winux_launcher.py",
    "winux_updater.py",
    "winux_update_ui.py",
    "winux_update_manifest.py",
    "winux_update_lock.py",
    "winux_update_installer.py",
    "run_winux.py",
    os.path.join("WinUx", "__main__.py"),
)


def _text(value):
    try:
        text_type = unicode  # noqa: F821 - Python 2 only
    except NameError:
        text_type = str
    try:
        return text_type(value)
    except Exception:
        return str(value)


def _json_bytes(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    if not isinstance(raw, bytes):
        raw = raw.encode("utf-8")
    return raw


def _safe_relative_path(value):
    value = _text(value).replace("/", os.sep).replace("\\", os.sep)
    normalized = os.path.normpath(value)
    if not normalized or normalized == ".":
        raise ValueError("Manifest file path is empty.")
    if os.path.isabs(normalized) or normalized == os.pardir or normalized.startswith(os.pardir + os.sep):
        raise ValueError("Unsafe manifest file path: {}".format(value))
    return normalized


def _is_ignored_name(name):
    return name in IGNORED_DIRECTORIES or name.lower().endswith(IGNORED_SUFFIXES)


def read_version(project_dir):
    if not project_dir:
        return None
    path = os.path.join(os.path.abspath(project_dir), VERSION_FILENAME)
    try:
        with open(path, "rb") as handle:
            raw = handle.read().strip()
    except (IOError, OSError):
        return None
    if not raw:
        return None
    try:
        return raw.decode("utf-8").strip()
    except AttributeError:
        return str(raw).strip()
    except UnicodeDecodeError:
        return raw.decode("ascii", "ignore").strip()


def _split_version(value):
    if value is None:
        raise ValueError("Version is missing.")
    text = _text(value).strip()
    if text[:1].lower() == "v":
        text = text[1:]
    text = text.split("+", 1)[0]
    if "-" in text:
        release_text, prerelease_text = text.split("-", 1)
        prerelease = prerelease_text.strip() or None
    else:
        release_text = text
        prerelease = None
    pieces = release_text.split(".")
    if not pieces or any(not piece.isdigit() for piece in pieces):
        raise ValueError("Invalid WinUx version: {}".format(value))
    return tuple(int(piece) for piece in pieces), prerelease


def _compare_prerelease(left, right):
    if left is None and right is None:
        return 0
    if left is None:
        return 1
    if right is None:
        return -1
    left_parts = left.split(".")
    right_parts = right.split(".")
    for left_part, right_part in zip(left_parts, right_parts):
        if left_part == right_part:
            continue
        left_numeric = left_part.isdigit()
        right_numeric = right_part.isdigit()
        if left_numeric and right_numeric:
            left_number = int(left_part)
            right_number = int(right_part)
            return -1 if left_number < right_number else 1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return -1 if left_part.lower() < right_part.lower() else 1
    if len(left_parts) == len(right_parts):
        return 0
    return -1 if len(left_parts) < len(right_parts) else 1


def compare_versions(left, right):
    left_release, left_prerelease = _split_version(left)
    right_release, right_prerelease = _split_version(right)
    width = max(len(left_release), len(right_release))
    left_release += (0,) * (width - len(left_release))
    right_release += (0,) * (width - len(right_release))
    if left_release < right_release:
        return -1
    if left_release > right_release:
        return 1
    return _compare_prerelease(left_prerelease, right_prerelease)


def sha256_file(path, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def iter_deployment_files(project_dir):
    root_dir = os.path.abspath(project_dir)
    paths = []
    for root, dir_names, file_names in os.walk(root_dir):
        dir_names[:] = sorted(
            name for name in dir_names if not _is_ignored_name(name)
        )
        relative_root = os.path.relpath(root, root_dir)
        for name in sorted(file_names):
            if _is_ignored_name(name) or name == MANIFEST_FILENAME:
                continue
            relative_path = name if relative_root == "." else os.path.join(relative_root, name)
            paths.append(relative_path)
    return sorted(paths, key=lambda item: item.lower())


def _package_digest(files):
    normalized = [
        {
            "path": entry["path"].replace("\\", "/"),
            "size": int(entry["size"]),
            "sha256": _text(entry["sha256"]).lower(),
        }
        for entry in files
    ]
    return hashlib.sha256(_json_bytes(normalized)).hexdigest()


def build_manifest(project_dir, version=None, release_path=".", package_revision=1, released=None):
    root = os.path.abspath(project_dir)
    version = version or read_version(root)
    if not version:
        raise ValueError("Cannot build WinUx manifest without VERSION.")
    files = []
    for relative_path in iter_deployment_files(root):
        absolute_path = os.path.join(root, relative_path)
        files.append({
            "path": relative_path.replace("\\", "/"),
            "size": int(os.path.getsize(absolute_path)),
            "sha256": sha256_file(absolute_path),
        })
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "version": _text(version),
        "package_revision": int(package_revision),
        "released": released or datetime.date.today().isoformat(),
        "release_path": _text(release_path or "."),
        "file_count": len(files),
        "package_sha256": _package_digest(files),
        "files": files,
    }


def write_manifest(project_dir, manifest=None, path=None):
    root = os.path.abspath(project_dir)
    manifest = manifest or build_manifest(root)
    target = path or os.path.join(root, MANIFEST_FILENAME)
    temporary = target + ".tmp"
    payload = json.dumps(manifest, indent=2, sort_keys=True)
    if not isinstance(payload, bytes):
        payload = payload.encode("utf-8")
    with open(temporary, "wb") as handle:
        handle.write(payload)
        handle.write(b"\n")
    if os.path.exists(target):
        os.remove(target)
    os.rename(temporary, target)
    return target


def _validate_manifest_payload(manifest):
    if not isinstance(manifest, dict):
        raise ValueError("WinUx update manifest must contain a JSON object.")
    if int(manifest.get("schema_version", 0)) != MANIFEST_SCHEMA_VERSION:
        raise ValueError("Unsupported WinUx update manifest schema.")
    version = _text(manifest.get("version", "")).strip()
    if not version:
        raise ValueError("WinUx update manifest version is missing.")
    _split_version(version)
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("WinUx update manifest has no files.")
    seen = set()
    normalized_files = []
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("Invalid file entry in WinUx update manifest.")
        relative_path = _safe_relative_path(entry.get("path", ""))
        portable_path = relative_path.replace("\\", "/")
        key = portable_path.lower()
        if key in seen:
            raise ValueError("Duplicate manifest file path: {}".format(portable_path))
        seen.add(key)
        size = int(entry.get("size", -1))
        digest = _text(entry.get("sha256", "")).strip().lower()
        if size < 0 or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("Invalid manifest metadata for {}".format(portable_path))
        normalized_files.append({"path": portable_path, "size": size, "sha256": digest})
    expected_count = int(manifest.get("file_count", len(normalized_files)))
    if expected_count != len(normalized_files):
        raise ValueError("WinUx update manifest file_count does not match files.")
    expected_package = _text(manifest.get("package_sha256", "")).strip().lower()
    actual_package = _package_digest(normalized_files)
    if expected_package and expected_package != actual_package:
        raise ValueError("WinUx update manifest package checksum is invalid.")
    result = dict(manifest)
    result["files"] = normalized_files
    result["file_count"] = len(normalized_files)
    result["package_sha256"] = actual_package
    result["release_path"] = _text(result.get("release_path") or ".").strip() or "."
    return result


def load_manifest(source_dir):
    path = os.path.join(os.path.abspath(source_dir), MANIFEST_FILENAME)
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except (IOError, OSError):
        raise ValueError("WinUx update manifest is missing: {}".format(path))
    try:
        raw = raw.decode("utf-8")
    except AttributeError:
        pass
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError("WinUx update manifest is invalid: {}".format(exc))
    return _validate_manifest_payload(payload)


def resolve_release_dir(source_dir, manifest):
    source_dir = os.path.abspath(source_dir)
    release_path = _text(manifest.get("release_path") or ".").strip().strip('"') or "."
    release_path = os.path.expanduser(os.path.expandvars(release_path))
    if os.path.isabs(release_path):
        return os.path.abspath(release_path)
    return os.path.abspath(os.path.join(source_dir, release_path))


def required_files_present(project_dir):
    if not project_dir or not os.path.isdir(project_dir):
        return False
    root = os.path.abspath(project_dir)
    return all(os.path.isfile(os.path.join(root, path)) for path in REQUIRED_FILES)


def validate_manifest_release(source_dir, manifest=None, verify_hashes=False, progress_callback=None):
    manifest = manifest or load_manifest(source_dir)
    release_dir = resolve_release_dir(source_dir, manifest)
    if not required_files_present(release_dir):
        raise ValueError("WinUx release is incomplete: {}".format(release_dir))
    release_version = read_version(release_dir)
    if release_version != manifest["version"]:
        raise ValueError(
            "Manifest VERSION ({}) does not match release VERSION ({}).".format(
                manifest["version"], release_version or "missing"
            )
        )
    if verify_hashes:
        verify_deployment(release_dir, manifest, progress_callback=progress_callback)
    return release_dir


def verify_deployment(project_dir, manifest, progress_callback=None):
    root = os.path.abspath(project_dir)
    files = manifest["files"]
    total = max(1, len(files))
    for index, entry in enumerate(files, 1):
        relative_path = _safe_relative_path(entry["path"])
        absolute_path = os.path.join(root, relative_path)
        if not os.path.isfile(absolute_path):
            raise ValueError("Update file is missing: {}".format(entry["path"]))
        if int(os.path.getsize(absolute_path)) != int(entry["size"]):
            raise ValueError("Update file size mismatch: {}".format(entry["path"]))
        if sha256_file(absolute_path) != entry["sha256"]:
            raise ValueError("Update checksum mismatch: {}".format(entry["path"]))
        if progress_callback is not None:
            progress_callback(index, total, entry["path"])
    if read_version(root) != manifest["version"]:
        raise ValueError("Installed VERSION does not match update manifest.")
    if not required_files_present(root):
        raise ValueError("Installed WinUx deployment is missing required files.")
    return True


def source_descriptor(source_dir, verify_hashes=False):
    source_dir = os.path.abspath(source_dir)
    manifest = load_manifest(source_dir)
    release_dir = validate_manifest_release(
        source_dir, manifest=manifest, verify_hashes=verify_hashes
    )
    return {
        "source_dir": source_dir,
        "release_dir": release_dir,
        "manifest": manifest,
        "version": manifest["version"],
    }


def source_is_valid(source_dir):
    try:
        source_descriptor(source_dir, verify_hashes=False)
        return True
    except Exception:
        return False


__all__ = [
    "MANIFEST_FILENAME",
    "MANIFEST_SCHEMA_VERSION",
    "REQUIRED_FILES",
    "VERSION_FILENAME",
    "build_manifest",
    "compare_versions",
    "iter_deployment_files",
    "load_manifest",
    "read_version",
    "required_files_present",
    "resolve_release_dir",
    "sha256_file",
    "source_descriptor",
    "source_is_valid",
    "validate_manifest_release",
    "verify_deployment",
    "write_manifest",
]
