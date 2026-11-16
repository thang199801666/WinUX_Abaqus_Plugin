import json
import os
import tempfile
import unittest
from pathlib import Path

from winux_runtime.update import updater
from winux_runtime.update.providers import (
    DEFAULT_GITHUB_REPOSITORY,
    PROVIDER_GITHUB,
    update_preferences,
)
from WinUx.preferences.update import UpdatePreferences
from winux_runtime import startup_update_cache as startup_cache


class _FailingGitHubProvider(object):
    def __init__(self, repository=None, channel=None, api_base=None, environ=None):
        self.repository = repository

    def check(self, local_version):
        raise RuntimeError("offline for regression test")


class UpdateNoSDriveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.local = self.root / "WinUx"
        self.local.mkdir()
        (self.local / "VERSION").write_text("1.2.3", encoding="utf-8")
        self.settings = self.root / "settings.json"
        self.settings.write_text(json.dumps({
            "update_provider": "folder",
            "update_source": r"S:\\WinUx",
        }), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_legacy_folder_settings_migrate_to_github(self):
        prefs = update_preferences({
            "update_provider": "folder",
            "update_source": r"S:\\WinUx",
        }, environ={})
        self.assertEqual(prefs["provider"], PROVIDER_GITHUB)
        self.assertEqual(prefs["github_repository"], DEFAULT_GITHUB_REPOSITORY)

    def test_manual_check_does_not_fall_back_to_shared_drive(self):
        original = updater.get_update_status
        updater.get_update_status = lambda *a, **k: self.fail("shared-folder status must not run")
        try:
            result = updater.check_for_updates(
                str(self.local), environ={}, settings_path=str(self.settings),
                github_provider_factory=_FailingGitHubProvider,
            )
        finally:
            updater.get_update_status = original
        self.assertEqual(result["provider"], PROVIDER_GITHUB)
        self.assertFalse(result["available"])
        self.assertIn("shared-drive fallback disabled", result["reason"])

    def test_startup_update_does_not_resolve_s_drive_after_github_failure(self):
        original = updater._resolve_interactive_source
        updater._resolve_interactive_source = lambda *a, **k: self.fail("S:/folder resolver must not run")
        try:
            result = updater.update_local_if_newer(
                str(self.local), environ={}, settings_path=str(self.settings),
                github_provider_factory=_FailingGitHubProvider,
            )
        finally:
            updater._resolve_interactive_source = original
        self.assertEqual(result["provider"], PROVIDER_GITHUB)
        self.assertFalse(result["available"])
        self.assertIn("shared-drive fallback disabled", result["reason"])


    def test_old_folder_startup_cache_is_ignored(self):
        env = {
            "LOCALAPPDATA": str(self.root / "localapp"),
            "APPDATA": str(self.root / "appdata"),
            "WINUX_STARTUP_UPDATE_CACHE_SECONDS": "3600",
        }
        payload = startup_cache._identity(str(self.local), env)
        payload.update({
            "checked_at": 100.0,
            "provider": "folder",
            "source_label": r"Legacy shared folder: S:\\WinUx",
            "server_version": "1.2.3",
        })
        cache_path = Path(startup_cache._cache_path(env))
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertIsNone(startup_cache.cached_startup_status(
            str(self.local), environ=env, now=101.0))

    def test_saving_preferences_removes_stale_update_source(self):
        profile = self.root / "profile"
        profile.mkdir()
        pref = UpdatePreferences(root=profile)
        pref._store.save({
            "update_provider": "folder",
            "update_source": r"S:\\WinUx",
        })
        saved = pref.save(
            provider="github",
            github_repository=DEFAULT_GITHUB_REPOSITORY,
            channel="stable",
            legacy_source=r"S:\\WinUx",
        )
        raw = pref._store.load()
        self.assertEqual(saved["provider"], "github")
        self.assertNotIn("update_source", raw)


if __name__ == "__main__":
    unittest.main()
