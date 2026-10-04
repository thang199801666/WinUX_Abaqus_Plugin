from __future__ import annotations

import atexit
import faulthandler
import functools
import logging
from logging.handlers import RotatingFileHandler
import os
import platform
import sys
import tempfile
import threading
import traceback
from datetime import datetime
from pathlib import Path


APP_LOG_NAME = "winux.log"
CRASH_LOG_NAME = "winux_crash.log"
LOG_DIR_ENV = "WINUX_LOG_DIR"
MAX_LOG_BYTES = 2 * 1024 * 1024
LOG_BACKUP_COUNT = 5
NATIVE_LOG_RETENTION = 10

_LOCK = threading.RLock()
_INSTALLED = False
_ATEXIT_REGISTERED = False
_FATAL_EXCEPTION_SEEN = False
_LOGGED_EXCEPTION_IDS = []
_LOG_DIRECTORY = None
_NATIVE_LOG_PATH = None
_NATIVE_LOG_FILE = None
_OWNS_FAULT_HANDLER = False
_APP_LOGGER = None
_CRASH_LOGGER = None
_PREVIOUS_SYS_EXCEPTHOOK = None
_PREVIOUS_THREADING_EXCEPTHOOK = None
_PREVIOUS_UNRAISABLEHOOK = None
_CURRENT_SESSION_ID = None


def _fallback_write(message):
    """Best-effort fallback that must never raise during crash handling."""
    try:
        sys.__stderr__.write("[WinUX crash logger] {}\n".format(message))
        sys.__stderr__.flush()
    except Exception:
        pass


def _candidate_log_directories():
    override = os.environ.get(LOG_DIR_ENV)
    if override:
        yield Path(override).expanduser()

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        yield Path(local_app_data) / "WinUx" / "logs"

    roaming_app_data = os.environ.get("APPDATA")
    if roaming_app_data:
        yield Path(roaming_app_data) / "WinUx" / "logs"

    try:
        yield Path.home() / ".winux" / "logs"
    except Exception:
        pass

    yield Path(tempfile.gettempdir()) / "WinUx" / "logs"


def _resolve_log_directory():
    errors = []
    seen = set()
    for candidate in _candidate_log_directories():
        try:
            candidate = candidate.resolve()
        except Exception:
            candidate = Path(candidate)
        key = str(candidate).casefold()
        if key in seen:
            continue
        seen.add(key)
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".winux-write-probe"
            with probe.open("a", encoding="utf-8"):
                pass
            try:
                probe.unlink()
            except OSError:
                pass
            return candidate
        except Exception as exc:
            errors.append("{}: {}".format(candidate, exc))

    raise OSError(
        "No writable WinUX log directory was found ({})".format(
            "; ".join(errors)))


STARTUP_TRUNCATE_BYTES = 2 * MAX_LOG_BYTES
STARTUP_KEEP_BYTES = MAX_LOG_BYTES


