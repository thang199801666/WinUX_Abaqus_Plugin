"""Native local-directory change notifications for WinUX.

Windows uses ``ReadDirectoryChangesW`` so the local file pane reacts to changes
made by Explorer and other applications without periodic directory scans.  A
small polling fallback keeps the class testable on non-Windows platforms.
"""

from __future__ import annotations

import ctypes
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional


ChangeCallback = Callable[[Path], None]
ErrorCallback = Callable[[Path, BaseException], None]


class LocalFileSystemWatcher:
    """Watch one directory at a time from a daemon worker thread."""

    def __init__(
        self,
        callback: Optional[ChangeCallback] = None,
        *,
        on_error: Optional[ErrorCallback] = None,
        polling_interval: float = 0.75,
    ) -> None:
        self._callback = callback
        self._on_error = on_error
        self._polling_interval = max(0.20, float(polling_interval))
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._path: Optional[Path] = None
        self._native_stop_handle = None

    @property
    def path(self) -> Optional[Path]:
        with self._lock:
            return self._path

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    def watch(
        self,
        path,
        callback: Optional[ChangeCallback] = None,
    ) -> None:
        """Stop the previous watch and monitor ``path``.

        The callback is invoked on the watcher thread.  GUI clients must queue
        work back to their UI thread.
        """
        target = Path(path)
        if not target.is_dir():
            raise NotADirectoryError(str(target))

        self.stop()
        with self._lock:
            self._path = target
            if callback is not None:
                self._callback = callback
            self._stop_event = threading.Event()
            worker = threading.Thread(
                target=self._run,
                args=(target, self._stop_event),
                name="winux-local-file-watcher",
                daemon=True,
            )
            self._thread = worker
        worker.start()

    def stop(self, *, wait: bool = True, timeout: float = 2.0) -> None:
        with self._lock:
            worker = self._thread
            stop_event = self._stop_event
            native_stop = self._native_stop_handle
            self._thread = None
            self._path = None

            stop_event.set()
            # Serialize signalling with the worker closing this handle.
            if native_stop and os.name == "nt":
                try:
                    _KERNEL32.SetEvent(native_stop)
                except Exception:
                    pass
        if (wait and worker and
                worker is not threading.current_thread()):
            worker.join(timeout=max(0.0, float(timeout)))

    close = stop

    def _run(self, path: Path, stop_event: threading.Event) -> None:
        try:
            if os.name == "nt":
                self._run_windows(path, stop_event)
            else:
                self._run_polling(path, stop_event)
        except BaseException as exc:  # keep a daemon watcher from killing app
            if not stop_event.is_set():
                self._report_error(path, exc)
        finally:
            with self._lock:
                if self._thread is threading.current_thread():
                    self._thread = None
                    self._path = None

    def _notify(self, path: Path) -> None:
        callback = self._callback
        if callback is None:
            return
        try:
            callback(path)
        except BaseException as exc:
            self._report_error(path, exc)

    def _report_error(self, path: Path, exc: BaseException) -> None:
        callback = self._on_error
        if callback is None:
            return
        try:
            callback(path, exc)
        except Exception:
            pass

    @staticmethod
    def _snapshot(path: Path):
        rows = []
        with os.scandir(str(path)) as entries:
            for entry in entries:
                try:
                    stat = entry.stat(follow_symlinks=False)
                    rows.append((
                        entry.name,
                        entry.is_dir(follow_symlinks=False),
                        int(stat.st_size),
                        int(stat.st_mtime_ns),
                    ))
                except OSError:
                    rows.append((entry.name, False, -1, -1))
        rows.sort(key=lambda row: row[0].casefold())
        return tuple(rows)

    def _run_polling(self, path: Path, stop_event: threading.Event) -> None:
        previous = self._snapshot(path)
        while not stop_event.wait(self._polling_interval):
            current = self._snapshot(path)
            if current != previous:
                previous = current
                self._notify(path)

    def _run_windows(self, path: Path, stop_event: threading.Event) -> None:
        directory = _KERNEL32.CreateFileW(
            str(path),
            _FILE_LIST_DIRECTORY,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
            None,
            _OPEN_EXISTING,
            _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OVERLAPPED,
            None,
        )
        if directory == _INVALID_HANDLE_VALUE:
            raise ctypes.WinError(ctypes.get_last_error())

        changed_event = _KERNEL32.CreateEventW(None, True, False, None)
        native_stop = _KERNEL32.CreateEventW(None, True, False, None)
        if not changed_event or not native_stop:
            error = ctypes.WinError(ctypes.get_last_error())
            if changed_event:
                _KERNEL32.CloseHandle(changed_event)
            if native_stop:
                _KERNEL32.CloseHandle(native_stop)
            _KERNEL32.CloseHandle(directory)
            raise error

        with self._lock:
            if self._stop_event is stop_event:
                self._native_stop_handle = native_stop
        if stop_event.is_set():
            _KERNEL32.SetEvent(native_stop)

        buffer = ctypes.create_string_buffer(64 * 1024)
        handles = (_HANDLE * 2)(changed_event, native_stop)
        overlapped = _OVERLAPPED()
        overlapped.hEvent = changed_event
        bytes_returned = _DWORD()
        pending = False

        try:
            while not stop_event.is_set():
                _KERNEL32.ResetEvent(changed_event)
                overlapped.Internal = None
                overlapped.InternalHigh = None
                overlapped.Offset = 0
                overlapped.OffsetHigh = 0
                overlapped.hEvent = changed_event

                queued = _KERNEL32.ReadDirectoryChangesW(
                    directory,
                    buffer,
                    len(buffer),
                    False,
                    _NOTIFY_FILTER,
                    None,
                    ctypes.byref(overlapped),
                    None,
                )
                if not queued:
                    raise ctypes.WinError(ctypes.get_last_error())
                pending = True

                result = _KERNEL32.WaitForMultipleObjects(
                    2, handles, False, _INFINITE)
                if result == _WAIT_OBJECT_0 + 1:
                    break
                if result != _WAIT_OBJECT_0:
                    raise ctypes.WinError(ctypes.get_last_error())

                completed = _KERNEL32.GetOverlappedResult(
                    directory,
                    ctypes.byref(overlapped),
                    ctypes.byref(bytes_returned),
                    False,
                )
                pending = False
                if not completed:
                    error_code = ctypes.get_last_error()
                    if error_code == _ERROR_OPERATION_ABORTED and stop_event.is_set():
                        break
                    raise ctypes.WinError(error_code)
                self._notify(path)
        finally:
            if pending:
                # CancelIoEx only REQUESTS cancellation. Windows still owns
                # buffer/OVERLAPPED until completion has been acknowledged.
                # Never release them while an asynchronous write is pending.
                _cancel_io(directory, ctypes.byref(overlapped))
                _KERNEL32.GetOverlappedResult(
                    directory, ctypes.byref(overlapped),
                    ctypes.byref(bytes_returned), True)
            with self._lock:
                if self._native_stop_handle == native_stop:
                    self._native_stop_handle = None
                _KERNEL32.CloseHandle(native_stop)
            _KERNEL32.CloseHandle(changed_event)
            _KERNEL32.CloseHandle(directory)


