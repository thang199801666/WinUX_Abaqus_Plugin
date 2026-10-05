from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def test_product_version_is_pinned_to_110():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.1.0"
    assert not (ROOT / "VERSION_EPOCH").exists()
    metadata = json.loads((ROOT / "tools" / "refactor_current.json").read_text(encoding="utf-8"))
    assert metadata.get("version") == "1.1.0"


def test_update_stack_uses_standard_semver_without_epoch_bridge():
    manifest = (ROOT / "winux_update_manifest.py").read_text(encoding="utf-8")
    updater = (ROOT / "winux_updater.py").read_text(encoding="utf-8")
    provider = (ROOT / "winux_update_providers.py").read_text(encoding="utf-8")
    combined = manifest + updater + provider
    assert "VERSION_EPOCH" not in combined
    assert "compare_update_versions" not in combined
    assert "1.6.49 bridge" not in combined


def test_settings_has_manual_check_and_sdrive_migration_path():
    settings = (ROOT / "WinUx" / "dialogs" / "settings_form.py").read_text(encoding="utf-8")
    assert '"Check for Updates"' in settings
    assert "def _check_for_updates_now" in settings
    assert "GitHub Releases (recommended)" in settings
    assert "Shared folder / S: drive (legacy)" in settings


def test_version_policy_documented_as_explicit_only():
    notes = (ROOT / "REFACTOR_NOTES.md").read_text(encoding="utf-8")
    assert "must not bump this version automatically" in notes
