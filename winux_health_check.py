"""Isolated post-install health checking for WinUx releases."""
from __future__ import print_function

import os
import subprocess
import sys
import tempfile
import time

DEFAULT_HEALTH_TIMEOUT_SECONDS = 35.0


def _text(value):
    try:
        text_type = unicode  # noqa: F821
    except NameError:
        text_type = str
    try:
        return text_type(value)
    except Exception:
        return str(value)


def subprocess_health_check(deployment_dir, manifest=None, environ=None, timeout=None,
                             popen_factory=None, executable=None):
    """Run the candidate's own runner in health-check mode before activation."""
    del manifest  # per-file verification is performed before this runtime check
    deployment_dir = os.path.abspath(deployment_dir)
    runner = os.path.join(deployment_dir, "run_winux.py")
    if not os.path.isfile(runner):
        raise RuntimeError("WinUx health-check runner is missing: {}".format(runner))
    env = dict(os.environ if environ is None else environ)
    env["WINUX_APP_DIR"] = deployment_dir
    env["WINUX_SKIP_UPDATE"] = "1"
    env["WINUX_HEALTH_CHECK"] = "1"
    command = [executable or sys.executable, runner, "--update-health-check"]
    popen_factory = popen_factory or subprocess.Popen
    kwargs = {
        "cwd": tempfile.gettempdir(),
        "env": env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    process = popen_factory(command, **kwargs)
    timeout = float(timeout or DEFAULT_HEALTH_TIMEOUT_SECONDS)
    try:
        try:
            output = process.communicate(timeout=timeout)[0]
        except TypeError:  # Python 2 subprocess has no timeout argument
            deadline = time.time() + timeout
            while process.poll() is None and time.time() < deadline:
                time.sleep(0.05)
            if process.poll() is None:
                try:
                    process.kill()
                except Exception:
                    pass
                output = process.communicate()[0]
                raise RuntimeError("WinUx health check timed out after {:.0f}s.".format(timeout))
            output = process.communicate()[0]
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except Exception:
                pass
            output = process.communicate()[0]
            raise RuntimeError("WinUx health check timed out after {:.0f}s.".format(timeout))
    finally:
        pass
    code = int(process.returncode or 0)
    if code != 0:
        message = _text(output.decode("utf-8", "replace") if isinstance(output, bytes) else output).strip()
        if len(message) > 1600:
            message = message[-1600:]
        raise RuntimeError("WinUx candidate health check failed (exit {}). {}".format(code, message))
    return True


__all__ = ["DEFAULT_HEALTH_TIMEOUT_SECONDS", "subprocess_health_check"]