if os.name == "nt":
    from ctypes import wintypes

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _HANDLE = wintypes.HANDLE
    _DWORD = wintypes.DWORD
    _BOOL = wintypes.BOOL

    class _OVERLAPPED(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_void_p),
            ("InternalHigh", ctypes.c_void_p),
            ("Offset", _DWORD),
            ("OffsetHigh", _DWORD),
            ("hEvent", _HANDLE),
        ]

    _KERNEL32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        _DWORD,
        _DWORD,
        ctypes.c_void_p,
        _DWORD,
        _DWORD,
        _HANDLE,
    ]
    _KERNEL32.CreateFileW.restype = _HANDLE
    _KERNEL32.CreateEventW.argtypes = [ctypes.c_void_p, _BOOL, _BOOL, wintypes.LPCWSTR]
    _KERNEL32.CreateEventW.restype = _HANDLE
    _KERNEL32.SetEvent.argtypes = [_HANDLE]
    _KERNEL32.SetEvent.restype = _BOOL
    _KERNEL32.ResetEvent.argtypes = [_HANDLE]
    _KERNEL32.ResetEvent.restype = _BOOL
    _KERNEL32.CloseHandle.argtypes = [_HANDLE]
    _KERNEL32.CloseHandle.restype = _BOOL
    _KERNEL32.ReadDirectoryChangesW.argtypes = [
        _HANDLE,
        ctypes.c_void_p,
        _DWORD,
        _BOOL,
        _DWORD,
        ctypes.POINTER(_DWORD),
        ctypes.POINTER(_OVERLAPPED),
        ctypes.c_void_p,
    ]
    _KERNEL32.ReadDirectoryChangesW.restype = _BOOL
    _KERNEL32.WaitForMultipleObjects.argtypes = [
        _DWORD,
        ctypes.POINTER(_HANDLE),
        _BOOL,
        _DWORD,
    ]
    _KERNEL32.WaitForMultipleObjects.restype = _DWORD
    _KERNEL32.GetOverlappedResult.argtypes = [
        _HANDLE,
        ctypes.POINTER(_OVERLAPPED),
        ctypes.POINTER(_DWORD),
        _BOOL,
    ]
    _KERNEL32.GetOverlappedResult.restype = _BOOL

    _cancel_io_ex = getattr(_KERNEL32, "CancelIoEx", None)
    if _cancel_io_ex is not None:
        _cancel_io_ex.argtypes = [_HANDLE, ctypes.POINTER(_OVERLAPPED)]
        _cancel_io_ex.restype = _BOOL

    def _cancel_io(handle, overlapped) -> None:
        if _cancel_io_ex is not None:
            try:
                _cancel_io_ex(handle, overlapped)
            except Exception:
                pass

    _FILE_LIST_DIRECTORY = 0x0001
    _FILE_SHARE_READ = 0x00000001
    _FILE_SHARE_WRITE = 0x00000002
    _FILE_SHARE_DELETE = 0x00000004
    _OPEN_EXISTING = 3
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _FILE_FLAG_OVERLAPPED = 0x40000000
    _FILE_NOTIFY_CHANGE_FILE_NAME = 0x00000001
    _FILE_NOTIFY_CHANGE_DIR_NAME = 0x00000002
    _FILE_NOTIFY_CHANGE_SIZE = 0x00000008
    _FILE_NOTIFY_CHANGE_LAST_WRITE = 0x00000010
    _FILE_NOTIFY_CHANGE_CREATION = 0x00000040
    _NOTIFY_FILTER = (
        _FILE_NOTIFY_CHANGE_FILE_NAME
        | _FILE_NOTIFY_CHANGE_DIR_NAME
        | _FILE_NOTIFY_CHANGE_SIZE
        | _FILE_NOTIFY_CHANGE_LAST_WRITE
        | _FILE_NOTIFY_CHANGE_CREATION
    )
    _WAIT_OBJECT_0 = 0x00000000
    _INFINITE = 0xFFFFFFFF
    _ERROR_OPERATION_ABORTED = 995
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
