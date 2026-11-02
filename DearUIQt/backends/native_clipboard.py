"""Win32 Unicode clipboard, independent of ImGui/GLFW clipboard callbacks."""
import ctypes
from ctypes import wintypes


def _api():
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.GetActiveWindow.restype = wintypes.HWND
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalSize.argtypes = [wintypes.HANDLE]
    kernel32.GlobalSize.restype = ctypes.c_size_t
    kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalFree.argtypes = [wintypes.HANDLE]
    kernel32.GlobalFree.restype = wintypes.HANDLE
    return user32, kernel32


def text():
    user32, kernel32 = _api()
    if not user32.OpenClipboard(None):
        return ''
    try:
        handle = user32.GetClipboardData(13)  # CF_UNICODETEXT
        pointer = kernel32.GlobalLock(handle) if handle else None
        if not pointer:
            return ''
        try:
            size = kernel32.GlobalSize(handle)
            return ctypes.string_at(pointer, size).decode('utf-16-le', errors='replace').split('\x00', 1)[0]
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_text(value):
    user32, kernel32 = _api()
    data = (str(value).replace('\x00', '') + '\x00').encode('utf-16-le')
    handle = kernel32.GlobalAlloc(0x02, len(data))  # GMEM_MOVEABLE
    if not handle:
        return False
    try:
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return False
        try:
            ctypes.memmove(pointer, data, len(data))
        finally:
            kernel32.GlobalUnlock(handle)
        if not user32.OpenClipboard(user32.GetActiveWindow()):
            return False
        try:
            if not user32.EmptyClipboard() or not user32.SetClipboardData(13, handle):
                return False
            handle = None  # Ownership transferred to the system.
            return True
        finally:
            user32.CloseClipboard()
    finally:
        if handle:
            kernel32.GlobalFree(handle)
