"""Foreground pointer-input gate for Dear PyGui overlays and widgets.

Dear PyGui mouse handlers registered in a global ``handler_registry`` receive
mouse events even when another Dear PyGui window is visually on top.  Without
an explicit z-order/input gate, pressing a floating dialog, popup or dock can
therefore also start selection, rubber-band or drag actions in an Explorer view
behind it.

This module provides one small application-level contract:

* foreground surfaces register themselves with
  :func:`register_pointer_protected_item`;
* background/global handlers call :func:`pointer_input_is_blocked` before doing
  any mouse work;
* a press that starts on a protected surface remains captured until after the
  physical mouse button is released, even if the pointer leaves that surface;
* explicit gestures (for example dragging a dock title bar while reparenting)
  can take stronger ownership with :func:`acquire_pointer_input`.

The implementation intentionally uses screen-space item rectangles as a
fallback. ``get_item_pos`` is parent-relative for many child widgets and was a
major source of click-through when overlays were nested or reparented.
"""

from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes

import dearpygui.dearpygui as dpg


_pointer_owner = None
_protected_items = set()
_surface_press_item = None
_release_guard_until_frame = -1
_native_gate_lock = threading.RLock()
_native_pointer_hwnds = set()
_native_modal_tokens = set()
_native_modal_release_pending = False
_native_modal_release_guard_until_frame = -1
_native_surface_press_hwnd = None
_native_release_guard_until_frame = -1




def register_native_pointer_surface(hwnd):
    """Register a real top-level HWND as a foreground pointer surface.

    Native Tk/Qt-like dialogs live outside Dear PyGui's item tree, therefore
    DPG's global handler registries cannot know that the pointer is currently
    over them.  Tracking the HWND lets WinUx suppress background DPG input in
    exactly the same way as a Qt top-level window naturally consumes it.
    """
    try:
        hwnd = int(hwnd or 0)
    except Exception:
        hwnd = 0
    if hwnd:
        with _native_gate_lock:
            _native_pointer_hwnds.add(hwnd)
    return hwnd or None


def unregister_native_pointer_surface(hwnd):
    try:
        hwnd = int(hwnd or 0)
    except Exception:
        hwnd = 0
    if hwnd:
        with _native_gate_lock:
            _native_pointer_hwnds.discard(hwnd)


def acquire_native_modal_input(owner):
    """Block all Dear PyGui pointer input while a native modal is visible."""
    global _native_modal_release_pending, _native_modal_release_guard_until_frame
    if owner is None:
        return False
    with _native_gate_lock:
        _native_modal_tokens.add(owner)
        _native_modal_release_pending = False
        _native_modal_release_guard_until_frame = -1
    return True


def release_native_modal_input(owner):
    global _native_modal_release_pending, _native_modal_release_guard_until_frame
    if owner is None:
        return False
    with _native_gate_lock:
        existed = owner in _native_modal_tokens
        _native_modal_tokens.discard(owner)
        if existed and not _native_modal_tokens:
            # The native command usually runs on mouse-up. Keep Dear PyGui
            # blocked until a future rendered frame so the same release cannot
            # be replayed into a row/button/splitter behind the closing dialog.
            _native_modal_release_pending = True
            _native_modal_release_guard_until_frame = -1
    return existed


def native_modal_input_active():
    with _native_gate_lock:
        return bool(_native_modal_tokens)


def _native_cursor_position():
    if os.name != "nt":
        return None
    try:
        point = wintypes.POINT()
        user32 = ctypes.windll.user32
        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.GetCursorPos.restype = wintypes.BOOL
        if not user32.GetCursorPos(ctypes.byref(point)):
            return None
        return float(point.x), float(point.y)
    except Exception:
        return None


def _native_surface_under_pointer():
    """Return the visible registered HWND under the desktop cursor, if any."""
    if os.name != "nt":
        return None
    point = _native_cursor_position()
    if point is None:
        return None
    px, py = point
    with _native_gate_lock:
        hwnds = tuple(_native_pointer_hwnds)
    stale = []
    try:
        user32 = ctypes.windll.user32
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        for hwnd in hwnds:
            native = wintypes.HWND(int(hwnd))
            if not user32.IsWindow(native):
                stale.append(hwnd)
                continue
            if not user32.IsWindowVisible(native):
                continue
            rect = wintypes.RECT()
            if not user32.GetWindowRect(native, ctypes.byref(rect)):
                continue
            if rect.left <= px < rect.right and rect.top <= py < rect.bottom:
                return int(hwnd)
    except Exception:
        return None
    finally:
        if stale:
            with _native_gate_lock:
                for hwnd in stale:
                    _native_pointer_hwnds.discard(hwnd)
    return None


