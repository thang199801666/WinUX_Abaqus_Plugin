"""Native move-loop observation without calling DPG inside a WNDPROC."""
import ctypes
import os
from ctypes import wintypes

PROPERTY = "WinUx.NativeDockGesture"


def release_owner_capture(view):
    """Release GLFW's initiating capture, never another window's capture."""
    if os.name != "nt":
        return
    resolver = getattr(view, "_find_main_viewport_hwnd", None)
    owner = resolver() if callable(resolver) else 0
    if not owner:
        return
    user32 = ctypes.windll.user32
    user32.GetCapture.restype = wintypes.HWND
    if int(user32.GetCapture() or 0) == int(owner):
        user32.ReleaseCapture()


def set_gesture(hwnd, mode):
    if os.name != "nt":
        return
    user32 = ctypes.windll.user32
    user32.SetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.HANDLE]
    user32.RemovePropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
    user32.RemovePropW.restype = wintypes.HANDLE
    if mode:
        user32.SetPropW(hwnd, PROPERTY, mode)
    else:
        user32.RemovePropW(hwnd, PROPERTY)


def gesture_mode(hwnd):
    if os.name != "nt" or not hwnd:
        return 0
    user32 = ctypes.windll.user32
    user32.GetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
    user32.GetPropW.restype = wintypes.HANDLE
    return int(user32.GetPropW(hwnd, PROPERTY) or 0)


def cursor_position():
    if os.name != "nt":
        return None
    point = wintypes.POINT()
    user32 = ctypes.windll.user32
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    if user32.GetCursorPos(ctypes.byref(point)):
        return point.x, point.y
    return None


def client_position(hwnd, screen_position):
    if os.name != "nt" or not hwnd or screen_position is None:
        return None
    point = wintypes.POINT(*map(int, screen_position))
    user32 = ctypes.windll.user32
    user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    if user32.ScreenToClient(hwnd, ctypes.byref(point)):
        return point.x, point.y
    return None
