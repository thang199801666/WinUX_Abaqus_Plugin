"""The updater UI must run outside the Abaqus/CAE process."""

import os
from unittest import mock

import run_winux
import winux_launcher


def test_child_update_changes_out_of_deployment_before_sync(tmp_path):
    project = tmp_path / "WinUx"
    project.mkdir()
    (project / "WinUx").mkdir()
    (project / "WinUx" / "__main__.py").write_text("# app\n")
    safe = tmp_path / "safe"
    safe.mkdir()
    calls = []

    def update(local_dir):
        calls.append((local_dir, os.getcwd()))
        assert os.path.abspath(local_dir) == str(project.resolve())
        assert os.path.abspath(os.getcwd()) != str(project.resolve())
        return {"updated": False}

    old_cwd = os.getcwd()
    try:
        os.chdir(project)
        with mock.patch.dict(os.environ, {"TEMP": str(safe)}, clear=False):
            result = run_winux._check_for_update(str(project), update_callable=update)
        assert result == {"updated": False}
        assert os.path.abspath(os.getcwd()) == str(project.resolve())
    finally:
        os.chdir(old_cwd)

    assert calls == [(str(project), str(safe))]


def test_child_update_can_be_explicitly_disabled(tmp_path):
    project = tmp_path / "WinUx"
    project.mkdir()
    update = mock.Mock()
    with mock.patch.dict(os.environ, {"WINUX_SKIP_UPDATE": "1"}, clear=False):
        assert run_winux._check_for_update(str(project), update_callable=update) is None
    update.assert_not_called()


def test_explicit_project_launch_sets_skip_update(tmp_path):
    project = tmp_path / "WinUx"
    project.mkdir()
    (project / "run_winux.py").write_text("# runner\n")
    (project / "WinUx").mkdir()
    (project / "WinUx" / "__main__.py").write_text("# app\n")
    log = tmp_path / "launcher.log"

    class Process(object):
        pid = 999
        def poll(self):
            return None

    popen = mock.Mock(return_value=Process())
    winux_launcher._ACTIVE_PROCESS = None
    with mock.patch.object(winux_launcher, "_log_path", return_value=str(log)):
        _process, started = winux_launcher.launch_winux(
            project_dir=str(project),
            abaqus_command="abaqus",
            popen_factory=popen,
        )
    assert started is True
    assert popen.call_args.kwargs["env"]["WINUX_SKIP_UPDATE"] == "1"


def test_normal_launch_does_not_set_skip_update(tmp_path):
    project = tmp_path / "WinUx"
    project.mkdir()
    (project / "run_winux.py").write_text("# runner\n")
    log = tmp_path / "launcher.log"

    class Process(object):
        pid = 1000
        def poll(self):
            return None

    popen = mock.Mock(return_value=Process())
    winux_launcher._ACTIVE_PROCESS = None
    with mock.patch.object(winux_launcher, "resolve_project_dir", return_value=str(project)), \
            mock.patch.object(winux_launcher, "_log_path", return_value=str(log)):
        _process, started = winux_launcher.launch_winux(
            abaqus_command="abaqus",
            popen_factory=popen,
        )
    assert started is True
    assert "WINUX_SKIP_UPDATE" not in popen.call_args.kwargs["env"]


def test_child_check_passes_before_sync_only_when_requested(tmp_path):
    project = tmp_path / "WinUx"
    project.mkdir()
    safe = tmp_path / "safe"
    safe.mkdir()
    before_sync = mock.Mock()
    update = mock.Mock(return_value={"updated": False})

    with mock.patch.dict(os.environ, {"TEMP": str(safe)}, clear=False):
        result = run_winux._check_for_update(
            str(project),
            update_callable=update,
            before_sync=before_sync,
        )

    assert result == {"updated": False}
    update.assert_called_once_with(str(project), before_sync=before_sync)


def test_reopen_always_checks_but_does_not_launch_duplicate_when_existing_kept(tmp_path):
    project = tmp_path / "WinUx"
    project.mkdir()
    (project / "WinUx").mkdir()
    (project / "WinUx" / "__main__.py").write_text("# app\n")
    run = mock.Mock()
    update = mock.Mock(return_value={"updated": False, "cancelled": True})

    with mock.patch.object(run_winux, "_project_dir", return_value=str(project)), \
            mock.patch.object(run_winux, "_existing_winux_pid", return_value=444), \
            mock.patch.object(run_winux, "_pid_is_alive", return_value=True), \
            mock.patch.object(run_winux, "_check_for_update", side_effect=lambda project_dir, before_sync=None: update(project_dir, before_sync=before_sync)), \
            mock.patch.object(run_winux, "_configure_bundled_dependencies"):
        result = run_winux.main(run_callable=run)

    update.assert_called_once()
    assert update.call_args.kwargs["before_sync"] is not None
    run.assert_not_called()
    assert result == {"updated": False, "cancelled": True}


def test_update_now_closes_existing_only_from_before_sync_then_runs_replacement(tmp_path):
    project = tmp_path / "WinUx"
    project.mkdir()
    (project / "WinUx").mkdir()
    (project / "WinUx" / "__main__.py").write_text("# app\n")
    events = []

    def check(project_dir, before_sync=None):
        events.append("check")
        assert before_sync is not None
        before_sync()
        events.append("updated")
        return {"updated": True}

    def terminate(pid):
        events.append("terminate:{}".format(pid))

    def run():
        events.append("run")

    with mock.patch.object(run_winux, "_project_dir", return_value=str(project)), \
            mock.patch.object(run_winux, "_existing_winux_pid", return_value=555), \
            mock.patch.object(run_winux, "_terminate_existing_winux", side_effect=terminate), \
            mock.patch.object(run_winux, "_check_for_update", side_effect=check), \
            mock.patch.object(run_winux, "_configure_bundled_dependencies"):
        run_winux.main(run_callable=run)

    assert events == ["check", "terminate:555", "updated", "run"]
