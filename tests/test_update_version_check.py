"""Regression guards for WinUx semantic-version update discovery."""
from pathlib import Path
import tempfile
import unittest

from winux_runtime.update.manifest import compare_versions, load_manifest, read_version
from winux_runtime.update.providers import GitHubReleaseProvider
from winux_runtime.update import updater
from WinUx.dialogs.settings.settings_form import SettingsDialog


ROOT = Path(__file__).resolve().parents[1]


def _release(tag, prerelease=False, draft=False):
    return {
        "tag_name": tag,
        "draft": bool(draft),
        "prerelease": bool(prerelease),
        "assets": [],
        "html_url": "https://example.invalid/{}".format(tag),
        "published_at": "2026-11-05T00:00:00Z",
    }


class _RecordingProvider(object):
    seen_local_version = None

    def __init__(self, repository=None, channel=None, api_base=None, environ=None):
        self.repository = repository
        self.channel = channel or "stable"

    def check(self, local_version):
        type(self).seen_local_version = local_version
        return {
            "provider": "github",
            "source_label": "GitHub Releases: test/repository",
            "repository": self.repository,
            "channel": self.channel,
            "local_version": local_version,
            "server_version": "1.1.7",
            "available": False,
            "reason": "local version is newer than latest GitHub release",
        }


