"""Architecture guards for canonical internal package boundaries."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "WinUx"
COMPATIBILITY_MODULES = {
    "abaqus_version_preferences.py",
    "general_preferences.py",
    "inp_preferences.py",
    "job_manager_preferences.py",
    "login_preferences.py",
    "navigation_preferences.py",
    "performance_preferences.py",
    "model.py",
    "application.py",
}


def test_internal_code_uses_canonical_preference_and_model_packages():
    forbidden = (
        ".abaqus_version_preferences import",
        ".general_preferences import",
        ".inp_preferences import",
        ".job_manager_preferences import",
        ".login_preferences import",
        ".navigation_preferences import",
        ".performance_preferences import",
        ".model import",
    )
    offenders = []
    for path in PACKAGE.rglob("*.py"):
        if path.parent == PACKAGE and path.name in COMPATIBILITY_MODULES:
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        if any(token in source for token in forbidden):
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_legacy_public_facades_remain_available():
    for name in COMPATIBILITY_MODULES:
        assert (PACKAGE / name).is_file()


def test_bootstrap_has_explicit_lifecycle_and_vendor_owners():
    bootstrap = PACKAGE / "bootstrap"
    assert (bootstrap / "application.py").is_file()
    assert (bootstrap / "vendor.py").is_file()
    application = (PACKAGE / "application.py").read_text(encoding="utf-8")
    assert "from .bootstrap.application import run" in application
