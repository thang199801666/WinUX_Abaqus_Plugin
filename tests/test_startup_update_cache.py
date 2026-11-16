import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from winux_runtime.startup_update_cache import (
    cached_startup_status,
    record_startup_status,
)


class StartupUpdateCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = self.root / "app"
        self.project.mkdir()
        (self.project / "VERSION").write_text("1.2.3", encoding="utf-8")
        (self.project / "update_manifest.json").write_text(
            json.dumps({"version": "1.2.3", "package_revision": 7,
                        "package_sha256": "a" * 64}),
            encoding="utf-8",
        )
        self.env = {
            "LOCALAPPDATA": str(self.root / "local"),
            "APPDATA": str(self.root / "roaming"),
            "WINUX_STARTUP_UPDATE_CACHE_SECONDS": "3600",
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _status(self):
        return {
            "local_version": "1.2.3",
            "server_version": "1.2.3",
            "provider": "github",
            "source_label": "GitHub Releases: test/repo",
            "available": False,
            "updated": False,
            "cancelled": False,
            "error": None,
            "manifest_error": None,
        }

    def test_recent_successful_no_update_result_is_reused(self):
        self.assertTrue(record_startup_status(
            str(self.project), self._status(), environ=self.env, now=100.0))
        cached = cached_startup_status(
            str(self.project), environ=self.env, now=200.0)
        self.assertIsNotNone(cached)
        self.assertTrue(cached["cached"])
        self.assertFalse(cached["available"])
        self.assertEqual(cached["server_version"], "1.2.3")

    def test_version_or_revision_change_invalidates_cache(self):
        self.assertTrue(record_startup_status(
            str(self.project), self._status(), environ=self.env, now=100.0))
        (self.project / "update_manifest.json").write_text(
            json.dumps({"version": "1.2.3", "package_revision": 8,
                        "package_sha256": "a" * 64}),
            encoding="utf-8",
        )
        self.assertIsNone(cached_startup_status(
            str(self.project), environ=self.env, now=110.0))


    def test_manifest_digest_or_version_change_invalidates_cache(self):
        self.assertTrue(record_startup_status(
            str(self.project), self._status(), environ=self.env, now=100.0))
        (self.project / "update_manifest.json").write_text(
            json.dumps({"version": "1.2.3", "package_revision": 7,
                        "package_sha256": "b" * 64}),
            encoding="utf-8",
        )
        self.assertIsNone(cached_startup_status(
            str(self.project), environ=self.env, now=110.0))

        # A manifest from another VERSION is stale identity, even when the
        # package revision happens to be the same.
        (self.project / "update_manifest.json").write_text(
            json.dumps({"version": "1.2.2", "package_revision": 7,
                        "package_sha256": "b" * 64}),
            encoding="utf-8",
        )
        self.assertIsNone(cached_startup_status(
            str(self.project), environ=self.env, now=120.0))

    def test_expired_or_forced_check_bypasses_cache(self):
        self.assertTrue(record_startup_status(
            str(self.project), self._status(), environ=self.env, now=100.0))
        self.assertIsNone(cached_startup_status(
            str(self.project), environ=self.env, now=5000.0))
        forced = dict(self.env)
        forced["WINUX_FORCE_UPDATE_CHECK"] = "1"
        self.assertIsNone(cached_startup_status(
            str(self.project), environ=forced, now=110.0))

    def test_settings_or_provider_override_change_invalidates_cache(self):
        settings = Path(self.env["APPDATA"]) / "WinUX" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text("{}", encoding="utf-8")
        self.assertTrue(record_startup_status(
            str(self.project), self._status(), environ=self.env, now=100.0))
        # Ensure both size and timestamp differ on filesystems with coarse mtimes.
        settings.write_text('{"update_provider":"folder"}', encoding="utf-8")
        stat = settings.stat()
        os.utime(str(settings), (stat.st_atime, stat.st_mtime + 2.0))
        self.assertIsNone(cached_startup_status(
            str(self.project), environ=self.env, now=110.0))

        # A fresh cache under the current settings also invalidates when an
        # environment override selects a different provider.
        self.assertTrue(record_startup_status(
            str(self.project), self._status(), environ=self.env, now=120.0))
        changed = dict(self.env)
        changed["WINUX_UPDATE_PROVIDER"] = "folder"
        self.assertIsNone(cached_startup_status(
            str(self.project), environ=changed, now=130.0))

    def test_failed_or_available_status_is_never_cached(self):
        failed = self._status()
        failed["error"] = "offline"
        self.assertFalse(record_startup_status(
            str(self.project), failed, environ=self.env, now=100.0))
        available = self._status()
        available["available"] = True
        available["server_version"] = "1.2.4"
        self.assertFalse(record_startup_status(
            str(self.project), available, environ=self.env, now=100.0))


if __name__ == "__main__":
    unittest.main()
