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

from .backends import dpg


_pointer_owner = None
_popup_input_owners = []
_popup_release_guard_until_frame = -1
_protected_items = set()
# Optional z-order-aware hit tests for native modeless surfaces.
_protected_hit_tests = {}
_surface_press_item = None
_surface_press_started_down = False
_release_guard_until_frame = -1
_native_gate_lock = threading.RLock()
_native_pointer_hwnds = set()
_native_modal_tokens = set()
_native_modal_release_pending = False
_native_modal_release_started_down = False
_native_modal_release_guard_until_frame = -1
_native_surface_press_hwnd = None
_native_surface_press_started_down = False
_native_release_guard_until_frame = -1




def register_native_pointer_surface(hwnd):
    """Register a real top-level HWND as a foreground pointer surface.

    Native Tk/Qt-like dialogs live outside Dear PyGui's item tree, therefore
    DPG's global handler registries cannot know that the pointer is currently
    over them. Tracking the HWND lets a host suppress background DPG input in
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
    global _native_modal_release_pending, _native_modal_release_started_down
    global _native_modal_release_guard_until_frame
    if owner is None:
        return False
    with _native_gate_lock:
        _native_modal_tokens.add(owner)
        _native_modal_release_pending = False
        _native_modal_release_started_down = False
        _native_modal_release_guard_until_frame = -1
    return True


def release_native_modal_input(owner):
    global _native_modal_release_pending, _native_modal_release_started_down
    global _native_modal_release_guard_until_frame
    if owner is None:
        return False
    started_down = bool(_mouse_button_down())
    with _native_gate_lock:
        existed = owner in _native_modal_tokens
        _native_modal_tokens.discard(owner)
        if existed and not _native_modal_tokens:
            # Consume only the gesture that closed the modal. If the pointer is
            # already up here, any later down-state is a fresh Qt-style press
            # and must not be swallowed by the old close guard.
            _native_modal_release_pending = True
            _native_modal_release_started_down = started_down
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
    """Return the registered top-level actually hit by the desktop cursor.

    A modeless tool can stay visible *behind* the main viewport. Its rectangle
    still contains the cursor, but it must not block clicks on the main window
    covering it. Use Windows hit-testing/Z-order, not rectangle overlap alone.
    """
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
        user32.WindowFromPoint.argtypes = [wintypes.POINT]
        user32.WindowFromPoint.restype = wintypes.HWND
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        hit = int(user32.WindowFromPoint(wintypes.POINT(int(px), int(py))) or 0)
        # Controls may have their own child HWND. GA_ROOT stops at the actual
        # top-level, unlike GA_ROOTOWNER which would collapse an owned dialog
        # into its main window and defeat background-input protection.
        hit_root = int(user32.GetAncestor(hit, 2) or hit) if hit else 0
        for hwnd in hwnds:
            native = wintypes.HWND(int(hwnd))
            if not user32.IsWindow(native):
                stale.append(hwnd)
                continue
            if not user32.IsWindowVisible(native):
                continue
            if int(hwnd) == hit_root:
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
    """Return True while a native top-level owns the current pointer gesture.

    Qt releases a mouse grab at the end of the gesture that owned it. A fresh
    press after dialog close is never treated as a continuation of the old
    release. The state machine below deliberately preserves that distinction.
    """
    global _native_surface_press_hwnd, _native_surface_press_started_down
    global _native_release_guard_until_frame
    global _native_modal_release_pending, _native_modal_release_started_down
    global _native_modal_release_guard_until_frame

    if native_modal_input_active():
        return True

    down = _mouse_button_down()
    frame = _frame_count()
    with _native_gate_lock:
        release_pending = bool(_native_modal_release_pending)
        release_started_down = bool(_native_modal_release_started_down)
        release_until = int(_native_modal_release_guard_until_frame)

    if release_pending:
        if down:
            if not release_started_down:
                # The closing gesture was already observed in its up state;
                # this is an independent next click and must pass immediately.
                with _native_gate_lock:
                    _native_modal_release_pending = False
                    _native_modal_release_started_down = False
                    _native_modal_release_guard_until_frame = -1
            else:
                return True
        else:
            if release_started_down:
                with _native_gate_lock:
                    _native_modal_release_started_down = False
            if release_until < 0:
                release_until = frame + 1
                with _native_gate_lock:
                    _native_modal_release_guard_until_frame = release_until
            if frame <= release_until:
                return True
            with _native_gate_lock:
                _native_modal_release_pending = False
                _native_modal_release_started_down = False
                _native_modal_release_guard_until_frame = -1

    if _native_surface_press_hwnd is not None:
        if down:
            if not _native_surface_press_started_down:
                _native_surface_press_hwnd = None
                _native_release_guard_until_frame = -1
            else:
                _native_release_guard_until_frame = -1
                return True
        else:
            _native_surface_press_started_down = False
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
            _native_surface_press_started_down = True
            _native_release_guard_until_frame = -1
        return True
    return False


def register_pointer_protected_item(item, *, hit_test=None):
    """Register a foreground surface that must consume pointer interaction.

    The registered item may be a complete window/child-window or a smaller
    interaction surface.  Descendant controls are covered by the parent's
    screen rectangle, so one registration is normally sufficient for a whole
    dialog/widget.
    """
    if hit_test is not None and not callable(hit_test):
        raise TypeError("hit_test must be callable")
    if item is not None:
        _protected_items.add(item)
        if hit_test is not None:
            _protected_hit_tests[item] = hit_test
        else:
            _protected_hit_tests.pop(item, None)
    return item


def unregister_pointer_protected_item(item):
    if item is not None:
        _protected_items.discard(item)
        _protected_hit_tests.pop(item, None)
        # Deliberately do not clear _surface_press_item here. A popup may hide
        # or delete itself from its click callback before global background
        # handlers receive the same mouse-up. The gesture must stay captured
        # through release even after the originating surface is gone.


def guard_pointer_surface_release(item):
    """Consume the closing surface's gesture, never the next independent click."""
    global _surface_press_item, _surface_press_started_down, _release_guard_until_frame
    if _item_contains_mouse(item):
        _surface_press_item = item
        _surface_press_started_down = bool(_mouse_button_down())
        _release_guard_until_frame = -1


