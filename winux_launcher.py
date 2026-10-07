"""Start WinUx through an independent ``abaqus python`` process."""

from __future__ import print_function

import datetime
import os
import subprocess
import tempfile

from winux_updater import DEFAULT_NETWORK_PROJECT_DIR
from winux_installation_state import resolve_active_installation


ABAQUS_COMMAND = "abaqus"
_ACTIVE_PROCESS = None
_ACTIVE_PROCESSES = []


def _is_project_dir(path):
    return bool(
        path
        and os.path.isfile(
            os.path.join(os.path.abspath(path), "WinUx", "__main__.py")
        )
    )


def _bundled_project_dir():
    """The flat WinUx plug-in folder directly contains the deployed WinUx package."""
    return os.path.dirname(os.path.abspath(__file__))


def resolve_project_dir(value=None, environ=None):
    """Resolve the local runtime deployment used for this launch.

    Explicit development/test paths still win. Normal Windows launches prefer
    the crash-safe versioned installation pointer when one exists, then fall
    back to the historical self-contained plug-in directory. The shared S:\n    source remains update-only and is never executed directly.
    """
    environ = os.environ if environ is None else environ
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    source_checkout = os.path.abspath(
        os.path.join(plugin_dir, os.pardir, os.pardir)
    )

    if value is not None:
        if _is_project_dir(value):
            return os.path.abspath(value)
        raise RuntimeError("The requested WinUx project directory is invalid: {}".format(value))

    bundled = _bundled_project_dir()
    install_mode = str(environ.get("WINUX_INSTALL_MODE", "")).strip().lower()
    prefer_bundled = str(environ.get("WINUX_PREFER_BUNDLED_RUNTIME", "")).strip().lower() in (
        "1", "true", "yes", "on", "bundled"
    )
    # Runtime precedence must not be coupled to the updater's install strategy.
    # A bundled hotfix can be preferred for this launch while updates continue
    # to use the crash-safe immutable/versioned installer.
    if not prefer_bundled and install_mode not in ("legacy", "flat", "in-place", "inplace"):
        try:
            active = resolve_active_installation(bundled, environ=environ)
        except Exception:
            active = None
        if _is_project_dir(active):
            return os.path.abspath(active)

    candidates = (
        bundled,
        environ.get("WINUX_APP_DIR") or environ.get("WIXUX_APP_DIR"),
        source_checkout,
        os.getcwd(),
    )
    for candidate in candidates:
        if _is_project_dir(candidate):
            return os.path.abspath(candidate)
    raise RuntimeError(
        "The local WinUx deployment was not found beside the launcher, in the "
        "versioned runtime store, or in WINUX_APP_DIR."
    )


def _runner_path(project_dir=None):
    """Return the runner from the resolved deployment when available."""
    if project_dir:
        shared_runner = os.path.join(os.path.abspath(project_dir), "run_winux.py")
        if os.path.isfile(shared_runner):
            return shared_runner
    return os.path.join(_bundled_project_dir(), "run_winux.py")


def build_abaqus_command(abaqus_command=None, runner_path=None):
    """Return the supported ``abaqus python script.py`` command."""
    command = str(
        abaqus_command
        or os.environ.get("WINUX_ABAQUS_COMMAND") or os.environ.get("WIXUX_ABAQUS_COMMAND")
        or ABAQUS_COMMAND
    ).strip()
    if not command:
        raise RuntimeError("The Abaqus command is empty.")
    runner_path = os.path.abspath(runner_path or _runner_path())
    if not os.path.isfile(runner_path):
        raise RuntimeError("WinUx runner was not found: {}".format(runner_path))
    return [command, "python", runner_path]


def _command_for_subprocess(command, environ=None, platform_name=None):
    """Wrap Abaqus' Windows batch command in ``cmd.exe`` when required."""
    environ = os.environ if environ is None else environ
    platform_name = os.name if platform_name is None else platform_name
    if platform_name != "nt":
        return list(command)
    command_line = subprocess.list2cmdline(list(command))
    return [
        environ.get("COMSPEC") or "cmd.exe",
        "/d",
        "/s",
        "/c",
        command_line,
    ]


LAUNCHER_LOG_MAX_BYTES = 1024 * 1024
LAUNCHER_LOG_KEEP_BYTES = 256 * 1024