class UpdateVersionCheckTests(unittest.TestCase):
    def provider(self, channel="stable"):
        return GitHubReleaseProvider(
            "owner/repository", channel=channel, environ={}
        )

    def test_product_version_matches_manifest_version(self):
        self.assertEqual(read_version(str(ROOT)), load_manifest(str(ROOT))["version"])

    def test_semantic_comparison_handles_two_digit_patch_and_prerelease(self):
        self.assertGreater(compare_versions("1.1.10", "1.1.9"), 0)
        self.assertGreater(compare_versions("1.10.0", "1.9.99"), 0)
        self.assertEqual(compare_versions("v1.1.10", "1.1.10+build.4"), 0)
        self.assertGreater(compare_versions("1.1.10", "1.1.10-rc.1"), 0)
        self.assertLess(compare_versions("1.1.10-beta.2", "1.1.10-beta.10"), 0)

    def test_stable_channel_chooses_highest_non_prerelease_version(self):
        provider = self.provider("stable")
        releases = [
            _release("v1.1.9"),
            _release("v1.2.0-beta.1", prerelease=True),
            _release("WinUx-v1.1.10"),
            _release("not-a-version"),
            _release("v9.0.0", draft=True),
        ]
        selected = provider._select_release(releases)
        self.assertEqual(provider._version_from_release(selected), "1.1.10")

    def test_beta_channel_chooses_highest_semantic_version(self):
        provider = self.provider("beta")
        releases = [
            _release("v1.1.10"),
            _release("v1.2.0-beta.2", prerelease=True),
            _release("v1.2.0-beta.10", prerelease=True),
        ]
        selected = provider._select_release(releases)
        self.assertEqual(provider._version_from_release(selected), "1.2.0-beta.10")

    def test_current_or_newer_local_version_does_not_touch_release_assets(self):
        for local_version, reason in (
            ("1.1.10", "local version is current"),
            ("1.1.11", "local version is newer than latest GitHub release"),
        ):
            provider = self.provider()
            provider._list_releases = lambda: [_release("v1.1.10")]

            def must_not_validate(*_args, **_kwargs):
                self.fail("current/newer version check must not fetch release metadata/assets")

            provider._metadata_contract = must_not_validate
            result = provider.check(local_version)
            self.assertFalse(result["available"])
            self.assertEqual(result["server_version"], "1.1.10")
            self.assertEqual(result["reason"], reason)
            self.assertIsNone(result["package_asset"])

    def test_newer_remote_release_is_fully_validated_before_offer(self):
        provider = self.provider()
        release = _release("v1.1.11")
        release["assets"] = [{"name": "WinUx_1.1.11_FULL.zip"}]
        provider._list_releases = lambda: [release]
        calls = []

        def metadata_contract(selected, version):
            calls.append((selected, version))
            return (
                {"version": version},
                {"name": "WinUx_1.1.11_FULL.zip"},
                "a" * 64,
            )

        provider._metadata_contract = metadata_contract
        result = provider.check("1.1.10")
        self.assertTrue(result["available"])
        self.assertEqual(result["server_version"], "1.1.11")
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["package_sha256"], "a" * 64)


    def test_nested_ui_path_resolves_back_to_deployment_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "WinUx"
            nested = root / "WinUx" / "dialogs" / "settings"
            nested.mkdir(parents=True)
            (root / "VERSION").write_text("1.1.10", encoding="utf-8")
            _RecordingProvider.seen_local_version = None
            result = updater.check_for_updates(
                str(nested), environ={},
                github_provider_factory=_RecordingProvider,
            )
            self.assertEqual(_RecordingProvider.seen_local_version, "1.1.10")
            self.assertEqual(result["local_version"], "1.1.10")
            self.assertEqual(Path(result["local_dir"]), root)
            self.assertFalse(result["available"])

    def test_settings_ui_never_enables_downgrade_from_inconsistent_result(self):
        dialog = SettingsDialog.__new__(SettingsDialog)
        dialog.check_updates_button = "check"
        dialog.install_update_button = "install"
        dialog._available_update = {"stale": True}
        enabled = {}
        values = {}
        statuses = []
        dialog.set_control_enabled = lambda control, state: enabled.__setitem__(control, bool(state))
        dialog.set_control_value = lambda control, value: values.__setitem__(control, value)
        dialog._set_status = lambda message, error=False: statuses.append((message, bool(error)))
        dialog.update_check_status = "status"

        SettingsDialog._finish_update_check(dialog, {
            "local_version": "1.1.10",
            "server_version": "1.1.7",
            "available": True,
            "source_label": "GitHub Releases: test/repository",
        })

        self.assertFalse(enabled["install"])
        self.assertIsNone(dialog._available_update)
        self.assertEqual(values["status"], "WinUx 1.1.10 installed. Latest release: 1.1.7.")
        self.assertNotIn("Update 1.1.7 is available", values["status"])

    def test_update_now_handler_blocks_stale_downgrade_candidate(self):
        dialog = SettingsDialog.__new__(SettingsDialog)
        dialog.install_update_button = "install"
        dialog._available_update = {
            "local_version": "1.1.10",
            "server_version": "1.1.7",
            "available": True,
        }
        enabled = {}
        statuses = []
        launched = []
        dialog.set_control_enabled = lambda control, state: enabled.__setitem__(control, bool(state))
        dialog._set_status = lambda message, error=False: statuses.append((message, bool(error)))
        dialog._on_install_update = lambda: launched.append(True)
        dialog._save_update_preferences_only = lambda: None

        SettingsDialog._install_update_now(dialog)

        self.assertFalse(enabled["install"])
        self.assertIsNone(dialog._available_update)
        self.assertFalse(launched)
        self.assertIn("not newer than the installed version", statuses[-1][0])

    def test_settings_ui_enables_only_a_strictly_newer_validated_release(self):
        dialog = SettingsDialog.__new__(SettingsDialog)
        dialog.check_updates_button = "check"
        dialog.install_update_button = "install"
        dialog._available_update = None
        enabled = {}
        values = {}
        dialog.set_control_enabled = lambda control, state: enabled.__setitem__(control, bool(state))
        dialog.set_control_value = lambda control, value: values.__setitem__(control, value)
        dialog._set_status = lambda *_args, **_kwargs: None
        dialog.update_check_status = "status"
        candidate = {
            "local_version": "1.1.10",
            "server_version": "1.1.11",
            "available": True,
            "source_label": "GitHub Releases: test/repository",
        }
        SettingsDialog._finish_update_check(dialog, candidate)
        self.assertTrue(enabled["install"])
        self.assertIs(dialog._available_update, candidate)
        self.assertEqual(values["status"], "WinUx 1.1.11 is available.")

    def test_invalid_local_version_can_recover_from_verified_release(self):
        provider = self.provider()
        release = _release("v1.1.11")
        release["assets"] = [{"name": "WinUx_1.1.11_FULL.zip"}]
        provider._list_releases = lambda: [release]
        provider._metadata_contract = lambda *_args: (
            {"version": "1.1.11"},
            {"name": "WinUx_1.1.11_FULL.zip"},
            "b" * 64,
        )
        result = provider.check("broken-version")
        self.assertTrue(result["available"])
        self.assertIn("missing or invalid", result["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
