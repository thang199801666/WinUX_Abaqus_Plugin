"""Regression coverage for local-first WinUx Abaqus plug-in launching."""

import os
from unittest import mock

import winux_launcher


EXPECTED_SHARED_DIR = (
    r"S:\Division1\CAE\1. FEA\6. Tools\17.WinUx\WinUX_Abaqus_Plugin"
)


def test_default_shared_deployment_path_is_update_source():
    assert winux_launcher.DEFAULT_NETWORK_PROJECT_DIR == EXPECTED_SHARED_DIR


def test_bundled_local_deployment_precedes_environment_fallback():
    local_dir = r"C:\Users\user\abaqus_plugins\WinUx"
    env_dir = r"C:\dev\WinUx"

    def is_project(path):
        return path in (local_dir, env_dir)

    with mock.patch.object(winux_launcher, "_bundled_project_dir", return_value=local_dir), \
            mock.patch.object(winux_launcher, "_is_project_dir", side_effect=is_project):
        resolved = winux_launcher.resolve_project_dir(
            environ={"WINUX_APP_DIR": env_dir}
        )

    assert resolved == os.path.abspath(local_dir)


def test_explicit_project_dir_overrides_local_deployment():
    explicit_dir = r"C:\explicit\WinUx"
    local_dir = r"C:\Users\user\abaqus_plugins\WinUx"

    def is_project(path):
        return path in (explicit_dir, local_dir)

    with mock.patch.object(winux_launcher, "_bundled_project_dir", return_value=local_dir), \
            mock.patch.object(winux_launcher, "_is_project_dir", side_effect=is_project):
        resolved = winux_launcher.resolve_project_dir(
            explicit_dir,
            environ={},
        )

    assert resolved == os.path.abspath(explicit_dir)


def test_environment_is_used_if_local_deployment_is_unavailable():
    local_dir = r"C:\Users\user\abaqus_plugins\WinUx"
    env_dir = r"C:\dev\WinUx"

    with mock.patch.object(winux_launcher, "_bundled_project_dir", return_value=local_dir), \
            mock.patch.object(
                winux_launcher,
                "_is_project_dir",
                side_effect=lambda path: path == env_dir,
            ):
        resolved = winux_launcher.resolve_project_dir(
            environ={"WINUX_APP_DIR": env_dir}
        )

    assert resolved == os.path.abspath(env_dir)


def test_runner_uses_resolved_local_project(tmp_path):
    project = tmp_path / "local"
    project.mkdir()
    runner = project / "run_winux.py"
    runner.write_text("# runner\n")

    assert winux_launcher._runner_path(str(project)) == str(runner.resolve())


def test_normal_launch_never_runs_update_ui_inside_abaqus_process(tmp_path):
    local = tmp_path / "WinUx"
    local.mkdir()
    (local / "run_winux.py").write_text("# runner\n")
    log = tmp_path / "launcher.log"
    checker = mock.Mock()

    class Process(object):
        pid = 123

        def poll(self):
            return None

    popen = mock.Mock(return_value=Process())
    winux_launcher._ACTIVE_PROCESS = None

    with mock.patch.object(winux_launcher, "resolve_project_dir", return_value=str(local)), \
            mock.patch.object(winux_launcher, "_bundled_project_dir", return_value=str(local)), \
            mock.patch.object(winux_launcher, "_log_path", return_value=str(log)):
        process, started = winux_launcher.launch_winux(
            abaqus_command="abaqus",
            popen_factory=popen,
            update_checker=checker,
        )

    assert started is True
    assert process.pid == 123
    checker.assert_not_called()
    # The command process must not hold the deployment directory as its CWD;
    # otherwise Windows can refuse the child updater's atomic directory swap.
    assert popen.call_args.kwargs["cwd"] == str(local.parent)


def test_reopening_plugin_always_spawns_version_check_when_child_is_active(tmp_path):
    """Every menu activation must bootstrap a fresh child for version check."""
    local = tmp_path / "WinUx"
    local.mkdir()
    (local / "run_winux.py").write_text("# runner\n")
    checker = mock.Mock()
    log = tmp_path / "launcher.log"

    class RunningProcess(object):
        def __init__(self, pid):
            self.pid = pid

        def poll(self):
            return None

    active = RunningProcess(456)
    bootstrap = RunningProcess(789)
    winux_launcher._ACTIVE_PROCESS = active
    winux_launcher._ACTIVE_PROCESSES = [active]
    popen = mock.Mock(return_value=bootstrap)

    with mock.patch.object(winux_launcher, "resolve_project_dir", return_value=str(local)), \
            mock.patch.object(winux_launcher, "_bundled_project_dir", return_value=str(local)), \
            mock.patch.object(winux_launcher, "_log_path", return_value=str(log)):
        process, started = winux_launcher.launch_winux(
            abaqus_command="abaqus",
            popen_factory=popen,
            update_checker=checker,
        )

    # Update UI/checking still never runs inside the Abaqus/CAE process itself.
    checker.assert_not_called()
    assert started is True
    assert process is bootstrap
    popen.assert_called_once()
    assert popen.call_args.kwargs["env"]["WINUX_EXISTING_PID"] == "456"


def test_reopening_plugin_prunes_dead_children_before_selecting_existing_pid(tmp_path):
    local = tmp_path / "WinUx"
    local.mkdir()
    (local / "run_winux.py").write_text("# runner\n")
    log = tmp_path / "launcher.log"

    class Process(object):
        def __init__(self, pid, running=True):
            self.pid = pid
            self.running = running

        def poll(self):
            return None if self.running else 0

    dead = Process(100, running=False)
    active = Process(200, running=True)
    bootstrap = Process(300, running=True)
    winux_launcher._ACTIVE_PROCESS = dead
    winux_launcher._ACTIVE_PROCESSES = [dead, active]
    popen = mock.Mock(return_value=bootstrap)

    with mock.patch.object(winux_launcher, "resolve_project_dir", return_value=str(local)), \
            mock.patch.object(winux_launcher, "_bundled_project_dir", return_value=str(local)), \
            mock.patch.object(winux_launcher, "_log_path", return_value=str(log)):
        winux_launcher.launch_winux(
            abaqus_command="abaqus",
            popen_factory=popen,
        )

    assert popen.call_args.kwargs["env"]["WINUX_EXISTING_PID"] == "200"
