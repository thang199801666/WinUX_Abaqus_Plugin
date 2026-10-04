"""Transactional staging/install/rollback for WinUx updates."""
from __future__ import print_function

import datetime
import os
import shutil

from winux_update_manifest import (
    MANIFEST_FILENAME,
    build_manifest,
    load_manifest,
    read_version,
    required_files_present,
    resolve_release_dir,
    source_descriptor,
    verify_deployment,
    write_manifest,
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


def _same_path(left, right):
    if not left or not right:
        return False
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def _unique_sibling(local_dir, label):
    parent = os.path.dirname(os.path.abspath(local_dir))
    base = os.path.basename(os.path.abspath(local_dir))
    stamp = "{}_{}".format(os.getpid(), datetime.datetime.now().strftime("%H%M%S%f"))
    return os.path.join(parent, ".{}.{}.{}".format(base, label, stamp))


def _remove_path(path):
    if not os.path.exists(path):
        return
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


def _notify(callback, percent, message):
    if callback is None:
        return
    callback(int(percent), _text(message))


def _safe_relative_path(path):
    normalized = os.path.normpath(path.replace("/", os.sep).replace("\\", os.sep))
    if os.path.isabs(normalized) or normalized == os.pardir or normalized.startswith(os.pardir + os.sep):
        raise RuntimeError("Unsafe update file path: {}".format(path))
    return normalized


def stage_release(source_dir, local_dir, manifest=None, progress_callback=None):
    """Copy only files declared by the manifest into a sibling staging folder."""
    if manifest is None:
        descriptor = source_descriptor(source_dir, verify_hashes=False)
        manifest = descriptor["manifest"]
    release_dir = resolve_release_dir(source_dir, manifest)
    local_dir = os.path.abspath(local_dir)
    stage_dir = _unique_sibling(local_dir, "update")
    _remove_path(stage_dir)
    os.makedirs(stage_dir)

    files = manifest["files"]
    total = max(1, len(files))
    _notify(progress_callback, 3, "Preparing {0} update files...".format(len(files)))
    try:
        for index, entry in enumerate(files, 1):
            relative_path = _safe_relative_path(entry["path"])
            source_path = os.path.join(release_dir, relative_path)
            destination_path = os.path.join(stage_dir, relative_path)
            if not os.path.isfile(source_path):
                raise RuntimeError("Shared update file disappeared: {}".format(entry["path"]))
            parent = os.path.dirname(destination_path)
            if parent and not os.path.isdir(parent):
                os.makedirs(parent)
            shutil.copy2(source_path, destination_path)
            percent = 3 + int((float(index) / float(total)) * 72.0)
            _notify(
                progress_callback,
                percent,
                "Copying {0}/{1}: {2}".format(index, len(files), entry["path"]),
            )
        # The shared manifest may point at an immutable release directory such
        # as ``releases/1.4.0``.  The installed local deployment is flattened,
        # so persist an equivalent local manifest whose release_path is ``.``.
        local_manifest = dict(manifest)
        local_manifest["release_path"] = "."
        write_manifest(stage_dir, manifest=local_manifest)
        return stage_dir
    except Exception:
        try:
            _remove_path(stage_dir)
        except Exception:
            pass
        raise


def validate_stage(stage_dir, manifest, progress_callback=None):
    files = manifest["files"]
    total = max(1, len(files))

    def verify_progress(index, _total, relative_path):
        percent = 76 + int((float(index) / float(total)) * 14.0)
        _notify(progress_callback, percent, "Verifying {0}/{1}: {2}".format(index, len(files), relative_path))

    _notify(progress_callback, 76, "Validating staged update and SHA-256 checksums...")
    verify_deployment(stage_dir, manifest, progress_callback=verify_progress)
    return True


def install_staged(stage_dir, local_dir, manifest, progress_callback=None, health_check=None):
    """Atomically swap stage into place; rollback if install/health check fails."""
    stage_dir = os.path.abspath(stage_dir)
    local_dir = os.path.abspath(local_dir)
    if not os.path.isdir(stage_dir):
        raise RuntimeError("Staged WinUx update does not exist: {}".format(stage_dir))
    if not os.path.isdir(local_dir):
        raise RuntimeError("Local WinUx deployment does not exist: {}".format(local_dir))

    backup_dir = _unique_sibling(local_dir, "backup")
    _remove_path(backup_dir)
    moved_local = False
    installed_stage = False
    try:
        _notify(progress_callback, 92, "Installing the new WinUx version...")
        os.rename(local_dir, backup_dir)
        moved_local = True
        os.rename(stage_dir, local_dir)
        installed_stage = True

        _notify(progress_callback, 96, "Running post-install health check...")
        verify_deployment(local_dir, manifest)
        if health_check is not None:
            result = health_check(local_dir, manifest)
            if result is False:
                raise RuntimeError("WinUx post-install health check failed.")

        _notify(progress_callback, 99, "Cleaning up the previous version...")
        try:
            _remove_path(backup_dir)
        except Exception:
            # Cleanup is non-critical; leaving a backup is safer than failing a
            # successfully installed and verified update.
            pass
        return read_version(local_dir)
    except Exception:
        # If the staged deployment was already swapped in, remove it before
        # restoring the known-good backup. If only the local->backup rename
        # happened, simply restore the backup.
        if installed_stage and os.path.exists(local_dir):
            try:
                _remove_path(local_dir)
            except Exception:
                pass
        if moved_local and os.path.exists(backup_dir) and not os.path.exists(local_dir):
            try:
                os.rename(backup_dir, local_dir)
            except Exception:
                pass
        raise
    finally:
        if os.path.exists(stage_dir):
            try:
                _remove_path(stage_dir)
            except Exception:
                pass



def _descriptor_for_install(source_dir, progress_callback=None):
    """Return a strict published descriptor or a verified transient snapshot.

    ``update_manifest.json`` remains the preferred publish mechanism.  For the
    corporate flat S: deployment, administrators sometimes replace files and
    bump ``VERSION`` before regenerating the manifest.  That must not make a
    newer VERSION invisible.  When the published manifest is unavailable or
    stale, Update Now builds an in-memory SHA-256 manifest from the reachable
    source, stages exactly that snapshot, then verifies every copied file.
    Nothing is written back to S:.
    """
    try:
        return source_descriptor(source_dir, verify_hashes=False)
    except Exception:
        version = read_version(source_dir)
        if not version:
            raise RuntimeError("Shared WinUx VERSION is missing: {}".format(source_dir))
        if not required_files_present(source_dir):
            raise RuntimeError("Shared WinUx deployment is incomplete: {}".format(source_dir))
        _notify(progress_callback, 2, "Preparing integrity snapshot for version {}...".format(version))
        manifest = build_manifest(
            source_dir,
            version=version,
            release_path=".",
            package_revision=0,
        )
        return {
            "source_dir": os.path.abspath(source_dir),
            "release_dir": os.path.abspath(source_dir),
            "manifest": manifest,
            "version": version,
            "transient_manifest": True,
        }

def synchronize_project(source_dir, local_dir, progress_callback=None, health_check=None):
    """Transactional update: manifest -> stage -> SHA-256 -> swap -> health check."""
    source_dir = os.path.abspath(source_dir)
    local_dir = os.path.abspath(local_dir)
    if _same_path(source_dir, local_dir):
        raise RuntimeError("Update source and local deployment are identical.")
    descriptor = _descriptor_for_install(source_dir, progress_callback=progress_callback)
    manifest = descriptor["manifest"]
    stage_dir = stage_release(
        source_dir,
        local_dir,
        manifest=manifest,
        progress_callback=progress_callback,
    )
    try:
        validate_stage(stage_dir, manifest, progress_callback=progress_callback)
        installed = install_staged(
            stage_dir,
            local_dir,
            manifest,
            progress_callback=progress_callback,
            health_check=health_check,
        )
        _notify(progress_callback, 100, "Update complete. Starting WinUx...")
        return installed
    except Exception:
        if os.path.exists(stage_dir):
            try:
                _remove_path(stage_dir)
            except Exception:
                pass
        raise


__all__ = [
    "install_staged",
    "stage_release",
    "synchronize_project",
    "validate_stage",
]
