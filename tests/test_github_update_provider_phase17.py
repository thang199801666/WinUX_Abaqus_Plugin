import hashlib
import io
import json
import os
import zipfile
from unittest import mock

import pytest

import winux_update_manifest
import winux_update_providers as providers
import winux_updater


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


def _zip_bytes(root):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.write(str(path), str(path.relative_to(root)).replace(os.sep, "/"))
    return stream.getvalue()


class _Response(io.BytesIO):
    def close(self):
        super().close()


class _FakeOpener(object):
    def __init__(self, payloads):
        self.payloads = payloads
        self.urls = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.urls.append((url, timeout))
        payload = self.payloads[url]
        if not isinstance(payload, bytes):
            payload = json.dumps(payload).encode("utf-8")
        return _Response(payload)


def test_legacy_users_remain_folder_provider_until_github_repository_is_configured():
    prefs = providers.update_preferences({"update_source": r"S:\\WinUx"}, environ={})
    assert prefs["provider"] == "auto"
    assert prefs["github_repository"] is None
    assert providers.should_use_github(prefs) is False


def test_github_repository_enables_github_in_auto_mode():
    prefs = providers.update_preferences(
        {"github_repository": "https://github.com/acme/WinUx.git"}, environ={}
    )
    assert prefs["github_repository"] == "acme/WinUx"
    assert providers.should_use_github(prefs) is True


def test_explicit_folder_source_overrides_github_auto_mode():
    prefs = providers.update_preferences(
        {"github_repository": "acme/WinUx"}, environ={}
    )
    assert providers.should_use_github(prefs, explicit_folder_source=True) is False


def test_update_preferences_are_saved_without_erasing_legacy_s_drive_setting(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"update_source": r"S:\\Shared\\WinUx", "auto_login": True}))

    winux_updater.save_update_preferences(
        provider="auto",
        github_repository="acme/WinUx",
        channel="stable",
        settings_path=str(settings),
        environ={},
    )

    payload = json.loads(settings.read_text())
    assert payload["update_source"] == r"S:\\Shared\\WinUx"
    assert payload["auto_login"] is True
    assert payload["update_provider"] == "auto"
    assert payload["github_repository"] == "acme/WinUx"
    assert payload["update_channel"] == "stable"


def test_github_provider_discovers_verified_release_and_materializes_complete_deployment(tmp_path):
    deployment = _deployment(tmp_path / "release", "1.6.44", marker="new_file.txt")
    package = _zip_bytes(deployment)
    checksum = hashlib.sha256(package).hexdigest()

    api = "https://api.github.test"
    releases_url = api + "/repos/acme/WinUx/releases?per_page=20"
    metadata_url = "https://downloads.test/winux-release.json"
    package_url = "https://downloads.test/WinUx_1.6.44_FULL.zip"
    release = {
        "tag_name": "v1.6.44",
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": "winux-release.json",
                "browser_download_url": metadata_url,
                "url": metadata_url,
                "size": 200,
            },
            {
                "name": "WinUx_1.6.44_FULL.zip",
                "browser_download_url": package_url,
                "url": package_url,
                "size": len(package),
            },
        ],
    }
    metadata = {
        "schema_version": 2,
        "product_id": "com.winux.desktop",
        "version": "1.6.44",
        "package": {
            "asset": "WinUx_1.6.44_FULL.zip",
            "sha256": checksum,
        },
    }
    opener = _FakeOpener(
        {
            releases_url: [release],
            metadata_url: metadata,
            package_url: package,
        }
    )
    provider = providers.GitHubReleaseProvider(
        "acme/WinUx",
        api_base=api,
        opener=opener,
        cache_dir=str(tmp_path / "cache"),
        environ={},
    )

    candidate = provider.check("1.6.43")
    assert candidate["available"] is True
    assert candidate["server_version"] == "1.6.44"
    assert candidate["package_sha256"] == checksum

    materialized = provider.materialize(candidate)
    try:
        source = materialized["source_dir"]
        assert winux_update_manifest.read_version(source) == "1.6.44"
        assert os.path.isfile(os.path.join(source, "new_file.txt"))
        assert winux_update_manifest.source_descriptor(source, verify_hashes=True)["version"] == "1.6.44"
    finally:
        provider.cleanup_materialized(materialized)


def test_github_provider_rejects_zip_path_traversal(tmp_path):
    package = tmp_path / "bad.zip"
    with zipfile.ZipFile(str(package), "w") as archive:
        archive.writestr("../escape.txt", "bad")
    with pytest.raises(RuntimeError, match="Unsafe parent path"):
        providers.safe_extract_zip(str(package), str(tmp_path / "extract"))
    assert not (tmp_path / "escape.txt").exists()


