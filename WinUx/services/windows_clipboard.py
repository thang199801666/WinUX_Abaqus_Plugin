"""Windows file clipboard integration used by WinUX.

The Windows shell represents copied/cut filesystem items with ``CF_HDROP`` and
stores the requested operation in the registered ``Preferred DropEffect``
format.  Reading and writing those formats lets WinUX exchange files and
folders directly with Windows Explorer without adding a pywin32 dependency.
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple


CF_HDROP = 15
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040
DROP_EFFECT_COPY = 0x00000001
DROP_EFFECT_MOVE = 0x00000002

_PREFERRED_DROP_EFFECT_NAME = "Preferred DropEffect"
_WINUX_TOKEN_FORMAT_NAME = "WinUX Clipboard Token"


@dataclass(frozen=True)
class FileClipboardData:
    """Filesystem entries currently published by the Windows clipboard."""

    paths: Tuple[str, ...]
    move: bool = False
    token: Optional[str] = None


class _DROPFILES(ctypes.Structure):
    _fields_ = [
        ("pFiles", wintypes.DWORD),
        ("pt", wintypes.POINT),
        ("fNC", wintypes.BOOL),
        ("fWide", wintypes.BOOL),
    ]


if os.name == "nt":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _shell32 = ctypes.WinDLL("shell32", use_last_error=True)

    _user32.OpenClipboard.argtypes = [wintypes.HWND]
    _user32.OpenClipboard.restype = wintypes.BOOL
    _user32.CloseClipboard.argtypes = []
    _user32.CloseClipboard.restype = wintypes.BOOL
    _user32.EmptyClipboard.argtypes = []
    _user32.EmptyClipboard.restype = wintypes.BOOL
    _user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    _user32.SetClipboardData.restype = wintypes.HANDLE
    _user32.GetClipboardData.argtypes = [wintypes.UINT]
    _user32.GetClipboardData.restype = wintypes.HANDLE
    _user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    _user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    _user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    _user32.RegisterClipboardFormatW.restype = wintypes.UINT
    _user32.GetClipboardSequenceNumber.argtypes = []
    _user32.GetClipboardSequenceNumber.restype = wintypes.DWORD

    _kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    _kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalLock.restype = ctypes.c_void_p
    _kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalUnlock.restype = wintypes.BOOL
    _kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalFree.restype = wintypes.HGLOBAL

    _shell32.DragQueryFileW.argtypes = [
        wintypes.HANDLE,
        wintypes.UINT,
        wintypes.LPWSTR,
        wintypes.UINT,
    ]
    _shell32.DragQueryFileW.restype = wintypes.UINT

    _preferred_drop_effect_format = int(
        _user32.RegisterClipboardFormatW(_PREFERRED_DROP_EFFECT_NAME)
    )
    _winux_token_format = int(
        _user32.RegisterClipboardFormatW(_WINUX_TOKEN_FORMAT_NAME)
    )
else:
    _user32 = None
    _kernel32 = None
    _shell32 = None
    _preferred_drop_effect_format = 0
    _winux_token_format = 0


class _ClipboardSession:
    """Retrying clipboard lock used by Explorer and WinUX concurrently."""

    def __init__(self, attempts: int = 40, delay: float = 0.01):
        self.attempts = max(1, int(attempts))
        self.delay = max(0.0, float(delay))
        self.opened = False

    def __enter__(self):
        if os.name != "nt":
            return self
        for _attempt in range(self.attempts):
            if _user32.OpenClipboard(None):
                self.opened = True
                return self
            time.sleep(self.delay)
        error = ctypes.get_last_error()
        raise OSError(error, "The Windows clipboard is busy")

    def __exit__(self, exc_type, exc_value, traceback):
        if self.opened:
            _user32.CloseClipboard()
            self.opened = False
        return False


def is_supported() -> bool:
    return os.name == "nt"


def sequence_number() -> int:
    """Return the Windows clipboard sequence number, or zero elsewhere."""
    if os.name != "nt":
        return 0
    return int(_user32.GetClipboardSequenceNumber())


def _allocate_bytes(data: bytes):
    handle = _kernel32.GlobalAlloc(
        GMEM_MOVEABLE | GMEM_ZEROINIT, max(1, len(data))
    )
    if not handle:
        error = ctypes.get_last_error()
        raise MemoryError(error, "GlobalAlloc failed for clipboard data")
    pointer = _kernel32.GlobalLock(handle)
    if not pointer:
        error = ctypes.get_last_error()
        _kernel32.GlobalFree(handle)
        raise OSError(error, "GlobalLock failed for clipboard data")
    try:
        if data:
            ctypes.memmove(pointer, data, len(data))
    finally:
        _kernel32.GlobalUnlock(handle)
    return handle


def _publish_bytes(format_id: int, data: bytes) -> None:
    handle = _allocate_bytes(data)
    if not _user32.SetClipboardData(int(format_id), handle):
        error = ctypes.get_last_error()
        _kernel32.GlobalFree(handle)
        raise OSError(error, "SetClipboardData failed")
    # Ownership transfers to Windows after SetClipboardData succeeds.


def _dropfiles_payload(paths: Iterable[os.PathLike]) -> bytes:
    normalized = []
    for value in paths:
        path = os.path.abspath(os.path.expandvars(os.path.expanduser(os.fspath(value))))
        if path and path not in normalized:
            normalized.append(path)
    if not normalized:
        raise ValueError("No filesystem paths were supplied to the clipboard")

    names = ("\0".join(normalized) + "\0\0").encode("utf-16-le")
    header = _DROPFILES()
    header.pFiles = ctypes.sizeof(_DROPFILES)
    header.pt = wintypes.POINT(0, 0)
    header.fNC = False
    header.fWide = True
    return bytes(header) + names


def set_file_drop(paths: Iterable[os.PathLike], move: bool = False,
                  token: Optional[str] = None) -> int:
    """Publish local files/folders for Windows Explorer copy or cut.

    Returns the resulting clipboard sequence number.  On non-Windows systems
    the function is a no-op and returns zero.
    """
    if os.name != "nt":
        return 0

    drop_payload = _dropfiles_payload(paths)
    effect = DROP_EFFECT_MOVE if move else DROP_EFFECT_COPY
    effect_payload = int(effect).to_bytes(4, byteorder="little", signed=False)
    token_payload = ((str(token) if token else "") + "\0").encode("utf-16-le")

    with _ClipboardSession():
        if not _user32.EmptyClipboard():
            error = ctypes.get_last_error()
            raise OSError(error, "EmptyClipboard failed")
        _publish_bytes(CF_HDROP, drop_payload)
        if _preferred_drop_effect_format:
            _publish_bytes(_preferred_drop_effect_format, effect_payload)
        if token and _winux_token_format:
            _publish_bytes(_winux_token_format, token_payload)

    return sequence_number()


def _read_dword(format_id: int) -> Optional[int]:
    if not format_id or not _user32.IsClipboardFormatAvailable(format_id):
        return None
    handle = _user32.GetClipboardData(format_id)
    if not handle:
        return None
    pointer = _kernel32.GlobalLock(handle)
    if not pointer:
        return None
    try:
        return int(ctypes.c_uint32.from_address(pointer).value)
    finally:
        _kernel32.GlobalUnlock(handle)


def _read_text(format_id: int) -> Optional[str]:
    if not format_id or not _user32.IsClipboardFormatAvailable(format_id):
        return None
    handle = _user32.GetClipboardData(format_id)
    if not handle:
        return None
    pointer = _kernel32.GlobalLock(handle)
    if not pointer:
        return None
    try:
        value = ctypes.wstring_at(pointer)
        return value or None
    finally:
        _kernel32.GlobalUnlock(handle)


def get_file_drop() -> Optional[FileClipboardData]:
    """Read Explorer-compatible file paths and the copy/cut operation."""
    if os.name != "nt" or not _user32.IsClipboardFormatAvailable(CF_HDROP):
        return None

    with _ClipboardSession():
        handle = _user32.GetClipboardData(CF_HDROP)
        if not handle:
            return None
        count = int(_shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0))
        paths = []
        for index in range(count):
            length = int(_shell32.DragQueryFileW(handle, index, None, 0))
            if length <= 0:
                continue
            buffer = ctypes.create_unicode_buffer(length + 1)
            copied = int(
                _shell32.DragQueryFileW(handle, index, buffer, length + 1)
            )
            if copied:
                paths.append(buffer.value)

        effect = _read_dword(_preferred_drop_effect_format) or DROP_EFFECT_COPY
        token = _read_text(_winux_token_format)

    if not paths:
        return None
    return FileClipboardData(
        paths=tuple(paths),
        move=bool(effect & DROP_EFFECT_MOVE),
        token=token,
    )


def clear() -> None:
    """Clear the Windows clipboard, matching Explorer after a cut paste."""
    if os.name != "nt":
        return
    with _ClipboardSession():
        if not _user32.EmptyClipboard():
            error = ctypes.get_last_error()
            raise OSError(error, "EmptyClipboard failed")