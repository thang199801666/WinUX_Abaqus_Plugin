"""Run the bundled WinUx application inside ``abaqus python``.

The process is already separate from Abaqus/CAE because ``winux_launcher``
starts this script through the Abaqus command.  Do not start SMApy's
``python.exe`` a second time: the ``abaqus python`` command is what prepares
the native Abaqus Python runtime correctly.
"""

from __future__ import print_function

import os
import signal
import subprocess
import sys


_VENDOR_DLL_HANDLES = []


def _project_dir():
    configured = os.environ.get("WINUX_APP_DIR") or os.environ.get("WIXUX_APP_DIR") or os.path.dirname(
        os.path.abspath(__file__)
    )
    configured = os.path.abspath(configured)
    if not os.path.isfile(os.path.join(configured, "WinUx", "__main__.py")):
        raise RuntimeError(
            "WinUx must be beside run_winux.py, or WINUX_APP_DIR must point "
            "to the directory containing WinUx."
        )
    return configured


def _existing_winux_pid(environ=None):
    """Return the WinUx PID supplied by the Abaqus launcher, if still valid.

    The launcher passes the oldest live WinUx child whenever the menu is
    activated again.  The bootstrap still performs a complete version check;
    this PID is only used to prevent a second application instance after the
    check and to close the old instance immediately before an accepted update.
    """
    environ = os.environ if environ is None else environ
    raw = str(environ.get("WINUX_EXISTING_PID", "")).strip()
    if not raw:
        return None
    try:
        pid = int(raw)
    except (TypeError, ValueError):
        return None
    if pid <= 0 or pid == os.getpid():
        return None
    return pid


def _pid_is_alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
            )
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:
            return True
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _terminate_existing_winux(pid):
    """Terminate only the existing WinUx child immediately before update.

    This is deliberately executed from the standalone bootstrap child, never
    from Abaqus/CAE.  On Windows ``taskkill /T`` also terminates any descendants
    started by the WinUx child while leaving the Abaqus parent untouched.
    """
    if not pid or pid == os.getpid() or not _pid_is_alive(pid):
        return
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        command = ["taskkill", "/PID", str(int(pid)), "/T", "/F"]
        null_handle = open(os.devnull, "wb")
        try:
            result = subprocess.call(
                command,
                stdout=null_handle,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )
        finally:
            null_handle.close()
        if result not in (0, 128) and _pid_is_alive(pid):
            raise RuntimeError(
                "Could not close the currently running WinUx process (PID {}).".format(pid)
            )
        return
    try:
        os.kill(int(pid), signal.SIGTERM)
    except OSError:
        if _pid_is_alive(pid):
            raise


def _vendor_candidates(project_dir):
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = (
        os.path.join(plugin_dir, "vendor"),
        os.path.join(plugin_dir, "winux_vendor"),
        os.path.join(plugin_dir, "site-packages"),
        os.path.join(plugin_dir, "winux_vendor.zip"),
        os.path.join(project_dir, "vendor"),
        os.path.join(project_dir, "winux_vendor"),
        os.path.join(project_dir, "site-packages"),
        os.path.join(project_dir, "winux_vendor.zip"),
        os.path.join(project_dir, "WinUx", "vendor"),
    )
    result = []
    seen = set()
    for path in candidates:
        path = os.path.abspath(path)
        key = path.lower()
        if key in seen:
            continue
        if os.path.isdir(path) or os.path.isfile(path):
            seen.add(key)
            result.append(path)
    return result


def _configure_bundled_dependencies(project_dir, environ=None):
    """Expose vendored Python packages and adjacent native DLLs."""
    global _VENDOR_DLL_HANDLES
    environ = os.environ if environ is None else environ
    if environ.get("WINUX_SKIP_VENDOR", "").strip() == "1":
        return []

    vendor_paths = _vendor_candidates(project_dir)
    for path in reversed(vendor_paths):
        if path not in sys.path:
            sys.path.insert(0, path)

    directories = [path for path in vendor_paths if os.path.isdir(path)]
    dll_directories = []
    for directory in directories:
        dll_directories.extend((
            directory,
            os.path.join(directory, "dearpygui"),
            os.path.join(directory, "PIL"),
        ))
    dll_directories = [
        path for path in dll_directories if os.path.isdir(path)
    ]

    old_path = environ.get("PATH", "")
    environ["PATH"] = os.pathsep.join(
        dll_directories + ([old_path] if old_path else [])
    )

    add_dll_directory = getattr(os, "add_dll_directory", None)
    if os.name == "nt" and add_dll_directory is not None:
        for directory in dll_directories:
            try:
                _VENDOR_DLL_HANDLES.append(add_dll_directory(directory))
            except OSError:
                pass
    return vendor_paths


