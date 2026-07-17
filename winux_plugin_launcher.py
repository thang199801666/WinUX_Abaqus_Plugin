from __future__ import print_function

import glob
import os
import shutil
import subprocess


def _plugin_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _is_abaqus_python(executable):
    normalized = os.path.normcase(os.path.abspath(executable))
    markers = ('simulia', 'smapy', 'estproducts', 'abaqus')
    return any(marker in normalized for marker in markers)


def _clean_environment():
    env = os.environ.copy()

    # Abaqus defines Python variables for its embedded SMApy runtime. Passing
    # these variables to a normal Python process can make it load Abaqus' stdlib
    # and fail while importing io.py.
    for name in (
        'PYTHONHOME',
        'PYTHONPATH',
        'PYTHONSTARTUP',
        'PYTHONUSERBASE',
        'PYTHONEXECUTABLE',
        '__PYVENV_LAUNCHER__',
    ):
        env.pop(name, None)

    env['PYTHONNOUSERSITE'] = '1'
    return env


def _yield_existing(candidates, seen):
    for executable, extra_args in candidates:
        if not executable:
            continue

        resolved = executable
        if not os.path.isabs(resolved):
            resolved = shutil.which(resolved)

        if not resolved or not os.path.isfile(resolved):
            continue
        if _is_abaqus_python(resolved):
            continue

        key = os.path.normcase(os.path.abspath(resolved))
        if key in seen:
            continue
        seen.add(key)
        yield resolved, extra_args


def _candidate_interpreters():
    seen = set()

    custom = os.environ.get('WINUX_PYTHON', '').strip().strip('"')
    custom_candidates = []
    if custom:
        custom_candidates.append((custom, []))

    for value in _yield_existing(custom_candidates, seen):
        yield value

    # Prefer windowed interpreters so no terminal window appears.
    path_candidates = [
        ('pyw.exe', ['-3']),
        ('pythonw.exe', []),
        ('py.exe', ['-3']),
        ('python.exe', []),
    ]
    for value in _yield_existing(path_candidates, seen):
        yield value

    local_app_data = os.environ.get('LOCALAPPDATA', '')
    program_files = os.environ.get('ProgramFiles', '')
    patterns = []
    if local_app_data:
        patterns.extend([
            os.path.join(local_app_data, 'Programs', 'Python', 'Python*', 'pythonw.exe'),
            os.path.join(local_app_data, 'Programs', 'Python', 'Python*', 'python.exe'),
        ])
    if program_files:
        patterns.extend([
            os.path.join(program_files, 'Python*', 'pythonw.exe'),
            os.path.join(program_files, 'Python*', 'python.exe'),
        ])

    discovered = []
    for pattern in patterns:
        for executable in sorted(glob.glob(pattern), reverse=True):
            discovered.append((executable, []))

    for value in _yield_existing(discovered, seen):
        yield value


def _test_interpreter(executable, extra_args, env):
    command = [executable] + extra_args + [
        '-c',
        'import sys, tkinter; raise SystemExit(0 if sys.version_info[0] >= 3 else 2)',
    ]
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=os.environ.get('TEMP') or None,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        _stdout, stderr = process.communicate()
        if process.returncode == 0:
            return True, ''
        try:
            return False, stderr.decode('utf-8', 'replace')
        except Exception:
            return False, str(stderr)
    except (OSError, ValueError) as exc:
        return False, str(exc)


def launch_winux():
    script_path = os.path.join(_plugin_dir(), 'winux_app.py')
    if not os.path.isfile(script_path):
        _show_error('WinUX application file was not found:\n' + script_path)
        return False

    env = _clean_environment()
    errors = []

    for executable, extra_args in _candidate_interpreters():
        valid, error = _test_interpreter(executable, extra_args, env)
        if not valid:
            errors.append('%s: %s' % (executable, error.strip()))
            continue

        command = [executable] + extra_args + [script_path]
        try:
            subprocess.Popen(
                command,
                cwd=_plugin_dir(),
                env=env,
                close_fds=False,
                creationflags=(
                    getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
                    | getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                ),
            )
            return True
        except (OSError, ValueError) as exc:
            errors.append('%s: %s' % (executable, exc))

    message = (
        'WinUX could not find a standalone Python 3 installation with tkinter.\n\n'
        'Do not point WINUX_PYTHON to the Abaqus/SMApy Python executable.\n'
        'Install standard Python 3, or set WINUX_PYTHON to its pythonw.exe, for example:\n\n'
        'C:\\Users\\<user>\\AppData\\Local\\Programs\\Python\\Python313\\pythonw.exe'
    )
    if errors:
        message += '\n\nInterpreter checks:\n' + '\n'.join(errors[-6:])
    _show_error(message)
    return False


def _show_error(message):
    try:
        from abaqusGui import showAFXErrorDialog, getAFXApp
        showAFXErrorDialog(getAFXApp().getAFXMainWindow(), message)
    except Exception:
        print(message)