def acquire_popup_input(owner):
    """Give a Qt-style popup exclusive application pointer ownership.

    Unlike an ordinary mouse grab, popup ownership is stack-aware: nested menus
    share the same foreground contract while every background/global handler is
    suppressed.  QMenu uses this from ``popup()`` until the root menu hides.
    """
    global _popup_release_guard_until_frame
    if owner is None:
        return False
    if owner not in _popup_input_owners:
        _popup_input_owners.append(owner)
    _popup_release_guard_until_frame = -1
    return True


def release_popup_input(owner, *, consume_gesture=False):
    """Release popup ownership and optionally consume the current callback frame.

    Dear PyGui global click handlers are all dispatched from the same mouse
    event.  A popup can therefore hide itself before a background handler runs.
    Qt does not let that closing click fall through to the widget underneath, so
    the final popup release can latch the *current frame* without swallowing the
    next independent press.
    """
    global _popup_release_guard_until_frame
    if owner is None:
        return False
    removed = False
    while owner in _popup_input_owners:
        _popup_input_owners.remove(owner)
        removed = True
    if removed and not _popup_input_owners and consume_gesture:
        _popup_release_guard_until_frame = _frame_count()
    return removed


def popup_input_active():
    return bool(_popup_input_owners)


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
    # Mouse-up can go to another process's dialog while GLFW still remembers
    # the press that opened it. On Windows the physical state is authoritative:
    # OR-ing it with stale DPG state can keep the close-release gate forever.
    if os.name == "nt":
        try:
            user32 = ctypes.windll.user32
            user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
            user32.GetAsyncKeyState.restype = ctypes.c_short
            return any(int(user32.GetAsyncKeyState(vk)) & 0x8000
                       for vk in (0x01, 0x02, 0x04))
        except Exception:
            pass
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


