import io
import json
from pathlib import Path

import winux_installation_state as state
import winux_update_providers as providers


class Response(io.BytesIO):
    def __init__(self, data, code=200, headers=None):
        super().__init__(data)
        self.code = code
        self.status = code
        self.headers = headers or {}


def test_public_preferences_never_resolve_or_return_credentials():
    prefs = providers.update_preferences(
        {"github_repository": "acme/WinUx", "github_credential_target": "legacy"},
        environ={"WINUX_GITHUB_TOKEN": "must-be-ignored", "GITHUB_TOKEN": "ignored"},
    )
    assert prefs["github_repository"] == "acme/WinUx"
    assert "github_token" not in prefs
    assert "github_credential_target" not in prefs
    assert "github_credential_source" not in prefs


def test_public_provider_never_adds_authorization_header():
    provider = providers.GitHubReleaseProvider("acme/WinUx", environ={})
    request = provider._request("https://example.test/file")
    headers = {k.lower(): v for k, v in request.header_items()}
    assert "authorization" not in headers


def test_quarantine_is_checksum_sensitive(tmp_path):
    env = {"LOCALAPPDATA": str(tmp_path)}
    state.quarantine_version("1.6.47", "a" * 64, "health failure", environ=env)
    assert state.is_quarantined("1.6.47", "a" * 64, environ=env)
    assert not state.is_quarantined("1.6.47", "b" * 64, environ=env)
    assert state.clear_quarantine("1.6.47", environ=env)
    assert not state.is_quarantined("1.6.47", "a" * 64, environ=env)


def test_incomplete_download_is_kept_for_resume(tmp_path):
    payload = b"abc"
    asset = {"name": "WinUx_FULL.zip", "browser_download_url": "https://download.test/a.zip", "size": 10}
    provider = providers.GitHubReleaseProvider(
        "acme/WinUx", cache_dir=str(tmp_path), environ={},
        opener=lambda request, timeout=None: Response(payload),
    )
    target = str(tmp_path / "WinUx_FULL.zip")
    try:
        provider._download_asset_to_file(asset, target, "0" * 64)
    except RuntimeError as exc:
        assert "will resume next time" in str(exc)
    else:
        raise AssertionError("incomplete download must fail")
    assert Path(target + ".partial").read_bytes() == payload
