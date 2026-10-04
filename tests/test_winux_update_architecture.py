"""Tests for the refactored transactional WinUx updater architecture."""

import json

import pytest

import winux_update_installer
import winux_update_lock
import winux_update_manifest
import winux_updater


def _deployment(root, version, marker=None):
    root.mkdir(parents=True, exist_ok=True)
    (root / "WinUx").mkdir(exist_ok=True)
    (root / "VERSION").write_text(version + "\n")
    for name in (
        "WinUx_plugin.py",
        "winux_launcher.py",
        "winux_updater.py",
        "winux_update_ui.py",
        "winux_update_manifest.py",
        "winux_update_lock.py",
        "winux_update_installer.py",
        "run_winux.py",
    ):
        (root / name).write_text("# {}\n".format(name))
    (root / "WinUx" / "__main__.py").write_text("# app\n")
    if marker:
        (root / marker).write_text(marker + "\n")
    winux_update_manifest.write_manifest(str(root))
    return root


def test_version_discovery_does_not_depend_on_publish_manifest(tmp_path):
    local = _deployment(tmp_path / "local", "1.0.0")
    server = _deployment(tmp_path / "server", "1.1.0")
    (server / winux_update_manifest.MANIFEST_FILENAME).unlink()

    status = winux_updater.get_update_status(str(local), str(server), environ={})

    assert status["available"] is True
    assert status["server_version"] == "1.1.0"
    assert status["manifest_valid"] is False
    assert "manifest" in status["reason"].lower()


def test_corrupted_server_file_is_rejected_before_local_swap(tmp_path):
    local = _deployment(tmp_path / "local", "1.0.0", marker="old.txt")
    server = _deployment(tmp_path / "server", "1.1.0", marker="new.txt")
    # Corrupt a file after the release manifest was published, preserving size
    # so the SHA-256 check (not merely file-size validation) is exercised.
    path = server / "run_winux.py"
    original = path.read_bytes()
    replacement = (b"X" if original[:1] != b"X" else b"Y") + original[1:]
    path.write_bytes(replacement)

    with pytest.raises(ValueError, match="checksum mismatch"):
        winux_update_installer.synchronize_project(str(server), str(local))

    assert winux_update_manifest.read_version(str(local)) == "1.0.0"
    assert (local / "old.txt").is_file()
    assert not (local / "new.txt").exists()


def test_health_check_failure_rolls_back_known_good_local(tmp_path):
    local = _deployment(tmp_path / "local", "1.0.0", marker="old.txt")
    server = _deployment(tmp_path / "server", "1.1.0", marker="new.txt")

    with pytest.raises(RuntimeError, match="health check failed"):
        winux_update_installer.synchronize_project(
            str(server),
            str(local),
            health_check=lambda _local, _manifest: False,
        )

    assert winux_update_manifest.read_version(str(local)) == "1.0.0"
    assert (local / "old.txt").is_file()
    assert not (local / "new.txt").exists()


def test_update_lock_prevents_two_processes_from_swapping_same_local(tmp_path):
    local = _deployment(tmp_path / "local", "1.0.0")
    environ = {"LOCALAPPDATA": str(tmp_path / "profile")}
    first = winux_update_lock.UpdateLock(str(local), environ=environ)
    second = winux_update_lock.UpdateLock(str(local), environ=environ)

    first.acquire()
    try:
        with pytest.raises(winux_update_lock.UpdateInProgress):
            second.acquire()
    finally:
        first.release()

    second.acquire()
    assert second.acquired is True
    second.release()


def test_stale_update_lock_is_recovered(tmp_path):
    local = _deployment(tmp_path / "local", "1.0.0")
    environ = {"LOCALAPPDATA": str(tmp_path / "profile")}
    lock = winux_update_lock.UpdateLock(str(local), environ=environ, stale_seconds=-1)
    path = winux_update_lock.lock_path_for(str(local), environ=environ)
    # Use os-level path returned by module to avoid platform separator assumptions.
    import os
    os.makedirs(path)
    with open(os.path.join(path, "owner.json"), "w") as handle:
        json.dump({"pid": 1}, handle)

    lock.acquire()
    assert lock.acquired is True
    lock.release()


def test_manifest_release_path_supports_versioned_immutable_release(tmp_path):
    source = tmp_path / "update-source"
    release = source / "releases" / "2.0.0"
    _deployment(release, "2.0.0", marker="release.txt")

    manifest = winux_update_manifest.build_manifest(
        str(release),
        version="2.0.0",
        release_path="releases/2.0.0",
        package_revision=7,
        released="2026-09-30",
    )
    source.mkdir(parents=True, exist_ok=True)
    winux_update_manifest.write_manifest(str(source), manifest=manifest)

    descriptor = winux_update_manifest.source_descriptor(str(source))

    assert descriptor["version"] == "2.0.0"
    assert descriptor["release_dir"] == str(release.resolve())
    assert descriptor["manifest"]["package_revision"] == 7

    local = _deployment(tmp_path / "local", "1.0.0")
    winux_update_installer.synchronize_project(str(source), str(local))
    installed_manifest = winux_update_manifest.load_manifest(str(local))
    assert installed_manifest["release_path"] == "."
    assert winux_update_manifest.source_is_valid(str(local)) is True


def test_update_rechecks_version_after_lock_is_acquired(tmp_path):
    local = _deployment(tmp_path / "local", "1.0.0")
    server = _deployment(tmp_path / "server", "1.1.0")
    events = []

    class Lock(object):
        def acquire(self):
            events.append("lock")
            # Simulate another updater completing just before this lock succeeds.
            (local / "VERSION").write_text("1.1.0\n")
            return self

        def release(self):
            events.append("unlock")

    status = winux_updater.update_local_if_newer(
        str(local),
        server_dir=str(server),
        environ={},
        dialog_available=lambda *_args: True,
        progress_factory=lambda *_args: None,
        sync_callable=lambda *_args, **_kwargs: pytest.fail("sync must not run"),
        lock_factory=lambda _path: Lock(),
        settings_path=str(tmp_path / "settings.json"),
    )

    assert status["updated"] is False
    assert status["reason"] == "local version became current before installation"
    assert events == ["lock", "unlock"]