def native_background_input_blocked():
    """Return True when native dialog/window interaction owns the pointer.

    Modal dialogs block the complete WinUx viewport. Modeless/tool dialogs only
    block while the cursor is over their HWND.  A press that begins on a native
    window remains captured through mouse-up so dragging out of the dialog
    cannot suddenly resize/select Dear PyGui widgets underneath.
    """
    global _native_surface_press_hwnd, _native_release_guard_until_frame

    global _native_modal_release_pending, _native_modal_release_guard_until_frame

    if native_modal_input_active():
        return True

    down = _mouse_button_down()
    frame = _frame_count()
    with _native_gate_lock:
        release_pending = bool(_native_modal_release_pending)
        release_until = int(_native_modal_release_guard_until_frame)
    if release_pending:
        if down:
            return True
        if release_until < 0:
            release_until = frame + 1
            with _native_gate_lock:
                _native_modal_release_guard_until_frame = release_until
        if frame <= release_until:
            return True
        with _native_gate_lock:
            _native_modal_release_pending = False
            _native_modal_release_guard_until_frame = -1

    if _native_surface_press_hwnd is not None:
        if down:
            _native_release_guard_until_frame = -1
            return True
        if _native_release_guard_until_frame < 0:
            _native_release_guard_until_frame = frame + 1
        if frame <= _native_release_guard_until_frame:
            return True
        _native_surface_press_hwnd = None
        _native_release_guard_until_frame = -1

    hwnd = _native_surface_under_pointer()
    if hwnd is not None:
        if down:
            _native_surface_press_hwnd = hwnd
            _native_release_guard_until_frame = -1
        return True
    return False


def register_pointer_protected_item(item):
    """Register a foreground surface that must consume pointer interaction.

    The registered item may be a complete window/child-window or a smaller
    interaction surface.  Descendant controls are covered by the parent's
    screen rectangle, so one registration is normally sufficient for a whole
    dialog/widget.
    """
    if item is not None:
        _protected_items.add(item)
    return item


def unregister_pointer_protected_item(item):
    if item is not None:
        _protected_items.discard(item)
        # Deliberately do not clear _surface_press_item here. A popup may hide
        # or delete itself from its click callback before global background
        # handlers receive the same mouse-up. The gesture must stay captured
        # through release even after the originating surface is gone.


def acquire_pointer_input(owner):
    """Capture global pointer input for *owner* until explicitly released."""
    global _pointer_owner
    if owner is None:
        return False
    if _pointer_owner is None or _pointer_owner is owner:
        _pointer_owner = owner
        return True
    return False


def release_pointer_input(owner=None):
    """Release explicit pointer capture when owned by *owner* (or always)."""
    global _pointer_owner
    if owner is None or _pointer_owner is owner:
        _pointer_owner = None
        return True
    return False


def _mouse_position():
    try:
        return tuple(map(float, dpg.get_mouse_pos(local=False)))
    except Exception:
        return None


def _mouse_button_down():
    """Return True while any ordinary pointer button is physically held."""
    for name in (
        "mvMouseButton_Left",
        "mvMouseButton_Right",
        "mvMouseButton_Middle",
    ):
        button = getattr(dpg, name, None)
        if button is None:
            continue
        try:
            if dpg.is_mouse_button_down(button):
                return True
        except Exception:
            continue
    # A native Tk dialog receives the actual button messages instead of GLFW.
    # Query the physical state as a fallback so native-surface capture remains
    # correct even while Dear PyGui itself never saw the press.
    if os.name == "nt":
        try:
            user32 = ctypes.windll.user32
            for vk in (0x01, 0x02, 0x04):  # left, right, middle
                if int(user32.GetAsyncKeyState(vk)) & 0x8000:
                    return True
        except Exception:
            pass
    return False


def _frame_count():
    try:
        return int(dpg.get_frame_count())
    except Exception:
        return 0


