import json
from unittest import mock

import run_winux
import winux_installation_state as state
import winux_update_manifest
import winux_updater


def _deployment(root, version):
    root.mkdir(parents=True, exist_ok=True)
    (root / "WinUx").mkdir(exist_ok=True)
    (root / "WinUx" / "__main__.py").write_text("# app\n")
    (root / "VERSION").write_text(version + "\n")
    for name in (
        "WinUx_plugin.py", "winux_launcher.py", "winux_updater.py",
        "winux_update_ui.py", "winux_update_manifest.py", "winux_update_lock.py",
        "winux_update_installer.py", "winux_installation_state.py",
        "winux_bootstrap_state.py", "winux_health_check.py", "run_winux.py",
    ):
        (root / name).write_text("# {}\n".format(name))
    winux_update_manifest.write_manifest(str(root))
    return root


def test_update_discovery_uses_active_runtime_instead_of_stale_launcher_path(tmp_path):
    stale = _deployment(tmp_path / "legacy", "1.1.2")
    active = _deployment(
        tmp_path / "profile" / "WinUx" / "runtime" / "versions" / "1.1.3",
        "1.1.3",
    )
    environ = {"LOCALAPPDATA": str(tmp_path / "profile")}
    state.write_state("1.1.3", [], environ=environ)

    class Provider(object):
        def __init__(self, **_kwargs):
            pass
        def check(self, local_version):
            assert local_version == "1.1.3"
            return {
                "provider": "github",
                "source_label": "GitHub Releases: acme/WinUx (stable)",
                "repository": "acme/WinUx",
                "channel": "stable",
                "local_version": local_version,
                "server_version": "1.1.3",
                "available": False,
                "reason": "local version is current",
            }

    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "update_provider": "github",
        "github_repository": "acme/WinUx",
    }))
    dialog = mock.Mock(return_value=True)
    status = winux_updater.update_local_if_newer(
        str(stale), environ=environ, settings_path=str(settings),
        github_provider_factory=Provider, dialog_available=dialog,
    )

    assert status["available"] is False
    assert status["local_version"] == "1.1.3"
    assert status["local_dir"] == str(active.resolve())
    dialog.assert_not_called()


def test_manual_check_also_uses_active_runtime_before_github_comparison(tmp_path):
    stale = _deployment(tmp_path / "legacy", "1.1.2")
    _deployment(
        tmp_path / "profile" / "WinUx" / "runtime" / "versions" / "1.1.3",
        "1.1.3",
    )
    environ = {"LOCALAPPDATA": str(tmp_path / "profile")}
    state.write_state("1.1.3", [], environ=environ)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "update_provider": "github",
        "github_repository": "acme/WinUx",
    }))

    class Provider(object):
        def __init__(self, **_kwargs):
            pass
        def check(self, local_version):
            return {
                "provider": "github", "source_label": "GitHub", "repository": "acme/WinUx",
                "channel": "stable", "local_version": local_version,
                "server_version": "1.1.3", "available": local_version != "1.1.3",
                "reason": "local version is current" if local_version == "1.1.3" else "newer",
            }

    status = winux_updater.check_for_updates(
        str(stale), environ=environ, settings_path=str(settings),
        github_provider_factory=Provider,
    )
    assert status["local_version"] == "1.1.3"
    assert status["available"] is False


def test_runner_rebinds_stale_winux_app_dir_to_active_runtime(tmp_path, monkeypatch):
    stale = _deployment(tmp_path / "legacy", "1.1.2")
    active = _deployment(
        tmp_path / "profile" / "WinUx" / "runtime" / "versions" / "1.1.3",
        "1.1.3",
    )
    environ = {"LOCALAPPDATA": str(tmp_path / "profile")}
    state.write_state("1.1.3", [], environ=environ)

    monkeypatch.setenv("LOCALAPPDATA", environ["LOCALAPPDATA"])
    monkeypatch.setenv("WINUX_APP_DIR", str(stale))
    monkeypatch.delenv("WINUX_SKIP_UPDATE", raising=False)
    monkeypatch.delenv("WINUX_HEALTH_CHECK", raising=False)
    monkeypatch.setattr(run_winux.sys, "argv", ["run_winux.py"])

    assert run_winux._project_dir() == str(active.resolve())


def test_legacy_sharing_violation_persists_versioned_install_mode(tmp_path, monkeypatch):
    class SharingViolation(OSError):
        winerror = 32
        errno = 13

    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"update_install_mode": "legacy"}))
    environ = {"LOCALAPPDATA": str(tmp_path / "profile"), "APPDATA": str(tmp_path / "roaming")}

    monkeypatch.setattr(winux_updater.os, "name", "nt")
    monkeypatch.setattr(winux_updater, "_use_versioned_install", lambda **_k: False)
    monkeypatch.setattr(
        winux_updater, "_synchronize_project",
        mock.Mock(side_effect=SharingViolation("file is being used by another process")),
    )
    monkeypatch.setattr(
        winux_updater, "_synchronize_versioned_project",
        mock.Mock(return_value={"version": "1.1.3", "active_dir": "active", "mode": "versioned"}),
    )

    result = winux_updater._default_sync(
        "stage", "local", environ=environ, settings_path=str(settings),
    )

    assert result["mode"] == "versioned"
    assert json.loads(settings.read_text())["update_install_mode"] == "versioned"