def _show_error(message):
    message = str(message)
    print(message, file=sys.stderr)
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None,
            message,
            "WinUx launch error",
            0x00000010,
        )
    except Exception:
        pass


def _check_for_update(project_dir, update_callable=None, before_sync=None):
    """Run the complete updater in this independent child process.

    ``winux_launcher`` starts this script through ``abaqus python`` and then
    immediately returns control to Abaqus/CAE.  Keeping the update UI here
    prevents native update dialogs from nesting a message loop inside FOX.

    The updater swaps the complete local deployment directory on Windows, so
    the child must first leave that directory as its current working directory.
    Python has already loaded this script into memory, therefore the directory
    can then be staged/replaced safely.
    """
    if os.environ.get("WINUX_SKIP_UPDATE", "").strip() == "1":
        return None

    if update_callable is None:
        from winux_updater import update_local_if_newer
        update_callable = update_local_if_newer

    previous_cwd = os.getcwd()
    safe_cwd = os.environ.get("TEMP") or os.environ.get("TMP") or os.path.dirname(project_dir)
    try:
        try:
            os.chdir(safe_cwd)
        except Exception:
            # Falling back to the deployment parent is still enough to avoid
            # holding the directory being replaced as the process CWD.
            os.chdir(os.path.dirname(project_dir))
        if before_sync is None:
            return update_callable(project_dir)
        return update_callable(project_dir, before_sync=before_sync)
    finally:
        # Always return to the (possibly newly installed) local deployment
        # before WinUx imports its resources/vendor packages.  If the update
        # failed, the updater guarantees rollback to the prior local copy.
        target = project_dir if os.path.isdir(project_dir) else previous_cwd
        try:
            os.chdir(target)
        except Exception:
            pass


def _note_launch_timings(marks):
    """Append pre-log startup timings to the launcher log, if configured.

    Everything before WinUx's own diagnostic log exists (process spawn,
    interpreter startup, vendor path setup, first imports) is otherwise
    invisible when diagnosing a slow cold start. Failures here must never
    break startup, so every step is guarded.
    """
    try:
        log_path = os.environ.get("WINUX_LAUNCH_LOG") or os.environ.get("WIXUX_LAUNCH_LOG", "")
        if not log_path:
            return
        lines = ["[child timings]"]
        first = marks[0][1] if marks else 0
        previous = first
        for label, stamp in marks:
            lines.append("  {} {:.3f} step={:.3f}s total={:.3f}s".format(
                label, stamp, max(0.0, stamp-previous), max(0.0, stamp-first)))
            previous = stamp
        with open(log_path, "ab") as handle:
            handle.write(("\n" + "\n".join(lines) + "\n").encode("utf-8"))
    except Exception:
        pass


def main(run_callable=None):
    import time as _time
    # This script is the entry point of a dedicated WinUX child process.
    os.environ.setdefault("WINUX_STANDALONE_PROCESS", "1")
    marks = [("child process started", _time.time())]
    project_dir = _project_dir()
    if project_dir not in sys.path:
        sys.path.insert(0, project_dir)

    # The update check/dialog/progress window live entirely in this child
    # process. Abaqus/CAE is never made an owner and never runs a nested native
    # message loop, so closing a dialog or WinUx itself cannot block CAE.
    #
    # IMPORTANT: this check always happens, even when another WinUx instance is
    # already running. If an update is accepted, the updater invokes
    # ``before_sync`` only after confirmation + lock acquisition, at which point
    # it is safe to close the old WinUx process and replace the local package.
    existing_pid = _existing_winux_pid()
    existing_closed = [False]

    def _before_sync():
        if existing_pid is not None:
            _terminate_existing_winux(existing_pid)
            existing_closed[0] = True

    update_status = _check_for_update(
        project_dir,
        before_sync=_before_sync if existing_pid is not None else None,
    )
    marks.append(("update check complete", _time.time()))

    # If WinUx was already running and the user kept the current version (same
    # version, Cancel, unavailable server, or source-dialog Cancel), this
    # bootstrap has completed its mandatory version check and must now exit
    # without opening a duplicate application instance. If Update Now reached
    # the transactional install phase, ``before_sync`` closed the old process;
    # this child then becomes the replacement WinUx instance, including after a
    # failed install/rollback.
    if existing_pid is not None and not existing_closed[0] and _pid_is_alive(existing_pid):
        return update_status

    _configure_bundled_dependencies(project_dir)
    os.chdir(project_dir)
    marks.append(("vendor paths configured", _time.time()))

    if run_callable is None:
        from WinUx import run
        run_callable = run
    marks.append(("WinUx entry imported", _time.time()))
    _note_launch_timings(marks)
    run_callable()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        _show_error("WinUx could not start.\n\n{}".format(error))
        raise
