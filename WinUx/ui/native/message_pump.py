"""Service native window messages during non-rendering UI-thread waits."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import time


def pump_native_messages(max_messages=64):
    """Pump a bounded batch without rendering or invoking DPG callbacks.

    PeekMessage also dispatches synchronous cross-thread sent messages. An IPC
    Queue.get() alone cannot do this: an owned window's activation can then
    block its owner while the child waits for an ACK from that same owner.
    """
    if os.name != "nt":
        return True
    user32 = ctypes.windll.user32
    user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                   wintypes.UINT, wintypes.UINT, wintypes.UINT]
    user32.PeekMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = ctypes.c_ssize_t
    message = wintypes.MSG()
    for _ in range(max(1, int(max_messages))):
        if not user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
            break
        if message.message == 0x0012:  # WM_QUIT must not disappear into a wait.
            return False
        user32.TranslateMessage(ctypes.byref(message))
        user32.DispatchMessageW(ctypes.byref(message))
    return True

def wait_native_messages(timeout_ms=16, max_messages=64):
    """Sleep efficiently until native input/IPC wake traffic or timeout.

    Qt's GUI thread blocks in the platform dispatcher when no events are ready;
    it does not poll with time.sleep().  A dialog IPC reader calls
    ``wake_native_window`` after queueing a command, so MsgWait returns
    immediately and a hidden retained dialog can reopen without a polling delay.
    """
    timeout_ms = max(0, int(timeout_ms))
    if os.name != "nt":
        time.sleep(timeout_ms / 1000.0)
        return True
    if not pump_native_messages(max_messages):
        return False
    user32 = ctypes.windll.user32
    user32.MsgWaitForMultipleObjects.argtypes = [
        wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL,
        wintypes.DWORD, wintypes.DWORD,
    ]
    user32.MsgWaitForMultipleObjects.restype = wintypes.DWORD
    user32.MsgWaitForMultipleObjects(0, None, False, timeout_ms, 0x04FF)
    return True


__all__ = ["pump_native_messages", "wait_native_messages"]
