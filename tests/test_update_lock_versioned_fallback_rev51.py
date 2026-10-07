from unittest import mock

import winux_launcher
import winux_updater


def test_prefer_bundled_runtime_does_not_require_legacy_install_mode(tmp_path, monkeypatch):
    bundled = tmp_path / "bundled"
    active = tmp_path / "active"
    for root in (bundled, active):
        (root / "WinUx").mkdir(parents=True)
        (root / "WinUx" / "__main__.py").write_text("# app\n")
    monkeypatch.setattr(winux_launcher, "_bundled_project_dir", lambda: str(bundled))
    monkeypatch.setattr(winux_launcher, "resolve_active_installation", lambda *_a, **_k: str(active))

    resolved = winux_launcher.resolve_project_dir(
        environ={"WINUX_PREFER_BUNDLED_RUNTIME": "1"}
    )

    assert resolved == str(bundled.resolve())


def test_windows_legacy_sharing_violation_falls_back_to_versioned(monkeypatch):
    class SharingViolation(OSError):
        winerror = 32
        errno = 13

    monkeypatch.setattr(winux_updater.os, "name", "nt")
    monkeypatch.setattr(winux_updater, "_use_versioned_install", lambda **_k: False)
    monkeypatch.setattr(
        winux_updater,
        "_synchronize_project",
        mock.Mock(side_effect=SharingViolation("file is being used by another process")),
    )
    expected = {"version": "1.1.3", "active_dir": r"C:\\runtime\\1.1.3", "mode": "versioned"}
    versioned = mock.Mock(return_value=expected)
    monkeypatch.setattr(winux_updater, "_synchronize_versioned_project", versioned)

    result = winux_updater._default_sync(
        r"C:\\stage", r"C:\\Users\\user\\abaqus_plugins\\WinUx",
        environ={"LOCALAPPDATA": r"C:\\Users\\user\\AppData\\Local"},
        source_label="GitHub Releases",
    )

    assert result is expected
    versioned.assert_called_once()
    assert versioned.call_args.kwargs["before_activate"] is None


def test_non_lock_legacy_install_error_is_not_masked(monkeypatch):
    class OtherFailure(OSError):
        winerror = 2
        errno = 2

    monkeypatch.setattr(winux_updater.os, "name", "nt")
    monkeypatch.setattr(winux_updater, "_use_versioned_install", lambda **_k: False)
    monkeypatch.setattr(
        winux_updater,
        "_synchronize_project",
        mock.Mock(side_effect=OtherFailure("missing file")),
    )
    versioned = mock.Mock()
    monkeypatch.setattr(winux_updater, "_synchronize_versioned_project", versioned)

    try:
        winux_updater._default_sync("stage", "local", environ={})
    except OtherFailure:
        pass
    else:
        raise AssertionError("non-sharing errors must propagate")
    versioned.assert_not_called()
