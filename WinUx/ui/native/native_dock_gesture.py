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


def screen_point_in_client(hwnd, screen_position):
    """Return True only when a desktop point is inside ``hwnd`` client area.

    ``ScreenToClient`` deliberately converts points outside a window too, so it
    cannot by itself be used as a docking hit-test.  Native floating windows
    move in desktop coordinates while Dear PyGui layout rectangles are owner
    client-relative.  This strict gate prevents a stale renderer mouse position
    (or an accidental screen/client coordinate match) from keeping a dock
    target alive after the cursor has left WinUx.
    """
    if os.name != "nt" or not hwnd or screen_position is None:
        return False
    try:
        user32 = ctypes.windll.user32
        rect = wintypes.RECT()
        origin = wintypes.POINT(0, 0)
        user32.GetClientRect.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.ClientToScreen.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        if not user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            return False
        if not user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(origin)):
            return False
        x, y = map(int, screen_position)
        left = int(origin.x)
        top = int(origin.y)
        right = left + max(0, int(rect.right - rect.left))
        bottom = top + max(0, int(rect.bottom - rect.top))
        # Match Win32 rectangle semantics: right/bottom are exclusive.
        return left <= x < right and top <= y < bottom
    except Exception:
        return False


def _native_caption_band(hwnd):
    """Return the usable native caption band as ``(top, bottom)`` offsets.

    Offsets are relative to the outer window rect.  The client area's screen
    origin gives the lower edge of the non-client caption.  The upper edge is
    the resize-frame thickness, keeping the handoff away from the resize border.
    """
    if os.name != "nt" or not hwnd:
        return 4, 28
    try:
        user32 = ctypes.windll.user32
        rect = wintypes.RECT()
        client = wintypes.RECT()
        origin = wintypes.POINT(0, 0)
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            return 4, 28
        if not user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(client)):
            return 4, 28
        if not user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(origin)):
            return 4, 28
        client_top = max(1, int(origin.y - rect.top))
        # SM_CYFRAME (33) + SM_CXPADDEDBORDER (92) is the top resize border.
        frame = max(0, int(user32.GetSystemMetrics(33)))
        padded = max(0, int(user32.GetSystemMetrics(92)))
        top = max(2, frame + padded)
        bottom = max(top + 6, client_top - 1)
        return top, bottom
    except Exception:
        return 4, 28


def resolve_drag_anchor(anchor, target_width, caption_band=None):
    """Map a dock-title grab point onto the floating native title bar.

    Preferred anchors carry ``(x, y, source_width, source_height)``.  Both axes
    are mapped proportionally, so the exact point held inside the embedded title
    bar remains under the cursor after tear-off.  Older 2/3-value anchors remain
    supported.  ``caption_band`` is the actual native caption's vertical range
    relative to the outer HWND and guarantees that the cursor is on HTCAPTION,
    never above it on the resize frame or below it in the client area.
    """
    if not isinstance(anchor, (tuple, list)) or len(anchor) < 2:
        return None
    try:
        width = max(1, int(target_width))
        source_x = float(anchor[0])
        source_y = float(anchor[1])
        if len(anchor) >= 3 and float(anchor[2]) > 1.0:
            ratio_x = max(0.0, min(1.0, source_x / float(anchor[2])))
            x = int(round(ratio_x * width))
        else:
            x = int(round(source_x))
        x = max(8, min(x, max(8, width - 32)))

        top, bottom = caption_band or (4, 28)
        top, bottom = int(top), int(bottom)
        if bottom <= top:
            bottom = top + 20
        if len(anchor) >= 4 and float(anchor[3]) > 1.0:
            ratio_y = max(0.0, min(1.0, source_y / float(anchor[3])))
            # Stay one pixel inside the native caption band at both edges.
            y = int(round((top + 1) + ratio_y * max(1, bottom - top - 2)))
        else:
            # Legacy anchor: preserve the requested y as much as possible, but
            # force it inside the native caption so HTCAPTION is guaranteed.
            y = int(round(source_y))
        y = max(top + 1, min(y, bottom - 1))
        return x, y
    except (TypeError, ValueError, OverflowError, IndexError):
        return None

def reveal_prepared_dock(hwnd, anchor=None, begin_move=False):
    """Reveal an already-rendered detached dock synchronously from the owner.

    The child process still receives the ordinary ``activate`` command and
    remains the authority for subsequent rendering.  This helper only removes
    the IPC scheduling round-trip from the user's tear-off gesture: position
    the resident HWND under the grabbed title point, show its last settled
    frame, and optionally enter the native caption move loop immediately.
    """
    if os.name != "nt" or not hwnd:
        return False
    try:
        hwnd = int(hwnd)
        user32 = ctypes.windll.user32
        point = cursor_position()
        if point is not None and isinstance(anchor, (tuple, list)) and len(anchor) >= 2:
            rect = wintypes.RECT()
            user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            if user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
                width = max(1, int(rect.right - rect.left))
                resolved = resolve_drag_anchor(anchor, width, _native_caption_band(hwnd))
                if resolved is not None:
                    ax, ay = resolved
                    user32.SetWindowPos.argtypes = [
                        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                        ctypes.c_int, ctypes.c_int, wintypes.UINT]
                    user32.SetWindowPos(
                        wintypes.HWND(hwnd), None, int(point[0]) - ax, int(point[1]) - ay,
                        0, 0, 0x0001 | 0x0004 | 0x0010)
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow(wintypes.HWND(hwnd), 4)  # SW_SHOWNOACTIVATE
        if begin_move and point is not None:
            user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
            user32.GetAsyncKeyState.restype = ctypes.c_short
            if int(user32.GetAsyncKeyState(1)) & 0x8000:
                try:
                    user32.SetForegroundWindow(wintypes.HWND(hwnd))
                except Exception:
                    pass
                packed = (int(point[0]) & 0xffff) | ((int(point[1]) & 0xffff) << 16)
                user32.PostMessageW(
                    wintypes.HWND(hwnd), 0x00A1, 2, packed)  # WM_NCLBUTTONDOWN/HTCAPTION
        return True
    except Exception:
        return False