def _truncate_oversized_log(path):
    """Hard-cap an existing log file at startup.

    The rotating handlers bound steady-state growth for a single process,
    but concurrent writers (e.g. two WinUx instances) can race rotation and
    keep appending past the limit. Trimming once at startup, before handlers
    are attached, guarantees the directory can never accumulate without
    bound. Only the most recent tail is kept, cut at a line boundary.
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return
    if size <= STARTUP_TRUNCATE_BYTES:
        return
    try:
        with open(path, "rb") as handle:
            handle.seek(max(0, size - STARTUP_KEEP_BYTES))
            tail = handle.read()
        newline = tail.find(b"\n")
        if newline != -1:
            tail = tail[newline + 1:]
        with open(path, "wb") as handle:
            handle.write(
                b"[WinUx log truncated at startup; "
                b"keeping the most recent entries]\n"
            )
            handle.write(tail)
    except (OSError, IOError):
        pass


def _new_rotating_logger(name, path, level):
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    # A previous WinUX session may have ended without calling the normal
    # teardown path. Remove only handlers owned by this dedicated logger.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    handler = RotatingFileHandler(
        str(path),
        maxBytes=MAX_LOG_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
        delay=False,
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s.%(msecs)03d | %(levelname)s | "
        "pid=%(process)d | thread=%(threadName)s(%(thread)d) | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(handler)
    return logger


def _module_location(name):
    module = sys.modules.get(name)
    if module is None:
        return "<not loaded>"
    return str(getattr(module, "__file__", "<built-in or embedded>"))


def _runtime_details():
    dpg_version = "<unknown>"
    for module_name in ("dearpygui.dearpygui", "dearpygui"):
        module = sys.modules.get(module_name)
        value = getattr(module, "__version__", None) if module else None
        if value is not None:
            try:
                dpg_version = str(value)
            except Exception:
                dpg_version = "<unprintable>"
            break

    try:
        cwd = str(Path.cwd())
    except Exception as exc:
        cwd = "<unavailable: {}>".format(exc)

    executable = getattr(sys, "executable", "") or "<embedded>"
    try:
        platform_name = platform.platform()
    except Exception as exc:
        platform_name = "<unavailable: {}>".format(exc)

    return (
        "session_id={session}\n"
        "platform={platform}\n"
        "python={python}\n"
        "executable={executable}\n"
        "pid={pid}\n"
        "parent_pid={parent_pid}\n"
        "sys_prefix={sys_prefix}\n"
        "cwd={cwd}\n"
        "dearpygui={dpg}\n"
        "dearpygui_module={dpg_module}\n"
        "WinUx={package}\n"
        "WinUx.controller={controller}\n"
        "WinUx.view={view}"
    ).format(
        session=_session_id(),
        platform=platform_name,
        python=sys.version.replace("\n", " "),
        executable=executable,
        pid=os.getpid(),
        parent_pid=os.getppid(),
        sys_prefix=getattr(sys, "prefix", "<unknown>"),
        cwd=cwd,
        dpg=dpg_version,
        dpg_module=_module_location("dearpygui.dearpygui"),
        package=_module_location("WinUx"),
        controller=_module_location("WinUx.controller"),
        view=_module_location("WinUx.view"),
    )


def _new_session_id():
    return "{}-{}".format(
        datetime.now().strftime("%Y%m%d-%H%M%S-%f"), os.getpid())


def _session_id():
    return _CURRENT_SESSION_ID or _new_session_id()


def _prune_native_logs(directory):
    try:
        logs = sorted(
            directory.glob("winux_native_*.log"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    except Exception:
        return
    for old_log in logs[NATIVE_LOG_RETENTION:]:
        try:
            old_log.unlink()
        except OSError:
            pass


def _install_faulthandler(directory):
    global _NATIVE_LOG_FILE, _NATIVE_LOG_PATH, _OWNS_FAULT_HANDLER

    _NATIVE_LOG_PATH = directory / "winux_native_{}.log".format(_session_id())
    if faulthandler.is_enabled():
        _NATIVE_LOG_PATH = None
        _OWNS_FAULT_HANDLER = False
        _APP_LOGGER.warning(
            "Python faulthandler was already enabled by the host; "
            "WinUX did not replace the host's native-crash destination.")
        return

    try:
        _NATIVE_LOG_FILE = _NATIVE_LOG_PATH.open(
            "a", encoding="utf-8", buffering=1)
        _NATIVE_LOG_FILE.write(
            "WinUX native fault log started {}\n{}\n\n".format(
                datetime.now().isoformat(), _runtime_details()))
        _NATIVE_LOG_FILE.flush()
        faulthandler.enable(file=_NATIVE_LOG_FILE, all_threads=True)
        _OWNS_FAULT_HANDLER = True
        _APP_LOGGER.info(
            "Native fault capture enabled: %s", _NATIVE_LOG_PATH)
        _prune_native_logs(directory)
    except Exception:
        _OWNS_FAULT_HANDLER = False
        if _NATIVE_LOG_FILE is not None:
            try:
                _NATIVE_LOG_FILE.close()
            except Exception:
                pass
            _NATIVE_LOG_FILE = None
        _APP_LOGGER.exception("Could not enable native fault capture")


def _flush_loggers():
    for logger in (_APP_LOGGER, _CRASH_LOGGER):
        if logger is None:
            continue
        for handler in logger.handlers:
            try:
                handler.flush()
            except Exception:
                pass


def _remember_exception(exc_value):
    if exc_value is None:
        return True
    identity = id(exc_value)
    with _LOCK:
        if identity in _LOGGED_EXCEPTION_IDS:
            return False
        _LOGGED_EXCEPTION_IDS.append(identity)
        del _LOGGED_EXCEPTION_IDS[:-128]
    return True


def install_crash_logging():
    """Install process/thread/native crash capture and return log paths.

    Installation is lazy and idempotent so importing WinUX does not mutate the
    host process. Constructing the controller or view activates it.
    """
    global _APP_LOGGER, _ATEXIT_REGISTERED, _CRASH_LOGGER
    global _CURRENT_SESSION_ID, _FATAL_EXCEPTION_SEEN
    global _INSTALLED, _LOG_DIRECTORY, _NATIVE_LOG_PATH
    global _PREVIOUS_SYS_EXCEPTHOOK, _PREVIOUS_THREADING_EXCEPTHOOK
    global _PREVIOUS_UNRAISABLEHOOK

    with _LOCK:
        if _INSTALLED:
            return get_log_paths()

        _CURRENT_SESSION_ID = _new_session_id()
        _FATAL_EXCEPTION_SEEN = False
        _LOGGED_EXCEPTION_IDS.clear()
        _NATIVE_LOG_PATH = None

        try:
            _LOG_DIRECTORY = _resolve_log_directory()
            _truncate_oversized_log(_LOG_DIRECTORY / APP_LOG_NAME)
            _truncate_oversized_log(_LOG_DIRECTORY / CRASH_LOG_NAME)
            _APP_LOGGER = _new_rotating_logger(
                "WinUx.application",
                _LOG_DIRECTORY / APP_LOG_NAME,
                logging.INFO,
            )
            _CRASH_LOGGER = _new_rotating_logger(
                "WinUx.crash",
                _LOG_DIRECTORY / CRASH_LOG_NAME,
                logging.ERROR,
            )
        except Exception:
            _fallback_write(
                "Failed to initialize file logging:\n{}".format(
                    traceback.format_exc()))
            return {}

        _INSTALLED = True
        _PREVIOUS_SYS_EXCEPTHOOK = sys.excepthook
        sys.excepthook = _sys_exception_hook

        if hasattr(threading, "excepthook"):
            _PREVIOUS_THREADING_EXCEPTHOOK = threading.excepthook
            threading.excepthook = _thread_exception_hook

        if hasattr(sys, "unraisablehook"):
            _PREVIOUS_UNRAISABLEHOOK = sys.unraisablehook
            sys.unraisablehook = _unraisable_exception_hook

        if not _ATEXIT_REGISTERED:
            atexit.register(_atexit_report)
            _ATEXIT_REGISTERED = True

        _APP_LOGGER.info("WinUX crash logging installed\n%s", _runtime_details())
        _install_faulthandler(_LOG_DIRECTORY)
        # Prune here as well: when the host already owns faulthandler, the
        # installer above skips pruning and old native logs would accumulate.
        _prune_native_logs(_LOG_DIRECTORY)
        _flush_loggers()
        return get_log_paths()


def get_log_paths():
    """Return the active or most recently resolved WinUX diagnostic paths."""
    if _LOG_DIRECTORY is None:
        return {}
    paths = {
        "directory": str(_LOG_DIRECTORY),
        "application": str(_LOG_DIRECTORY / APP_LOG_NAME),
        "crash": str(_LOG_DIRECTORY / CRASH_LOG_NAME),
        "hang": str(_LOG_DIRECTORY / "winux_hang.log"),
    }
    if _NATIVE_LOG_PATH is not None:
        paths["native"] = str(_NATIVE_LOG_PATH)
    return paths


def log_event(message, level=logging.INFO):
    """Write an operational event without ever disrupting the application."""
    if not _INSTALLED:
        install_crash_logging()
    try:
        if _APP_LOGGER is not None:
            _APP_LOGGER.log(level, "%s", message)
            _flush_loggers()
    except Exception:
        _fallback_write("Could not write application event: {}".format(message))


def log_runtime_snapshot(context="WinUX runtime snapshot"):
    """Record module/runtime locations after lazily loaded layers are ready."""
    log_event("{}\n{}".format(context, _runtime_details()))


def log_exception(context, exc_info=None, fatal=True):
    """Record an exception with traceback in the appropriate diagnostic logs."""
    global _FATAL_EXCEPTION_SEEN

    if not _INSTALLED:
        install_crash_logging()
    if exc_info is None:
        exc_info = sys.exc_info()
    exc_type, exc_value, exc_traceback = exc_info
    if exc_type is None:
        return False
    if fatal and not _remember_exception(exc_value):
        return False

    try:
        message = "{}: {}: {}".format(
            context,
            getattr(exc_type, "__name__", str(exc_type)),
            exc_value,
        )
        if _APP_LOGGER is not None:
            _APP_LOGGER.error(message, exc_info=exc_info)
        if fatal and _CRASH_LOGGER is not None:
            _FATAL_EXCEPTION_SEEN = True
            _CRASH_LOGGER.error(message, exc_info=exc_info)
        _flush_loggers()
        return True
    except Exception:
        _fallback_write(
            "Crash logging itself failed:\n{}".format(traceback.format_exc()))
        return False


def crash_guard(context):
    """Decorator that logs an escaping exception once and re-raises it."""
    def decorate(function):
        @functools.wraps(function)
        def guarded(*args, **kwargs):
            install_crash_logging()
            try:
                return function(*args, **kwargs)
            except Exception:
                log_exception(context, sys.exc_info(), fatal=True)
                raise
        return guarded
    return decorate


def _sys_exception_hook(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        if _PREVIOUS_SYS_EXCEPTHOOK is not None:
            _PREVIOUS_SYS_EXCEPTHOOK(exc_type, exc_value, exc_traceback)
        return

    log_exception(
        "Unhandled exception on the main Python thread",
        (exc_type, exc_value, exc_traceback),
        fatal=True,
    )
    if (_PREVIOUS_SYS_EXCEPTHOOK is not None
            and _PREVIOUS_SYS_EXCEPTHOOK is not _sys_exception_hook):
        try:
            _PREVIOUS_SYS_EXCEPTHOOK(
                exc_type, exc_value, exc_traceback)
        except Exception:
            _fallback_write("The previous sys.excepthook failed")


def _thread_exception_hook(args):
    if args.exc_type is not SystemExit:
        thread_name = getattr(args.thread, "name", "<unknown>")
        log_exception(
            "Unhandled exception in thread {!r}".format(thread_name),
            (args.exc_type, args.exc_value, args.exc_traceback),
            fatal=True,
        )
    if (_PREVIOUS_THREADING_EXCEPTHOOK is not None
            and _PREVIOUS_THREADING_EXCEPTHOOK is not _thread_exception_hook):
        try:
            _PREVIOUS_THREADING_EXCEPTHOOK(args)
        except Exception:
            _fallback_write("The previous threading.excepthook failed")


def _unraisable_exception_hook(args):
    context = "Unraisable exception"
    if getattr(args, "err_msg", None):
        context += ": {}".format(args.err_msg)
    if getattr(args, "object", None) is not None:
        try:
            context += " object={!r}".format(args.object)
        except Exception:
            pass
    log_exception(
        context,
        (args.exc_type, args.exc_value, args.exc_traceback),
        fatal=False,
    )
    if (_PREVIOUS_UNRAISABLEHOOK is not None
            and _PREVIOUS_UNRAISABLEHOOK is not _unraisable_exception_hook):
        try:
            _PREVIOUS_UNRAISABLEHOOK(args)
        except Exception:
            _fallback_write("The previous sys.unraisablehook failed")


def shutdown_crash_logging(reason="WinUX logging shutdown"):
    """Flush logs and restore host hooks after a normal application exit."""
    global _APP_LOGGER, _CRASH_LOGGER, _INSTALLED
    global _NATIVE_LOG_FILE, _OWNS_FAULT_HANDLER

    with _LOCK:
        if not _INSTALLED:
            return

        log_event(reason)
        if sys.excepthook is _sys_exception_hook:
            sys.excepthook = _PREVIOUS_SYS_EXCEPTHOOK or sys.__excepthook__
        if (hasattr(threading, "excepthook")
                and threading.excepthook is _thread_exception_hook):
            threading.excepthook = (
                _PREVIOUS_THREADING_EXCEPTHOOK
                or threading.__excepthook__)
        if (hasattr(sys, "unraisablehook")
                and sys.unraisablehook is _unraisable_exception_hook):
            sys.unraisablehook = (
                _PREVIOUS_UNRAISABLEHOOK
                or sys.__unraisablehook__)

        if _OWNS_FAULT_HANDLER:
            try:
                faulthandler.disable()
            except Exception:
                pass
        _OWNS_FAULT_HANDLER = False

        if _NATIVE_LOG_FILE is not None:
            try:
                _NATIVE_LOG_FILE.flush()
                _NATIVE_LOG_FILE.close()
            except Exception:
                pass
            _NATIVE_LOG_FILE = None

        for logger in (_APP_LOGGER, _CRASH_LOGGER):
            if logger is None:
                continue
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                try:
                    handler.flush()
                    handler.close()
                except Exception:
                    pass

        _APP_LOGGER = None
        _CRASH_LOGGER = None
        _INSTALLED = False


def _atexit_report():
    if not _INSTALLED:
        return
    if _FATAL_EXCEPTION_SEEN:
        message = "Python process exiting after a recorded fatal exception"
    else:
        message = "Python process exiting without a recorded fatal exception"
    try:
        log_event(message)
    except Exception:
        pass
