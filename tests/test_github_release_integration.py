import hashlib
import io
import json
import zipfile

import pytest

from WinUx.preferences.update import UpdatePreferences
from tools.build_github_release import build_release
from winux_update_manifest import REQUIRED_FILES, source_descriptor
from winux_update_providers import (
    DEFAULT_GITHUB_REPOSITORY, GitHubReleaseProvider, safe_extract_zip,
    should_use_github, update_preferences,
)


def test_new_install_and_settings_use_product_repository(tmp_path):
    bootstrap = update_preferences({}, environ={})
    app = UpdatePreferences(root=tmp_path).load()
    assert bootstrap["github_repository"] == DEFAULT_GITHUB_REPOSITORY
    assert app["github_repository"] == DEFAULT_GITHUB_REPOSITORY
    assert should_use_github(bootstrap)


def test_legacy_source_and_explicit_opt_out_are_preserved(tmp_path):
    prefs = UpdatePreferences(root=tmp_path)
    prefs._store.save({"update_source": r"S:\WinUx"})
    assert prefs.load()["github_repository"] == ""
    assert update_preferences({"update_source": r"S:\WinUx"}, environ={})["github_repository"] is None
    forced = update_preferences({"update_source": r"S:\WinUx", "update_provider": "github"}, environ={})
    assert forced["github_repository"] == DEFAULT_GITHUB_REPOSITORY
    prefs.save(provider="auto", github_repository="", channel="stable", legacy_source="")
    assert prefs.load()["github_repository"] == ""
    assert not should_use_github(update_preferences(prefs._store.load(), environ={}))


def test_built_package_is_consumable_by_github_provider(tmp_path):
    source = tmp_path / "source"
    for relative in REQUIRED_FILES:
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("1.1.0\n" if relative == "VERSION" else "# deployment\n")
    (source / "vendor").mkdir()
    (source / "vendor" / "dependency.py").write_text("# required runtime\n")
    (source / "update_manifest.json").write_text('{"stale": true}')
    (source / "tests").mkdir()
    (source / "tests" / "test_dev.py").write_text("# not runtime\n")
    package, metadata_path, checksum_path = build_release(str(source), str(tmp_path / "output"), "v1.1.0")
    metadata = json.loads(open(metadata_path).read())
    digest = hashlib.sha256(open(package, "rb").read()).hexdigest()
    assert metadata["package"]["sha256"] == digest
    assert open(checksum_path).read().startswith(digest)
    assert metadata["channel"] == "stable"
    with zipfile.ZipFile(package) as archive:
        assert "vendor/dependency.py" in archive.namelist()
        assert "tests/test_dev.py" not in archive.namelist()
    extracted = tmp_path / "extracted"
    safe_extract_zip(package, str(extracted))
    assert source_descriptor(str(extracted), verify_hashes=True)["version"] == "1.1.0"

    release = {"tag_name": "v1.1.0", "assets": [
        {"name": "winux-release.json", "browser_download_url": "https://test/metadata"},
        {"name": metadata["package"]["asset"], "browser_download_url": "https://test/package"},
    ]}
    provider = GitHubReleaseProvider(DEFAULT_GITHUB_REPOSITORY, environ={})
    provider._list_releases = lambda: [release]
    provider._download_bytes = lambda asset: json.dumps(metadata).encode("utf-8")
    assert provider.check("1.0.0")["available"]
    assert not provider.check("1.1.0")["available"]
    assert (source / "update_manifest.json").read_text() == '{"stale": true}'


def test_release_builder_rejects_wrong_tag_and_nested_output(tmp_path):
    (tmp_path / "VERSION").write_text("1.1.0\n")
    with pytest.raises(ValueError, match="does not match VERSION"):
        build_release(str(tmp_path), str(tmp_path.parent / "output"), "v2.0.0")
    with pytest.raises(ValueError, match="outside the source"):
        build_release(str(tmp_path), str(tmp_path / "dist"))


def test_manual_winux_release_uses_github_sha256_digest():
    checksum = "a" * 64
    release = {
        "tag_name": "WinUx-1.1.1", "prerelease": False,
        "assets": [{"name": "WinUx-1.1.1.zip", "digest": "sha256:" + checksum}],
    }
    provider = GitHubReleaseProvider(DEFAULT_GITHUB_REPOSITORY, environ={})
    provider._list_releases = lambda: [release]
    candidate = provider.check("1.1.0")
    assert candidate["available"]
    assert candidate["server_version"] == "1.1.1"
    assert candidate["package_sha256"] == checksum
    assert candidate["package_asset"]["name"] == "WinUx-1.1.1.zip"
    assert not provider.check("1.1.1")["available"]


@pytest.mark.parametrize("digest", [None, "md5:" + "a" * 32, "sha256:invalid"])
def test_manual_release_requires_valid_sha256_digest(digest):
    provider = GitHubReleaseProvider(DEFAULT_GITHUB_REPOSITORY, environ={})
    provider._list_releases = lambda: [{
        "tag_name": "WinUx-1.1.1",
        "assets": [{"name": "WinUx-1.1.1.zip", "digest": digest}],
    }]
    with pytest.raises(RuntimeError, match="SHA-256 metadata"):
        provider.check("1.1.0")


def test_manual_release_rebuilds_stale_manifest_only_after_zip_verification(tmp_path):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for relative in REQUIRED_FILES:
            archive.writestr(relative.replace("\\", "/"), "1.1.1\n" if relative == "VERSION" else "# runtime\n")
        archive.writestr("update_manifest.json", '{"stale": true}')
    package = stream.getvalue()
    release = {"tag_name": "WinUx-1.1.1", "assets": [{
        "name": "WinUx-1.1.1.zip", "digest": "sha256:" + hashlib.sha256(package).hexdigest(),
        "size": len(package), "browser_download_url": "https://test/package",
    }]}
    provider = GitHubReleaseProvider(
        DEFAULT_GITHUB_REPOSITORY, environ={}, cache_dir=str(tmp_path / "cache"),
        opener=lambda *_args: io.BytesIO(package),
    )
    provider._list_releases = lambda: [release]
    candidate = provider.check("1.1.0")
    assert candidate["github_digest_contract"]
    materialized = provider.materialize(candidate)
    try:
        assert source_descriptor(materialized["source_dir"], verify_hashes=True)["version"] == "1.1.1"
    finally:
        provider.cleanup_materialized(materialized)

    # A package cannot change its version merely by being renamed on GitHub.
    candidate["server_version"] = "1.1.2"
    with pytest.raises(RuntimeError, match="VERSION .* does not match release"):
        provider.materialize(candidate)
