"""Regression tests for WinUx local-first version/update behavior."""

import json
from unittest import mock

import pytest

import winux_updater
import winux_update_manifest


def _deployment(root, version, marker=None):
    root.mkdir(parents=True, exist_ok=True)
    (root / "WinUx").mkdir(exist_ok=True)
    (root / "VERSION").write_text(version + "\n")
    (root / "WinUx_plugin.py").write_text("# plugin\n")
    (root / "winux_launcher.py").write_text("# launcher\n")
    (root / "winux_updater.py").write_text("# updater\n")
    (root / "winux_update_ui.py").write_text("# updater ui\n")
    (root / "winux_update_manifest.py").write_text("# manifest\n")
    (root / "winux_update_lock.py").write_text("# lock\n")
    (root / "winux_update_installer.py").write_text("# installer\n")
    (root / "run_winux.py").write_text("# runner\n")
    (root / "WinUx" / "__main__.py").write_text("# app\n")
    if marker:
        (root / marker).write_text(marker + "\n")
    winux_update_manifest.write_manifest(str(root))
    return root


@pytest.mark.parametrize(
    "left,right,expected",
    [
        ("1.0.0", "1.0.0", 0),
        ("1.1.0", "1.0.9", 1),
        ("1.0.9", "1.1.0", -1),
        ("v2.0", "2.0.0", 0),
        ("2.0.0-beta.2", "2.0.0-beta.10", -1),
        ("2.0.0-rc.1", "2.0.0", -1),
        ("2.0.0", "2.0.0-rc.1", 1),
    ],
)
def test_compare_versions(left, right, expected):
    assert winux_updater.compare_versions(left, right) == expected


def test_newer_shared_version_is_detected(tmp_path):
    local = _deployment(tmp_path / "local", "1.1.0")
    server = _deployment(tmp_path / "server", "1.2.0")

    status = winux_updater.get_update_status(str(local), str(server), environ={})

    assert status["available"] is True
    assert status["local_version"] == "1.1.0"
    assert status["server_version"] == "1.2.0"


def test_same_or_older_shared_version_does_not_update(tmp_path):
    local = _deployment(tmp_path / "local", "1.2.0")
    server = _deployment(tmp_path / "server", "1.2.0")

    status = winux_updater.get_update_status(str(local), str(server), environ={})

    assert status["available"] is False
    assert status["reason"] == "local version is current"


def test_unavailable_shared_deployment_does_not_block_local(tmp_path):
    local = _deployment(tmp_path / "local", "1.1.0")

    status = winux_updater.get_update_status(
        str(local), str(tmp_path / "missing-server"), environ={}
    )

    assert status["available"] is False
    assert "unavailable" in status["reason"]


def test_skip_update_environment_disables_network_check(tmp_path):
    local = _deployment(tmp_path / "local", "1.1.0")
    server = _deployment(tmp_path / "server", "9.0.0")

    status = winux_updater.get_update_status(
        str(local),
        str(server),
        environ={"WINUX_SKIP_UPDATE": "1"},
    )

    assert status["available"] is False
    assert "disabled" in status["reason"]


def test_saved_update_source_uses_shared_settings_json_without_erasing_other_keys(tmp_path):
    server = _deployment(tmp_path / "server", "1.2.0")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"auto_login": True, "other": "keep"}))

    winux_updater.save_update_source(str(server), settings_path=str(settings), environ={})

    payload = json.loads(settings.read_text())
    assert payload["auto_login"] is True
    assert payload["other"] == "keep"
    assert payload[winux_updater.UPDATE_SOURCE_KEY] == str(server.resolve())
    assert winux_updater.load_update_source(settings_path=str(settings), environ={}) == str(server.resolve())


def test_configured_source_prefers_explicit_environment_but_canonical_s_before_saved(tmp_path):
    saved = _deployment(tmp_path / "saved", "1.2.0")
    env_source = _deployment(tmp_path / "environment", "1.2.0")
    canonical = _deployment(tmp_path / "canonical", "1.3.0")
    settings = tmp_path / "settings.json"
    winux_updater.save_update_source(str(saved), settings_path=str(settings), environ={})

    assert winux_updater.configured_update_source(
        environ={"WINUX_UPDATE_SOURCE": str(env_source)}, settings_path=str(settings)
    ) == str(env_source.resolve())
    with mock.patch.object(winux_updater, "DEFAULT_NETWORK_PROJECT_DIR", str(canonical)):
        assert winux_updater.configured_update_source(
            environ={}, settings_path=str(settings)
        ) == str(canonical.resolve())


def test_saved_source_is_fallback_when_canonical_s_is_unavailable(tmp_path):
    saved = _deployment(tmp_path / "saved", "1.2.0")
    settings = tmp_path / "settings.json"
    winux_updater.save_update_source(str(saved), settings_path=str(settings), environ={})

    with mock.patch.object(
        winux_updater, "DEFAULT_NETWORK_PROJECT_DIR", str(tmp_path / "missing-canonical")
    ):
        assert winux_updater.configured_update_source(
            environ={}, settings_path=str(settings)
        ) == str(saved.resolve())