def _item_contains_mouse(item, mouse=None):
    """Hit-test *item* in viewport/screen coordinates.

    ``is_item_hovered`` is preferred when the backend exposes reliable state.
    For windows/containers where that state may be unavailable, use
    ``get_item_rect_min`` + ``get_item_rect_size``.  Only as a final compatibility
    fallback do we use ``get_item_pos``.
    """
    try:
        if not dpg.does_item_exist(item):
            return False
        try:
            if not dpg.is_item_shown(item):
                return False
        except Exception:
            pass

        try:
            if dpg.is_item_hovered(item):
                return True
        except Exception:
            try:
                state = dpg.get_item_state(item) or {}
                if bool(state.get("hovered", False)):
                    return True
            except Exception:
                pass

        mouse = mouse or _mouse_position()
        if mouse is None:
            return False
        mx, my = mouse

        rect_min = None
        getter = getattr(dpg, "get_item_rect_min", None)
        if getter is not None:
            try:
                rect_min = tuple(map(float, getter(item)))
            except Exception:
                rect_min = None
        if rect_min is None:
            try:
                rect_min = tuple(map(float, dpg.get_item_pos(item)))
            except Exception:
                return False

        try:
            width, height = map(float, dpg.get_item_rect_size(item))
        except Exception:
            return False
        if width <= 0.0 or height <= 0.0:
            return False

        x, y = rect_min
        return x <= mx <= x + width and y <= my <= y + height
    except Exception:
        return False


def _protected_surface_under_pointer():
    mouse = _mouse_position()
    if mouse is None:
        return None

    stale = []
    hit = None
    for item in tuple(_protected_items):
        try:
            if not dpg.does_item_exist(item):
                stale.append(item)
                continue
            if _item_contains_mouse(item, mouse):
                hit = item
                break
        except Exception:
            stale.append(item)

    for item in stale:
        _protected_items.discard(item)
    return hit


def pointer_input_is_blocked(owner=None):
    """Return True when another foreground interaction owns pointer input.

    Unlike the old implementation, this is not conditional on
    ``is_mouse_button_down``. Dear PyGui's global click handler may run after the
    button has already transitioned to *up*.  Hit-testing the foreground
    surface unconditionally therefore prevents both press- and release-phase
    click-through.

    ``owner`` is optional. When the same object currently owns an explicit
    capture created by :func:`acquire_pointer_input`, this function returns
    ``False`` for that owner and ``True`` for everyone else. This mirrors Qt
    mouse-grab semantics and prevents global splitter polling from stealing a
    drag that started in a header/list/widget.

    If a press starts on a protected surface, ownership is latched until one
    frame after release. This mirrors normal GUI mouse capture: dragging a
    dialog/widget outside its original rectangle cannot suddenly activate the
    Explorer rows now under the cursor.
    """
    global _surface_press_item, _release_guard_until_frame

    if native_background_input_blocked():
        return True

    if _pointer_owner is not None:
        # Explicit gesture capture is owner-aware. The control that acquired
        # the pointer must keep receiving its own drag/release callbacks, while
        # every sibling/global handler (splitters, other list views, etc.) is
        # blocked until the owner releases the gesture.
        return _pointer_owner is not owner

    down = _mouse_button_down()
    frame = _frame_count()

    # Continue consuming a gesture that began on a foreground surface even
    # after the cursor has left that surface.
    if _surface_press_item is not None:
        if down:
            _release_guard_until_frame = -1
            return True
        if _release_guard_until_frame < 0:
            _release_guard_until_frame = frame + 1
        if frame <= _release_guard_until_frame:
            return True
        _surface_press_item = None
        _release_guard_until_frame = -1

    hit = _protected_surface_under_pointer()
    if hit is not None:
        if down:
            _surface_press_item = hit
            _release_guard_until_frame = -1
        # Also block hover and click callbacks that execute after mouse-up.
        return True

    return False


def reset_pointer_input_gate():
    global _pointer_owner, _surface_press_item, _release_guard_until_frame
    global _native_surface_press_hwnd, _native_release_guard_until_frame
    global _native_modal_release_pending, _native_modal_release_guard_until_frame
    _pointer_owner = None
    _surface_press_item = None
    _release_guard_until_frame = -1
    _native_surface_press_hwnd = None
    _native_release_guard_until_frame = -1
    _native_modal_release_pending = False
    _native_modal_release_guard_until_frame = -1
    _protected_items.clear()
    with _native_gate_lock:
        _native_pointer_hwnds.clear()
        _native_modal_tokens.clear()
