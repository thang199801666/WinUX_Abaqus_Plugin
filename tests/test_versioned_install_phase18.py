import json
import os

import pytest

import winux_installation_state as state
import winux_launcher
import winux_update_installer
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


def _env(tmp_path, **extra):
    value = {
        "LOCALAPPDATA": str(tmp_path / "profile"),
        "WINUX_INSTALL_MODE": "versioned",
    }
    value.update(extra)
    return value


def test_versioned_mode_is_windows_default_but_legacy_remains_explicitly_supported():
    assert state.normalize_install_mode(None, platform_name="nt") == "versioned"
    assert state.normalize_install_mode(None, platform_name="posix") == "legacy"
    assert state.normalize_install_mode("flat", platform_name="nt") == "legacy"
    assert state.normalize_install_mode("atomic", platform_name="posix") == "versioned"


def test_versioned_install_adds_new_files_without_mutating_flat_legacy_deployment(tmp_path):
    local = _deployment(tmp_path / "legacy", "1.6.44", marker="legacy-only.txt")
    source = _deployment(tmp_path / "server", "1.6.45", marker="new-module.py")
    environ = _env(tmp_path)

    result = winux_update_installer.synchronize_versioned_project(
        str(source), str(local), environ=environ, source_label=r"S:\\WinUx"
    )

    assert result["version"] == "1.6.45"
    active = result["active_dir"]
    assert winux_update_manifest.read_version(active) == "1.6.45"
    assert os.path.isfile(os.path.join(active, "new-module.py"))
    assert not os.path.exists(os.path.join(active, "legacy-only.txt"))
    # The pre-versioned plug-in folder remains a known-good emergency fallback.
    assert winux_update_manifest.read_version(str(local)) == "1.6.44"
    assert (local / "legacy-only.txt").is_file()
    assert state.resolve_active_installation(str(local), environ=environ) == active


def test_versioned_health_check_failure_never_changes_active_pointer(tmp_path):
    local = _deployment(tmp_path / "legacy", "1.6.44", marker="safe.txt")
    source = _deployment(tmp_path / "server", "1.6.45", marker="candidate.txt")
    environ = _env(tmp_path)

    with pytest.raises(RuntimeError, match="health check failed"):
        winux_update_installer.synchronize_versioned_project(
            str(source), str(local), environ=environ,
            health_check=lambda _root, _manifest: False,
        )

    assert state.resolve_active_installation(str(local), environ=environ) == str(local.resolve())
    assert winux_update_manifest.read_version(str(local)) == "1.6.44"
    assert (local / "safe.txt").is_file()


def test_two_previous_known_good_versions_are_retained_and_invalid_active_rolls_back(tmp_path):
    legacy = _deployment(tmp_path / "legacy", "1.6.43")
    environ = _env(tmp_path)
    release44 = _deployment(tmp_path / "release44", "1.6.44")
    release45 = _deployment(tmp_path / "release45", "1.6.45")
    release46 = _deployment(tmp_path / "release46", "1.6.46")

    first = winux_update_installer.synchronize_versioned_project(str(release44), str(legacy), environ=environ)
    second = winux_update_installer.synchronize_versioned_project(str(release45), first["active_dir"], environ=environ)
    third = winux_update_installer.synchronize_versioned_project(str(release46), second["active_dir"], environ=environ)

    payload = state.load_state(environ)
    assert payload["active_version"] == "1.6.46"
    assert payload["previous_versions"] == ["1.6.45", "1.6.44"]
    assert os.path.isdir(state.version_dir("1.6.44", environ))
    assert os.path.isdir(state.version_dir("1.6.45", environ))
    assert os.path.isdir(state.version_dir("1.6.46", environ))

    # Simulate a damaged active build. Launcher resolution must recover to the
    # newest known-good previous immutable version without touching S:.
    os.remove(os.path.join(third["active_dir"], "WinUx", "__main__.py"))
    recovered = state.resolve_active_installation(str(legacy), environ=environ)
    assert winux_update_manifest.read_version(recovered) == "1.6.45"
    assert state.load_state(environ)["active_version"] == "1.6.45"


def test_interrupted_pre_activation_transaction_keeps_old_pointer(tmp_path):
    environ = _env(tmp_path)
    legacy = _deployment(tmp_path / "legacy", "1.6.44")
    release45 = _deployment(tmp_path / "release45", "1.6.45")
    first = winux_update_installer.synchronize_versioned_project(str(release45), str(legacy), environ=environ)
    assert state.load_state(environ)["active_version"] == "1.6.45"

    incomplete = state.version_dir("1.6.46", environ)
    os.makedirs(incomplete)
    state.begin_transaction("1.6.45", "1.6.46", incomplete, source_label="GitHub", environ=environ)
    state.update_transaction("staged", environ=environ)

    active = state.resolve_active_installation(str(legacy), environ=environ)
    assert winux_update_manifest.read_version(active) == "1.6.45"
    assert not os.path.exists(incomplete)
    assert not os.path.exists(state.transaction_path(environ))


