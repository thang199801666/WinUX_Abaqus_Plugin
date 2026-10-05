import json
import os
from pathlib import Path
from unittest import mock

import pytest

import winux_bootstrap_state as bootstrap
import winux_health_check
import winux_update_manifest
import winux_update_providers
import winux_updater


def _full_bootstrap_deployment(root, version):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "WinUx").mkdir(exist_ok=True)
    (root / "WinUx" / "__main__.py").write_text("# app\n")
    (root / "VERSION").write_text(version + "\n")
    for name in bootstrap.BOOTSTRAP_FILES:
        if name == "VERSION":
            continue
        (root / name).write_text("# {} {}\n".format(name, version))
    # Files required by the normal deployment validator.
    for name in ("WinUx_plugin.py", "winux_update_ui.py", "winux_update_lock.py"):
        path = root / name
        if not path.exists():
            path.write_text("# {}\n".format(name))
    winux_update_manifest.write_manifest(str(root))
    return root


def _env(tmp_path):
    return {"LOCALAPPDATA": str(tmp_path / "profile")}


def test_bootstrap_store_activates_new_version_and_keeps_previous(tmp_path):
    env = _env(tmp_path)
    d145 = _full_bootstrap_deployment(tmp_path / "d145", "1.6.45")
    d146 = _full_bootstrap_deployment(tmp_path / "d146", "1.6.46")

    first = bootstrap.install_from_deployment(str(d145), "1.6.45", environ=env)
    second = bootstrap.install_from_deployment(str(d146), "1.6.46", environ=env)

    assert first["version"] == "1.6.45"
    assert second["version"] == "1.6.46"
    state = bootstrap.load_state(env)
    assert state["active_version"] == "1.6.46"
    assert state["previous_versions"] == ["1.6.45"]
    assert bootstrap.resolve_active_bootstrap(environ=env) == os.path.abspath(
        bootstrap.version_dir("1.6.46", env)
    )


def test_bootstrap_resolution_falls_back_to_previous_when_active_is_damaged(tmp_path):
    env = _env(tmp_path)
    for version in ("1.6.45", "1.6.46"):
        deployment = _full_bootstrap_deployment(tmp_path / version, version)
        bootstrap.install_from_deployment(str(deployment), version, environ=env)
    os.remove(os.path.join(bootstrap.version_dir("1.6.46", env), "winux_launcher.py"))
    resolved = bootstrap.resolve_active_bootstrap(environ=env)
    assert resolved == os.path.abspath(bootstrap.version_dir("1.6.45", env))


class _FakeProcess(object):
    def __init__(self, returncode=0, output=b"WINUX_HEALTH_CHECK_OK 1.6.46\n"):
        self.returncode = returncode
        self._output = output
        self.command = None
        self.kwargs = None

    def communicate(self, timeout=None):
        return (self._output, None)

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9


def test_subprocess_health_check_uses_candidate_runner_and_isolated_environment(tmp_path):
    deployment = tmp_path / "candidate"
    deployment.mkdir()
    (deployment / "run_winux.py").write_text("# runner\n")
    captured = {}
    process = _FakeProcess()

    def factory(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return process

    assert winux_health_check.subprocess_health_check(
        str(deployment), environ={"TEMP": str(tmp_path)}, executable="python-test",
        popen_factory=factory,
    ) is True
    assert captured["command"] == ["python-test", str(deployment / "run_winux.py"), "--update-health-check"]
    assert captured["kwargs"]["env"]["WINUX_APP_DIR"] == str(deployment.resolve())
    assert captured["kwargs"]["env"]["WINUX_SKIP_UPDATE"] == "1"
    assert captured["kwargs"]["env"]["WINUX_HEALTH_CHECK"] == "1"


def test_subprocess_health_check_rejects_nonzero_candidate(tmp_path):
    deployment = tmp_path / "candidate"
    deployment.mkdir()
    (deployment / "run_winux.py").write_text("# runner\n")
    with pytest.raises(RuntimeError, match="candidate health check failed"):
        winux_health_check.subprocess_health_check(
            str(deployment), executable="python-test",
            popen_factory=lambda *_args, **_kwargs: _FakeProcess(2, b"missing native DLL"),
        )


def test_versioned_default_sync_enables_subprocess_health_check_on_windows(monkeypatch, tmp_path):
    source = tmp_path / "source"
    local = tmp_path / "local"
    source.mkdir(); local.mkdir()
    captured = {}

    monkeypatch.setattr(winux_updater, "_use_versioned_install", lambda **_kwargs: True)
    monkeypatch.setattr(winux_updater.os, "name", "nt")
    monkeypatch.setattr(
        winux_updater, "_subprocess_health_check",
        lambda root, manifest, environ=None: captured.setdefault("health_called", root) or True,
    )

    def fake_sync(source_dir, local_dir, **kwargs):
        captured.update(kwargs)
        assert callable(kwargs.get("health_check"))
        assert kwargs["health_check"]("candidate-root", {})
        return {"version": "1.6.46", "active_dir": "candidate-root", "mode": "versioned"}

    monkeypatch.setattr(winux_updater, "_synchronize_versioned_project", fake_sync)
    result = winux_updater._default_sync(str(source), str(local), environ={})
    assert result["version"] == "1.6.46"
    assert captured["health_called"] == "candidate-root"


def test_plugin_contains_stable_self_updating_bootstrap_shim():
    source = Path(__file__).resolve().parents[1].joinpath("WinUx_plugin.py").read_text()
    assert "_activate_self_updated_bootstrap" in source
    assert '"WinUx", "bootstrap"' in source
    assert 'from winux_launcher import launch_winux, resolve_project_dir' in source
