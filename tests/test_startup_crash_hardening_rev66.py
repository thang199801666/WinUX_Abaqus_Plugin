from pathlib import Path
from unittest.mock import patch
import os
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_safe_current_directory_survives_deleted_or_invalid_cwd():
    from WinUx.runtime.paths import safe_current_directory

    with patch.object(Path, "cwd", side_effect=OSError("cwd unavailable")):
        value = safe_current_directory()
    assert isinstance(value, Path)
    assert value.is_absolute()
    assert value.name or value.parent != value


def test_preference_path_falls_back_when_profile_and_home_are_unavailable(monkeypatch):
    from WinUx.preferences.storage import user_profile_path

    for key in ("APPDATA", "LOCALAPPDATA", "USERPROFILE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: (_ for _ in ()).throw(RuntimeError("no home"))))
    value = user_profile_path("settings.json")
    assert value.name == "settings.json"
    assert value.parent.name == "WinUX"
    assert str(value).startswith(tempfile.gettempdir())


def test_resource_discovery_does_not_require_cwd():
    from WinUx import resources

    with patch.object(Path, "cwd", side_effect=OSError("deleted cwd")):
        candidates = list(resources._candidate_resource_dirs())
    assert resources.PACKAGE_DIR / "Resources" in candidates


def test_launcher_project_resolution_does_not_require_cwd(monkeypatch):
    import winux_launcher

    monkeypatch.setattr(winux_launcher.os, "getcwd", lambda: (_ for _ in ()).throw(OSError("cwd gone")))
    resolved = winux_launcher.resolve_project_dir(value=str(ROOT), environ={})
    assert Path(resolved) == ROOT


def test_update_check_does_not_require_inherited_cwd(monkeypatch):
    import run_winux

    calls = []
    monkeypatch.setattr(run_winux.os, "getcwd", lambda: (_ for _ in ()).throw(OSError("cwd gone")))
    monkeypatch.setattr(run_winux.os, "chdir", lambda value: calls.append(str(value)))
    result = run_winux._check_for_update(
        str(ROOT), update_callable=lambda project_dir, **_kwargs: {"project": project_dir})
    assert result["project"] == str(ROOT)
    assert calls


def test_startup_optional_warmups_are_nonfatal_by_contract():
    source = (ROOT / "WinUx" / "view.py").read_text(encoding="utf-8")
    prewarm = source[source.index("from .dialogs.prewarm_pool import start_dialog_prewarm") - 20:
                     source.index("self._dock_drop_preview = DockDropPreview()")]
    assert "try:" in prewarm
    assert "Floating dialog prewarm failed during startup" in prewarm
    assert "Explorer theme warm-up failed during startup" in prewarm
    assert "fatal=False" in prewarm


def test_startup_sources_no_longer_call_raw_cwd_in_main_ui_path():
    view = (ROOT / "WinUx" / "view.py").read_text(encoding="utf-8")
    controller = (ROOT / "WinUx" / "controller.py").read_text(encoding="utf-8")
    navigation = (ROOT / "WinUx" / "controllers" / "navigation.py").read_text(encoding="utf-8")
    assert "Path.cwd()" not in view
    assert "Path.cwd()" not in controller
    assert "Path.cwd()" not in navigation
    assert "safe_current_directory()" in view
    assert "safe_current_directory()" in controller
    assert "safe_current_directory()" in navigation