def test_launcher_prefers_active_version_but_legacy_mode_can_force_bundled_fallback(tmp_path, monkeypatch):
    bundled = _deployment(tmp_path / "bundled", "1.6.44")
    active = _deployment(tmp_path / "profile" / "WinUx" / "runtime" / "versions" / "1.6.45", "1.6.45")
    environ = {"LOCALAPPDATA": str(tmp_path / "profile")}
    state.write_state("1.6.45", [], environ=environ)
    monkeypatch.setattr(winux_launcher, "_bundled_project_dir", lambda: str(bundled))
    monkeypatch.setattr(winux_launcher, "__file__", str(bundled / "winux_launcher.py"))

    assert winux_launcher.resolve_project_dir(environ=environ) == str(active.resolve())
    legacy_env = dict(environ)
    legacy_env["WINUX_INSTALL_MODE"] = "legacy"
    assert winux_launcher.resolve_project_dir(environ=legacy_env) == str(bundled.resolve())


def test_folder_s_drive_provider_can_activate_versioned_install_without_modifying_source_or_legacy(tmp_path):
    local = _deployment(tmp_path / "legacy", "1.0.0", marker="old.txt")
    server = _deployment(tmp_path / "server", "1.1.0", marker="new.txt")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "update_provider": "folder",
        "update_source": str(server),
        "update_install_mode": "versioned",
    }))
    environ = _env(tmp_path)

    class Progress(object):
        def update(self, _percent, _message):
            pass
        def close(self):
            pass

    status = winux_updater.update_local_if_newer(
        str(local), server_dir=str(server), environ=environ,
        settings_path=str(settings), dialog_available=lambda *_args: True,
        progress_factory=lambda *_args: Progress(),
        # Synthetic modules exercise activation rather than runtime imports.
        health_check=lambda *_args: True,
    )

    assert status["updated"] is True
    assert status["install_mode"] == "versioned"
    assert winux_update_manifest.read_version(status["active_dir"]) == "1.1.0"
    assert os.path.isfile(os.path.join(status["active_dir"], "new.txt"))
    assert winux_update_manifest.read_version(str(local)) == "1.0.0"
    assert winux_update_manifest.read_version(str(server)) == "1.1.0"


def test_versioned_install_delays_old_process_close_until_candidate_is_verified(tmp_path):
    local = _deployment(tmp_path / "legacy", "1.6.44")
    source = _deployment(tmp_path / "server", "1.6.45")
    environ = _env(tmp_path)
    events = []

    def health_check(_root, _manifest):
        events.append("health")
        return True

    def before_activate():
        events.append("close-old")

    result = winux_update_installer.synchronize_versioned_project(
        str(source), str(local), environ=environ,
        health_check=health_check, before_activate=before_activate,
    )

    assert result["version"] == "1.6.45"
    assert events == ["health", "close-old"]


def test_child_bootstrap_switches_import_root_to_new_active_version(tmp_path, monkeypatch):
    import run_winux
    old = _deployment(tmp_path / "old", "1.6.44")
    active = _deployment(tmp_path / "active", "1.6.45")
    monkeypatch.setenv("WINUX_APP_DIR", str(old))
    monkeypatch.setattr(run_winux.sys, "path", [str(old), "sentinel"])

    selected = run_winux._switch_to_active_project(
        str(old), {"active_dir": str(active), "updated": True}
    )

    assert selected == str(active.resolve())
    assert run_winux.sys.path[0] == str(active.resolve())
    assert str(old.resolve()) not in run_winux.sys.path
    assert os.environ["WINUX_APP_DIR"] == str(active.resolve())


def test_newer_bundled_hotfix_is_not_shadowed_by_older_active_runtime(tmp_path):
    bundled = _deployment(tmp_path / "bundled", "1.6.46")
    active = _deployment(tmp_path / "profile" / "WinUx" / "runtime" / "versions" / "1.6.45", "1.6.45")
    environ = {"LOCALAPPDATA": str(tmp_path / "profile")}
    state.write_state("1.6.45", [], environ=environ)

    resolved = state.resolve_active_installation(str(bundled), environ=environ)
    assert resolved == str(bundled.resolve())
    assert winux_update_manifest.read_version(active) == "1.6.45"