def test_auto_mode_falls_back_to_legacy_s_provider_when_github_is_unavailable(tmp_path):
    local = _deployment(tmp_path / "local", "1.0.0")
    legacy = _deployment(tmp_path / "legacy", "1.0.0")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "update_provider": "auto",
        "github_repository": "acme/WinUx",
        "update_source": str(legacy),
    }))

    class BrokenProvider(object):
        def __init__(self, **_kwargs):
            pass

        def check(self, _local_version):
            raise RuntimeError("offline")

    with mock.patch.object(winux_updater, "DEFAULT_NETWORK_PROJECT_DIR", str(tmp_path / "missing-s")):
        status = winux_updater.update_local_if_newer(
            str(local),
            environ={},
            settings_path=str(settings),
            github_provider_factory=BrokenProvider,
            source_prompt=lambda _current: None,
        )

    assert status["available"] is False
    assert status["local_version"] == "1.0.0"
    assert "current" in status["reason"]


def test_forced_github_failure_never_prompts_for_s_drive_and_uses_local_version(tmp_path):
    local = _deployment(tmp_path / "local", "1.0.0")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "update_provider": "github",
        "github_repository": "acme/WinUx",
        "update_source": r"S:\\old\\WinUx",
    }))
    source_prompt = mock.Mock()

    class BrokenProvider(object):
        def __init__(self, **_kwargs):
            pass

        def check(self, _local_version):
            raise RuntimeError("GitHub unavailable")

    status = winux_updater.update_local_if_newer(
        str(local),
        environ={},
        settings_path=str(settings),
        github_provider_factory=BrokenProvider,
        source_prompt=source_prompt,
    )

    assert status["provider"] == "github"
    assert status["updated"] is False
    assert "unavailable" in status["reason"].lower()
    source_prompt.assert_not_called()


def test_github_update_reuses_transactional_sync_and_replaces_obsolete_files(tmp_path):
    local = _deployment(tmp_path / "local", "1.0.0", marker="obsolete.txt")
    release = _deployment(tmp_path / "release", "1.1.0", marker="new_module.py")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "update_provider": "github",
        "github_repository": "acme/WinUx",
    }))

    class Provider(object):
        def __init__(self, **_kwargs):
            self.source_label = "GitHub Releases: acme/WinUx (stable)"

        def check(self, local_version):
            return {
                "provider": "github",
                "source_label": self.source_label,
                "repository": "acme/WinUx",
                "local_version": local_version,
                "server_version": "1.1.0",
                "available": local_version != "1.1.0",
                "reason": "newer GitHub release available" if local_version != "1.1.0" else "local version is current",
            }

        def materialize(self, _candidate, progress_callback=None):
            if progress_callback:
                progress_callback(100, "ready")
            return {"source_dir": str(release), "cleanup_dir": None}

        def cleanup_materialized(self, _materialized):
            return None

    class Progress(object):
        def update(self, _percent, _message):
            pass

        def close(self):
            pass

    status = winux_updater.update_local_if_newer(
        str(local),
        environ={"LOCALAPPDATA": str(tmp_path / "profile")},
        settings_path=str(settings),
        github_provider_factory=Provider,
        dialog_available=lambda *_args: True,
        progress_factory=lambda *_args: Progress(),
        # This fixture is a synthetic flat deployment, not an executable app.
        sync_callable=winux_updater.synchronize_project,
        health_check=lambda *_args: True,
    )

    assert status["updated"] is True
    assert winux_update_manifest.read_version(str(local)) == "1.1.0"
    assert not (local / "obsolete.txt").exists()
    assert (local / "new_module.py").is_file()


def test_application_update_preferences_keep_legacy_source_and_normalize_repo(tmp_path):
    from WinUx.preferences.update import UpdatePreferences

    prefs = UpdatePreferences(root=tmp_path)
    saved = prefs.save(
        provider="auto",
        github_repository="https://github.com/acme/WinUx.git",
        channel="stable",
        legacy_source=r"S:\\Shared\\WinUx",
    )
    assert saved == {
        "provider": "auto",
        "github_repository": "acme/WinUx",
        "channel": "stable",
        "legacy_source": r"S:\\Shared\\WinUx",
    }
    payload = json.loads(prefs.path.read_text())
    assert payload["update_source"] == r"S:\\Shared\\WinUx"


def test_settings_form_exposes_github_and_legacy_s_provider_controls():
    from pathlib import Path

    source = (Path(__file__).parents[1] / "WinUx" / "dialogs" / "settings_form.py").read_text()
    for token in (
        '"Updates"',
        '"GitHub repository"',
        '"Shared folder fallback"',
        'UpdatePreferences.DEFAULT_LEGACY_SOURCE',
        '"Automatic (GitHub, then shared folder fallback)"',
    ):
        assert token in source


def test_skip_update_disables_github_provider_too(tmp_path):
    local = _deployment(tmp_path / "local", "1.0.0")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "update_provider": "github",
        "github_repository": "acme/WinUx",
    }))

    factory = mock.Mock(side_effect=AssertionError("GitHub must not be touched"))
    status = winux_updater.update_local_if_newer(
        str(local),
        environ={"WINUX_SKIP_UPDATE": "1"},
        settings_path=str(settings),
        github_provider_factory=factory,
    )
    assert status["available"] is False
    assert "disabled" in status["reason"]
    factory.assert_not_called()