def test_newer_server_version_is_detected_even_when_manifest_is_stale(tmp_path):
    local = _deployment(tmp_path / "local", "1.3.2")
    server = _deployment(tmp_path / "server", "1.3.2")
    # Simulate the real deployment workflow that triggered the regression:
    # files/VERSION are updated on S: but the published manifest still describes
    # the previous release. Version discovery must still offer the update.
    (server / "VERSION").write_text("1.3.3\n")

    status = winux_updater.get_update_status(str(local), str(server), environ={})

    assert status["server_version"] == "1.3.3"
    assert status["available"] is True
    assert status["manifest_valid"] is False
    assert "manifest" in status["reason"]


def test_stale_manifest_source_can_still_update_transactionally_from_version_snapshot(tmp_path):
    local = _deployment(tmp_path / "local", "1.3.2", marker="old.txt")
    server = _deployment(tmp_path / "server", "1.3.2", marker="new.txt")
    (server / "VERSION").write_text("1.3.3\n")
    # Keep update_manifest.json deliberately stale at 1.3.2.

    installed = winux_updater.synchronize_project(str(server), str(local))

    assert installed == "1.3.3"
    assert winux_updater.read_version(str(local)) == "1.3.3"
    assert (local / "new.txt").is_file()
    installed_manifest = winux_update_manifest.load_manifest(str(local))
    assert installed_manifest["version"] == "1.3.3"


def test_missing_source_prompts_for_new_path_and_saves_it(tmp_path):
    local = _deployment(tmp_path / "local", "1.1.0")
    server = _deployment(tmp_path / "server", "1.1.0")
    missing = tmp_path / "missing"
    settings = tmp_path / "settings.json"
    prompts = []

    def prompt(current):
        prompts.append(current)
        return str(server)

    status = winux_updater.update_local_if_newer(
        str(local),
        server_dir=str(missing),
        environ={},
        source_prompt=prompt,
        invalid_source_dialog=mock.Mock(),
        settings_path=str(settings),
    )

    assert len(prompts) == 1
    assert status["cancelled"] is False
    assert status["available"] is False
    assert winux_updater.load_update_source(settings_path=str(settings), environ={}) == str(server.resolve())


def test_missing_source_cancel_uses_local_version(tmp_path):
    local = _deployment(tmp_path / "local", "1.1.0")
    settings = tmp_path / "settings.json"

    status = winux_updater.update_local_if_newer(
        str(local),
        server_dir=str(tmp_path / "missing"),
        environ={},
        source_prompt=lambda _current: None,
        settings_path=str(settings),
    )

    assert status["cancelled"] is True
    assert status["updated"] is False
    assert "using local" in status["reason"]


def test_invalid_replacement_path_reprompts_until_valid(tmp_path):
    local = _deployment(tmp_path / "local", "1.1.0")
    server = _deployment(tmp_path / "server", "1.1.0")
    invalid = tmp_path / "invalid"
    invalid.mkdir()
    values = iter([str(invalid), str(server)])
    invalid_dialog = mock.Mock()

    status = winux_updater.update_local_if_newer(
        str(local),
        server_dir=str(tmp_path / "missing"),
        environ={},
        source_prompt=lambda _current: next(values),
        invalid_source_dialog=invalid_dialog,
        settings_path=str(tmp_path / "settings.json"),
    )

    assert status["cancelled"] is False
    invalid_dialog.assert_called_once()


def test_synchronize_project_replaces_complete_local_tree_and_reports_progress(tmp_path):
    local = _deployment(tmp_path / "WinUx", "1.1.0", marker="old_only.txt")
    server = _deployment(tmp_path / "Server", "1.2.0", marker="new_only.txt")
    (server / "vendor").mkdir()
    (server / "vendor" / "dependency.txt").write_text("new dependency\n")
    winux_update_manifest.write_manifest(str(server))
    progress = []

    installed_version = winux_updater.synchronize_project(
        str(server), str(local), progress_callback=lambda percent, text: progress.append((percent, text))
    )

    assert installed_version == "1.2.0"
    assert winux_updater.read_version(str(local)) == "1.2.0"
    assert not (local / "old_only.txt").exists()
    assert (local / "new_only.txt").is_file()
    assert (local / "vendor" / "dependency.txt").is_file()
    assert progress[-1][0] == 100
    assert any("Validating" in text for _percent, text in progress)
    assert any("Installing" in text for _percent, text in progress)


