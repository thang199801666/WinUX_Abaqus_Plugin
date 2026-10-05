import json
import os
from pathlib import Path

import winux_installation_state as state
import winux_update_diagnostics as diagnostics
import winux_update_providers as providers


def release(tag, prerelease=False, draft=False):
    return {"tag_name": tag, "prerelease": prerelease, "draft": draft, "assets": []}


def test_stable_channel_selects_highest_non_prerelease():
    provider = providers.GitHubReleaseProvider("acme/WinUx", channel="stable", environ={})
    selected = provider._select_release([
        release("v1.6.49-beta.1", prerelease=True),
        release("v1.6.47"),
        release("not-a-version"),
        release("v1.6.48"),
    ])
    assert selected["tag_name"] == "v1.6.48"


def test_beta_channel_selects_highest_semantic_version_including_prerelease():
    provider = providers.GitHubReleaseProvider("acme/WinUx", channel="beta", environ={})
    selected = provider._select_release([
        release("v1.6.48"),
        release("v1.6.49-beta.1", prerelease=True),
        release("v1.6.47"),
    ])
    assert selected["tag_name"] == "v1.6.49-beta.1"


def test_cache_cleanup_expires_old_partial_and_packages(tmp_path):
    provider = providers.GitHubReleaseProvider("acme/WinUx", cache_dir=str(tmp_path), environ={})
    old_zip = tmp_path / "old.zip"
    recent_zip = tmp_path / "recent.zip"
    old_partial = tmp_path / "download.zip.partial"
    old_zip.write_bytes(b"old")
    recent_zip.write_bytes(b"recent")
    old_partial.write_bytes(b"partial")
    now = 10_000_000.0
    old = now - 40 * 24 * 60 * 60
    recent = now - 2 * 24 * 60 * 60
    os.utime(str(old_zip), (old, old))
    os.utime(str(old_partial), (old, old))
    os.utime(str(recent_zip), (recent, recent))
    removed = provider.cleanup_cache(keep_packages=3, package_max_age_days=30,
                                     partial_max_age_days=7, staging_max_age_hours=24,
                                     now=now)
    assert str(old_zip) in removed
    assert str(old_partial) in removed
    assert recent_zip.exists()


def test_diagnostics_reports_state_quarantine_and_cache(tmp_path):
    env = {"LOCALAPPDATA": str(tmp_path)}
    state.write_state("1.6.48", ["1.6.47"], environ=env, reason="test")
    state.quarantine_version("1.6.49-beta.1", "a" * 64, "health failure", environ=env)
    cache = tmp_path / "WinUx" / "cache" / "updates"
    cache.mkdir(parents=True)
    (cache / "cached.zip").write_bytes(b"1234")
    snap = diagnostics.collect_update_diagnostics(environ=env)
    assert snap["active_version"] == "1.6.48"
    assert snap["previous_versions"] == ["1.6.47"]
    assert "1.6.49-beta.1" in snap["quarantine"]
    assert snap["cache"]["bytes"] == 4
    text = diagnostics.format_update_diagnostics(snap)
    assert "Active: 1.6.48" in text
    assert "Quarantined: 1.6.49-beta.1" in text