def _protected_surface_under_pointer(exclude_items=None):
    """Return the registered foreground surface currently under the pointer.

    ``exclude_items`` lets a composite control ask whether it is occluded by
    *another* foreground surface without treating its own registered hit boxes
    as blockers.  This is intentionally a non-capturing hit test; the regular
    :func:`pointer_input_is_blocked` state machine remains responsible for
    press/release ownership.
    """
    excluded = set(exclude_items or ())
    mouse = _mouse_position()
    if mouse is None:
        return None

    stale = []
    hit = None
    for item in tuple(_protected_items):
        if item in excluded:
            continue
        try:
            if not dpg.does_item_exist(item):
                stale.append(item)
                continue
            native_hit_test = _protected_hit_tests.get(item)
            if native_hit_test is not None:
                # Native modeless dialogs can sit *behind* WinUx: their screen
                # rectangle may overlap an Explorer pane even though Win32
                # WindowFromPoint hits the main viewport. A simple rectangle
                # must never block Explorer selection in that case.
                # DPG mouse positions can be viewport-relative for detached
                # multi-viewport windows. Win32 hit testing needs actual
                # desktop coordinates, including negative monitor origins.
                screen_point = _native_cursor_position() or mouse
                if native_hit_test(screen_point):
                    hit = item
                    break
            elif _item_contains_mouse(item, mouse):
                hit = item
                break
        except Exception:
            stale.append(item)

    for item in stale:
        _protected_items.discard(item)
        _protected_hit_tests.pop(item, None)
    return hit


def protected_surface_under_pointer(*, exclude_items=None):
    """Return a foreground protected surface at the cursor, if any.

    This query does not acquire or release pointer ownership.  It is intended
    for visual-state arbitration (hover/pressed chrome) in composite widgets
    such as ``QScroller`` where the widget's own hit boxes are themselves
    registered foreground surfaces.
    """
    return _protected_surface_under_pointer(exclude_items=exclude_items)


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
    global _surface_press_item, _surface_press_started_down, _release_guard_until_frame
    global _popup_release_guard_until_frame

    if native_background_input_blocked():
        return True

    # QMenu/QPopup semantics: while a popup is visible it owns application
    # pointer routing, not merely the pixels covered by its rectangle.  This is
    # what prevents a click inside (or the outside click that dismisses it) from
    # also activating controls underneath through Dear PyGui global handlers.
    if _popup_input_owners:
        return owner not in _popup_input_owners
    if _popup_release_guard_until_frame >= 0:
        if _frame_count() <= _popup_release_guard_until_frame:
            return True
        _popup_release_guard_until_frame = -1

    if _pointer_owner is not None:
        return _pointer_owner is not owner

    down = _mouse_button_down()
    frame = _frame_count()

    if _surface_press_item is not None:
        if down:
            if not _surface_press_started_down:
                _surface_press_item = None
                _release_guard_until_frame = -1
            else:
                _release_guard_until_frame = -1
                return True
        else:
            _surface_press_started_down = False
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
            _surface_press_started_down = True
            _release_guard_until_frame = -1
        return True

    return False


def reset_pointer_input_gate():
    global _pointer_owner, _popup_release_guard_until_frame
    global _surface_press_item, _surface_press_started_down
    global _release_guard_until_frame
    global _native_surface_press_hwnd, _native_surface_press_started_down
    global _native_release_guard_until_frame
    global _native_modal_release_pending, _native_modal_release_started_down
    global _native_modal_release_guard_until_frame
    _pointer_owner = None
    _popup_input_owners.clear()
    _popup_release_guard_until_frame = -1
    _surface_press_item = None
    _surface_press_started_down = False
    _release_guard_until_frame = -1
    _native_surface_press_hwnd = None
    _native_surface_press_started_down = False
    _native_release_guard_until_frame = -1
    _native_modal_release_pending = False
    _native_modal_release_started_down = False
    _native_modal_release_guard_until_frame = -1
    _protected_items.clear()
    _protected_hit_tests.clear()
    with _native_gate_lock:
        _native_pointer_hwnds.clear()
        _native_modal_tokens.clear()