def test_update_now_dialog_is_shown_before_progress_and_synchronization(tmp_path):
    local = _deployment(tmp_path / "local", "1.1.0")
    server = _deployment(tmp_path / "server", "1.2.0")
    events = []

    def dialog(local_version, server_version, server_dir):
        events.append(("dialog", local_version, server_version, server_dir))
        return True

    class Progress(object):
        def __init__(self):
            events.append(("progress_open",))

        def update(self, percent, message):
            events.append(("progress", percent, message))

        def close(self):
            events.append(("progress_close",))

    def sync(server_dir, local_dir, progress_callback=None):
        events.append(("sync", server_dir, local_dir))
        progress_callback(50, "Copying")
        return "1.2.0"

    status = winux_updater.update_local_if_newer(
        str(local),
        server_dir=str(server),
        environ={},
        dialog_available=dialog,
        dialog_failed=mock.Mock(),
        sync_callable=sync,
        progress_factory=lambda _local, _server: Progress(),
        settings_path=str(tmp_path / "settings.json"),
    )

    assert status["updated"] is True
    assert [event[0] for event in events] == [
        "dialog",
        "progress_open",
        "progress",
        "progress",
        "sync",
        "progress",
        "progress",
        "progress_close",
    ]
    assert events[2][1:] == (0, "Preparing update...")
    assert events[3][1:] == (2, "Starting file synchronization...")
    assert events[-2][1:] == (100, "Update complete. Starting WinUx...")
    assert status["local_version"] == "1.2.0"


def test_update_cancel_does_not_copy_and_keeps_old_local_version(tmp_path):
    local = _deployment(tmp_path / "local", "1.1.0")
    server = _deployment(tmp_path / "server", "1.2.0")
    sync = mock.Mock()
    progress = mock.Mock()

    status = winux_updater.update_local_if_newer(
        str(local),
        server_dir=str(server),
        environ={},
        dialog_available=lambda *_args: False,
        sync_callable=sync,
        progress_factory=progress,
        settings_path=str(tmp_path / "settings.json"),
    )

    assert status["cancelled"] is True
    assert status["updated"] is False
    assert winux_updater.read_version(str(local)) == "1.1.0"
    sync.assert_not_called()
    progress.assert_not_called()


def test_failed_update_closes_progress_and_keeps_startup_recoverable(tmp_path):
    local = _deployment(tmp_path / "local", "1.1.0")
    server = _deployment(tmp_path / "server", "1.2.0")
    failed_dialog = mock.Mock()
    progress = mock.Mock()

    def fail_sync(_server_dir, _local_dir, progress_callback=None):
        progress_callback(20, "Copying")
        raise IOError("network copy failed")

    status = winux_updater.update_local_if_newer(
        str(local),
        server_dir=str(server),
        environ={},
        dialog_available=lambda *_args: True,
        dialog_failed=failed_dialog,
        sync_callable=fail_sync,
        progress_factory=lambda _local, _server: progress,
        settings_path=str(tmp_path / "settings.json"),
    )

    assert status["updated"] is False
    assert "network copy failed" in status["error"]
    assert winux_updater.read_version(str(local)) == "1.1.0"
    progress.update.assert_called()
    progress.close.assert_called_once()
    failed_dialog.assert_called_once()


def test_cancelled_update_is_offered_again_on_next_launch(tmp_path):
    """Cancel is session-only; it must never suppress the same server version."""
    local = _deployment(tmp_path / "local", "1.1.0")
    server = _deployment(tmp_path / "server", "1.2.0")
    settings = tmp_path / "settings.json"
    prompts = []

    def cancel_dialog(local_version, server_version, server_dir):
        prompts.append((local_version, server_version, server_dir))
        return False

    first = winux_updater.update_local_if_newer(
        str(local), server_dir=str(server), environ={},
        dialog_available=cancel_dialog, settings_path=str(settings),
    )
    second = winux_updater.update_local_if_newer(
        str(local), server_dir=str(server), environ={},
        dialog_available=cancel_dialog, settings_path=str(settings),
    )

    assert first["cancelled"] is True
    assert second["cancelled"] is True
    assert winux_updater.read_version(str(local)) == "1.1.0"
    assert len(prompts) == 2
    # Cancelling an update must not persist any dismissed/ignored version.
    payload = json.loads(settings.read_text()) if settings.exists() else {}
    assert set(payload).issubset({winux_updater.UPDATE_SOURCE_KEY})


def test_update_now_runs_before_sync_hook_only_after_acceptance(tmp_path):
    local = _deployment(tmp_path / "local", "1.1.0")
    server = _deployment(tmp_path / "server", "1.2.0")
    events = []

    def accepted(*_args):
        events.append("accepted")
        return True

    def before_sync():
        events.append("before_sync")

    def sync(source, destination, progress_callback=None):
        events.append("sync")
        return "1.2.0"

    class Progress(object):
        def __init__(self):
            events.append("progress_open")
        def update(self, percent, message):
            events.append(("progress", percent, message))
        def close(self):
            events.append("progress_close")

    status = winux_updater.update_local_if_newer(
        str(local), server_dir=str(server), environ={},
        dialog_available=accepted,
        before_sync=before_sync,
        sync_callable=sync,
        progress_factory=lambda *_args: Progress(),
        settings_path=str(tmp_path / "settings.json"),
    )

    assert status["updated"] is True
    assert events[0:2] == ["accepted", "progress_open"]
    assert events[2] == ("progress", 0, "Preparing update...")
    assert events[3] == ("progress", 1, "Closing the current WinUx instance...")
    assert events[4] == "before_sync"
    assert events[5] == ("progress", 2, "Starting file synchronization...")
    assert events[6] == "sync"
    assert events[7] == ("progress", 100, "Update complete. Starting WinUx...")
    assert events[8] == "progress_close"
