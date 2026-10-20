"""Event-driven source identity cache; no directory walks in UI snapshots."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import struct
import threading
from typing import NamedTuple


class SourceSnapshot(NamedTuple):
    signature: tuple
    generation: int


def changed_names(data):
    """Decode FILE_NOTIFY_INFORMATION; None means overflow/invalid data."""
    if not data:
        return None
    names, offset = [], 0
    while True:
        if offset + 12 > len(data):
            return None
        next_offset, _action, length = struct.unpack_from("<III", data, offset)
        end = offset + 12 + length
        if length % 2 or end > len(data):
            return None
        try:
            names.append(data[offset + 12:end].decode("utf-16-le"))
        except UnicodeError:
            return None
        if not next_offset:
            return names
        if next_offset < 12 + length or offset + next_offset >= len(data):
            return None
        offset += next_offset


def affects_sources(name, package_name):
    parts = str(name).replace("/", "\\").split("\\")
    if not parts or parts[0].casefold() != package_name.casefold():
        return False
    if len(parts) == 1:
        return True
    if any(part in ("__pycache__", "Resources") or part.startswith(".") for part in parts[1:-1]):
        return False
    if parts[-1] in ("__pycache__", "Resources"):
        return False
    if parts[-1].startswith(".") and not parts[-1].endswith(".py"):
        return False
    # Notifications do not distinguish directories from files. Be conservative
    # inside the module tree: a dotted-directory rename can move Python files.
    return True


class _Overlapped(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE)]


class _DirectoryChanges:
    """One overlapped directory read, polled under the cache lock."""
    def __init__(self, directory):
        if os.name != "nt":
            raise OSError("native source notifications require Windows")
        self.kernel = ctypes.windll.kernel32
        k = self.kernel
        k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k.CreateFileW.restype = wintypes.HANDLE
        k.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        k.CreateEventW.restype = wintypes.HANDLE
        for name in ("SetEvent", "ResetEvent", "CloseHandle"):
            getattr(k, name).argtypes = [wintypes.HANDLE]
        k.ReadDirectoryChangesW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                           wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p,
                                           ctypes.POINTER(_Overlapped), ctypes.c_void_p]
        k.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Overlapped),
                                        ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
        k.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Overlapped)]
        k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.WaitForSingleObject.restype = wintypes.DWORD
        k.WaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
                                           wintypes.BOOL, wintypes.DWORD]
        k.WaitForMultipleObjects.restype = wintypes.DWORD
        k.GetLastError.argtypes = []
        k.GetLastError.restype = wintypes.DWORD
        self.handle = k.CreateFileW(str(directory), 1, 7, None, 3, 0x42000000, None)
        self.events = []
        self.pending = False
        self.buffer = ctypes.create_string_buffer(32768)
        if not self.handle or self.handle == ctypes.c_void_p(-1).value:
            self.handle = None
            raise OSError("could not watch source directory")
        try:
            for _ in range(3):
                event = k.CreateEventW(None, True, False, None)
                if not event:
                    raise OSError("could not create source-watch event")
                self.events.append(event)
            self._arm()
        except Exception:
            self.dispose()
            raise

    def _arm(self):
        self.kernel.ResetEvent(self.events[0])
        self.overlapped = _Overlapped()
        self.overlapped.hEvent = self.events[0]
        if not self.kernel.ReadDirectoryChangesW(self.handle, self.buffer, len(self.buffer), True,
                0x1 | 0x2 | 0x8 | 0x10, None, ctypes.byref(self.overlapped), None):
            if self.kernel.GetLastError() != 997:  # ERROR_IO_PENDING
                raise OSError("source notification read failed")
        self.pending = True

    def poll(self):
        state = self.kernel.WaitForSingleObject(self.events[0], 0)
        if state == 258:  # WAIT_TIMEOUT
            return []
        if state != 0:
            raise OSError("source notification event failed")
        count = wintypes.DWORD()
        success = self.kernel.GetOverlappedResult(self.handle, ctypes.byref(self.overlapped), ctypes.byref(count), False)
        self.pending = False
        if not success and self.kernel.GetLastError() != 1022:  # ERROR_NOTIFY_ENUM_DIR
            raise OSError("source notification result failed")
        names = changed_names(self.buffer.raw[:count.value]) if success else None
        self._arm()
        return names

    def wake(self):
        self.kernel.SetEvent(self.events[2])

    def clear_wake(self):
        self.kernel.ResetEvent(self.events[2])

    def stop(self):
        self.kernel.SetEvent(self.events[1])

    def wait(self):
        handles = (wintypes.HANDLE * 3)(*self.events)
        if self.kernel.WaitForMultipleObjects(3, handles, False, 500) == 0xffffffff:
            raise OSError("source notification wait failed")

    def dispose(self):
        # Only the reader thread disposes: cancelled I/O completes before its
        # OVERLAPPED/buffer/event storage is freed or handles are closed.
        if self.handle:
            if self.pending:
                self.kernel.CancelIoEx(self.handle, ctypes.byref(self.overlapped))
                count = wintypes.DWORD()
                self.kernel.GetOverlappedResult(self.handle, ctypes.byref(self.overlapped), ctypes.byref(count), True)
            self.kernel.CloseHandle(self.handle)
            self.handle = None
        for event in self.events:
            self.kernel.CloseHandle(event)
        self.events = []


class SourceSignatureCache:
    def __init__(self, root, scan, on_refresh):
        self.root = Path(root)
        self.scan, self.on_refresh = scan, on_refresh
        self._lock = threading.Lock()
        self._signature = None
        self._generation = 0
        self._backend = None
        self.failed = self._closed = False
        self.thread = threading.Thread(target=self._run, name="dialog-source-watch", daemon=True)
        self.thread.start()

    @property
    def generation(self):
        with self._lock:
            return self._generation

    def _poll_locked(self):
        names = self._backend.poll()
        if names is None or any(affects_sources(name, self.root.name) for name in names):
            self._generation += 1
            self._signature = None
            self._backend.wake()

    def snapshot(self):
        with self._lock:
            if self._closed or self.failed or self._backend is None:
                return None
            try:
                self._poll_locked()
            except OSError:
                self._generation += 1
                self._signature = None
                self.failed = True
                self._backend.stop()
                return None
            if self._signature is None:
                return None
            return SourceSnapshot(self._signature, self._generation)

    def _run(self):
        backend = None
        try:
            # Watching the parent also catches replacement/rename of the root.
            backend = _DirectoryChanges(self.root.parent)
            with self._lock:
                self._backend = backend
            while True:
                with self._lock:
                    if self._closed or self.failed:
                        break
                    self._poll_locked()
                    needs_scan = self._signature is None
                    generation = self._generation
                    if needs_scan:
                        backend.clear_wake()
                if needs_scan:
                    signature = self.scan()  # Expensive filesystem work off UI.
                    with self._lock:
                        if self._closed or self.failed:
                            break
                        self._poll_locked()
                        if generation != self._generation:
                            continue
                        self._signature = signature
                        snapshot = SourceSnapshot(signature, generation)
                    self.on_refresh(snapshot)  # Never hold the cache lock here.
                backend.wait()
        except Exception:
            with self._lock:
                if not self.failed:
                    self._generation += 1
                    self._signature = None
                self.failed = True
        finally:
            with self._lock:
                self._backend = None
            if backend is not None:
                backend.dispose()

    def close(self):
        with self._lock:
            self._closed = True
            if self._backend is not None:
                self._backend.stop()