def _prune_launcher_log(path):
    """Keep the append-only launcher log bounded across sessions.

    Called on every launch before new lines are written. When the log grows
    past the limit, only the most recent tail is kept so launch history can
    never accumulate without bound. Failures are silent: logging must never
    break application startup.
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return
    if size <= LAUNCHER_LOG_MAX_BYTES:
        return
    try:
        with open(path, "rb") as handle:
            handle.seek(max(0, size - LAUNCHER_LOG_KEEP_BYTES))
            tail = handle.read()
        newline = tail.find(b"\n")
        if newline != -1:
            tail = tail[newline + 1:]
        with open(path, "wb") as handle:
            handle.write(
                b"[WinUx launch history truncated; "
                b"keeping the most recent entries]\n"
            )
            handle.write(tail)
    except (OSError, IOError):
        pass


def _log_path(environ=None):
    environ = os.environ if environ is None else environ
    root = (
        environ.get("LOCALAPPDATA")
        or environ.get("APPDATA")
        or tempfile.gettempdir()
    )
    directory = os.path.join(root, "WinUx", "logs")
    if not os.path.isdir(directory):
        try:
            os.makedirs(directory)
        except OSError:
            if not os.path.isdir(directory):
                raise
    path = os.path.join(directory, "winux_abaqus_launcher.log")
    _prune_launcher_log(path)
    return path


def _launch_environment(project_dir, environ=None):
    result = dict(os.environ if environ is None else environ)
    old_python_path = result.get("PYTHONPATH", "")
    result["PYTHONPATH"] = (
        project_dir
        if not old_python_path
        else project_dir + os.pathsep + old_python_path
    )
    result["WINUX_APP_DIR"] = project_dir
    # WinUX runs in its own SMAPython child. This allows the application close
    # path to use a guaranteed process exit without affecting Abaqus/CAE.
    result["WINUX_STANDALONE_PROCESS"] = "1"
    return result


def _is_running(process):
    if process is None:
        return False
    try:
        return process.poll() is None
    except Exception:
        return False


def _running_processes():
    """Return all WinUx bootstrap/app children still owned by this CAE session.

    Every Plug-ins > WinUx activation starts a fresh bootstrap child so version
    checking is never skipped.  We therefore keep more than one historical
    process handle: the oldest running child is normally the current WinUx app,
    while newer short-lived children may only be performing a version check.
    """
    global _ACTIVE_PROCESSES
    candidates = []
    for process in list(_ACTIVE_PROCESSES):
        if process not in candidates and _is_running(process):
            candidates.append(process)
    if _ACTIVE_PROCESS is not None and _ACTIVE_PROCESS not in candidates and _is_running(_ACTIVE_PROCESS):
        candidates.append(_ACTIVE_PROCESS)
    _ACTIVE_PROCESSES = candidates
    return list(candidates)


def launch_winux(project_dir=None, abaqus_command=None, popen_factory=None, update_checker=None,
                 existing_pid=None, install_update=False):
    """Launch WinUx without blocking Abaqus/CAE.

    Returns ``(process, started)``. A new bootstrap child is started for every
    invocation so every Plug-ins > WinUx activation performs a version check.
    The child itself suppresses duplicate WinUx application instances after the
    check when an existing local instance is still running.
    """
    global _ACTIVE_PROCESS, _ACTIVE_PROCESSES

    explicit_project_dir = project_dir is not None
    project_dir = resolve_project_dir(project_dir)

    # IMPORTANT: never run update dialogs or file synchronization inside the
    # Abaqus/CAE process.  The child ``abaqus python run_winux.py`` process
    # owns the complete update flow.  This lets the FOX event loop return
    # immediately, so closing/cancelling WinUx dialogs can never leave the
    # Abaqus main window disabled or blocked.
    #
    # ``update_checker`` is retained only for source/API compatibility with
    # older callers; update checks are intentionally not executed here.
    del update_checker

    # Version checking is mandatory on every menu activation.  Never return
    # early just because a previous WinUx child is still running.  Instead pass
    # the oldest live child PID to the new bootstrap process.  After checking
    # the server version, that child either exits (no update / Cancel) or closes
    # the existing WinUx instance immediately before installing an accepted
    # update.
    running_before_launch = _running_processes()
    existing_process = running_before_launch[0] if running_before_launch else None

    command = build_abaqus_command(
        abaqus_command,
        runner_path=_runner_path(project_dir),
    )
    if install_update:
        command.append("--install-update")
    log_path = _log_path()
    environment = _launch_environment(project_dir)
    environment["WINUX_LAUNCH_LOG"] = log_path
    if install_update:
        environment.pop("WINUX_SKIP_UPDATE", None)
        environment["WINUX_UPDATE_FROM_APP"] = "1"
    if existing_pid is not None:
        environment["WINUX_EXISTING_PID"] = str(int(existing_pid))
    elif existing_process is not None:
        try:
            environment["WINUX_EXISTING_PID"] = str(int(existing_process.pid))
        except Exception:
            pass
    if explicit_project_dir and not install_update:
        # Explicit development/test checkouts preserve the historical behavior:
        # they are launched as-is and never auto-updated from the shared S: source.
        environment["WINUX_SKIP_UPDATE"] = "1"
    process_command = _command_for_subprocess(command, environment)
    popen_factory = popen_factory or subprocess.Popen

    flags = 0
    if os.name == "nt":
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    log_handle = open(log_path, "ab")
    null_handle = open(os.devnull, "rb")
    try:
        header = (
            "\n[{0}] WinUx launch\n"
            "Project: {1}\n"
            "Runner: {2}\n"
            "Command: {3}\n"
        ).format(
            datetime.datetime.now().isoformat(),
            project_dir,
            _runner_path(project_dir),
            " ".join(command),
        )
        log_handle.write(header.encode("utf-8"))
        log_handle.flush()
        # Do not start cmd.exe/abaqus with the WinUx deployment itself as the
        # working directory. On Windows a process CWD can prevent the updater
        # child from renaming/swapping that directory even after the Python
        # script changes its own CWD. The runner uses an absolute path and
        # WINUX_APP_DIR, so the deployment parent is the safe launch CWD.
        launch_cwd = os.path.dirname(project_dir) or tempfile.gettempdir()
        _ACTIVE_PROCESS = popen_factory(
            process_command,
            cwd=launch_cwd,
            env=environment,
            stdin=null_handle,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        _ACTIVE_PROCESSES.append(_ACTIVE_PROCESS)
        try:
            log_handle.write(
                "[{}] parent spawned pid={}\n".format(
                    datetime.datetime.now().isoformat(),
                    _ACTIVE_PROCESS.pid,
                ).encode("utf-8")
            )
            log_handle.flush()
        except Exception:
            pass
    except Exception as exc:
        raise RuntimeError(
            "Failed to execute '{}'. Details: {}. Log: {}".format(
                " ".join(command), exc, log_path
            )
        )
    finally:
        null_handle.close()
        log_handle.close()

    return _ACTIVE_PROCESS, True


__all__ = [
    "DEFAULT_NETWORK_PROJECT_DIR",
    "build_abaqus_command",
    "launch_winux",
    "resolve_project_dir",
]
