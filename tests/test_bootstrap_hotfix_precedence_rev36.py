from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_plugin_shim_prefers_newer_bundled_hotfix_over_stale_bootstrap():
    source = (ROOT / "WinUx_plugin.py").read_text(encoding="utf-8")
    assert "_bundled_is_newer_than(active)" in source
    assert 'os.environ["WINUX_BOOTSTRAP_MODE"] = "bundled"' in source
    assert 'os.environ["WINUX_PREFER_BUNDLED_RUNTIME"] = "1"' in source
    assert 'os.environ["WINUX_INSTALL_MODE"] = "legacy"' not in source


def test_hotfix_version_is_newer_than_cached_112_runtime():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.1.3"
