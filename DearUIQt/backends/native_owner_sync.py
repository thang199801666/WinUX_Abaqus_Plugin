"""Compatibility for native ABI 1 renderers that replay HWND ownership.

The bundled bridge calls SetWindowLongPtrW(GWLP_HWNDPARENT) every render.
Even an unchanged owner resets DWM's caption hot state without sending a
window message, so a WNDPROC filter cannot fix it. Interpose only this import
in the loaded renderer, not USER32 or other modules. Actual owner/style/proc
changes go through unchanged. No executable code or on-disk DLL is modified.

Remove this adapter when the bundled bridge compares the owner before writing.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
import threading


_installed = {}  # Keep callbacks alive as long as their loaded modules.
_lock = threading.Lock()


def _owner_setter(original, getter, is_window, clear_error):
    def set_window_long(hwnd, index, value):
        if index == -8 and is_window(hwnd):  # GWLP_HWNDPARENT
            current = getter(hwnd, index)
            if current == value:
                # Match a successful SetWindowLongPtr, including zero owners.
                clear_error(0)
                return current
        return original(hwnd, index, value)
    return set_window_long


def _import_slot(base):
    """Find the named USER32 import in a validated, loaded PE32+ image."""
    def u16(offset):
        return ctypes.c_uint16.from_address(base + offset).value

    def u32(offset):
        return ctypes.c_uint32.from_address(base + offset).value

    if u16(0) != 0x5A4D:
        return None
    pe = u32(60)
    if pe > 0x100000 or u32(pe) != 0x4550 or u16(pe + 24) != 0x20B:
        return None
    size = u32(pe + 24 + 56)
    directory = u32(pe + 24 + 120)
    directory_size = u32(pe + 24 + 124)
    if not directory or directory + directory_size > size:
        return None

    def string(rva):
        if not 0 < rva < size:
            return b''
        # Bound reads to this mapped image, including malformed import names.
        return ctypes.string_at(base + rva, min(256, size - rva)).split(b'\0', 1)[0]

    for descriptor in range(directory, directory + directory_size - 19, 20):
        name = u32(descriptor + 12)
        if not name:
            break
        if string(name).lower() != b'user32.dll':
            continue
        names, slots = u32(descriptor), u32(descriptor + 16)
        if not names or not slots:
            return None
        while names + 8 <= size and slots + 8 <= size:
            entry = ctypes.c_uint64.from_address(base + names).value
            if not entry:
                break
            if not entry & (1 << 63) and string(entry + 2) == b'SetWindowLongPtrW':
                return base + slots
            names += 8
            slots += 8
    return None


def install_owner_sync_guard(extension):
    """Install once per loaded native renderer; leave unsupported builds alone."""
    path = getattr(extension, '__file__', None)
    if os.name != 'nt' or ctypes.sizeof(ctypes.c_void_p) != 8 or not isinstance(path, str):
        return False
    with _lock:
        kernel = ctypes.windll.kernel32
        kernel.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel.GetModuleHandleW.restype = ctypes.c_void_p
        base = kernel.GetModuleHandleW(path)
        if not base:
            return False
        if base in _installed:
            return True
        try:
            slot = _import_slot(base)
            if slot is None:
                return False
            address = ctypes.c_void_p.from_address(slot).value
            if not address:
                return False
            prototype = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND,
                                           ctypes.c_int, ctypes.c_ssize_t)
            original = prototype(address)
            user32 = ctypes.windll.user32
            getter = user32.GetWindowLongPtrW
            getter.argtypes = [wintypes.HWND, ctypes.c_int]
            getter.restype = ctypes.c_ssize_t
            user32.IsWindow.argtypes = [wintypes.HWND]
            user32.IsWindow.restype = wintypes.BOOL
            kernel.SetLastError.argtypes = [wintypes.DWORD]
            kernel.SetLastError.restype = None
            callback = prototype(_owner_setter(original, getter, user32.IsWindow,
                                               kernel.SetLastError))
            protect = kernel.VirtualProtect
            protect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD,
                                ctypes.POINTER(wintypes.DWORD)]
            protect.restype = wintypes.BOOL
            previous = wintypes.DWORD()
            if not protect(slot, 8, 0x04, ctypes.byref(previous)):  # PAGE_READWRITE
                return False
            # Publish the lifetime reference before making the callback callable.
            _installed[base] = (callback, original)
            ctypes.c_void_p.from_address(slot).value = ctypes.cast(callback, ctypes.c_void_p).value
            ignored = wintypes.DWORD()
            if not protect(slot, 8, previous.value, ctypes.byref(ignored)):
                logging.getLogger(__name__).warning('Could not restore renderer import-page protection')
            return True
        except Exception:
            logging.getLogger(__name__).exception('Could not install native owner-sync compatibility guard')
            return False
