"""Native focus queries and deferred owner-focus policy, independent of IPC."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from .native_dialog_host import ensure_owner_visible, restore_owner_foreground


def foreground_hwnd():
    if os.name != "nt":
        return 0
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    return int(user32.GetForegroundWindow() or 0)


def window_state(hwnd):
    if os.name != "nt" or not hwnd:
        return False, False, False
    user32 = ctypes.windll.user32
    for name in ("IsWindow", "IsWindowVisible", "IsWindowEnabled"):
        function = getattr(user32, name)
        function.argtypes = [wintypes.HWND]
        function.restype = wintypes.BOOL
    return (bool(user32.IsWindow(hwnd)), bool(user32.IsWindowVisible(hwnd)),
            bool(user32.IsWindowEnabled(hwnd)))


def owner_has_keyboard_focus(hwnd):
    if os.name != "nt" or not hwnd:
        return False
    class GuiThreadInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                    ("active", wintypes.HWND), ("focus", wintypes.HWND),
                    ("capture", wintypes.HWND), ("menu_owner", wintypes.HWND),
                    ("move_size", wintypes.HWND), ("caret", wintypes.HWND),
                    ("caret_rect", wintypes.RECT)]
    user32 = ctypes.windll.user32
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GuiThreadInfo)]
    user32.GetGUIThreadInfo.restype = wintypes.BOOL
    info = GuiThreadInfo()
    info.cbSize = ctypes.sizeof(info)
    if not user32.GetGUIThreadInfo(user32.GetWindowThreadProcessId(hwnd, None), ctypes.byref(info)):
        return False
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    return bool(info.focus and int(user32.GetAncestor(info.focus, 2) or info.focus) == hwnd)


def queue_owner_focus(dialog, force=False, foreground=foreground_hwnd, state=window_state,
                      restore=restore_owner_foreground, keyboard=owner_has_keyboard_focus):
    """Return focus to the captured owner after the closing HWND disappears.

    The owner visibility observed when the dialog was shown is part of the
    lifecycle contract.  Windows/GLFW can occasionally hide an owned viewport
    while the last owned top-level is being destroyed; repairing that *lost*
    visibility is safe only when the owner was visible before the dialog and
    the close still belongs to WinUx.  An unrelated foreground application is
    never displaced.
    """
    if (not dialog._hwnd or not dialog._owner_hwnd
            or getattr(dialog.view, "_floating_focus_suppressed", False)):
        return
    closing_hwnds = [dialog._hwnd]

    def collect_children(parent):
        for child in getattr(parent, "_owned_dialogs", ()):
            if not child._closed and child._hwnd:
                closing_hwnds.append(child._hwnd)
                collect_children(child)

    collect_children(dialog)
    current = foreground()
    if not force and current and current not in closing_hwnds:
        return

    # Capture this before any asynchronous retry.  It distinguishes an owner
    # that Windows unexpectedly hid during dialog teardown from one the app had
    # deliberately hidden before the dialog existed.
    owner_was_visible = bool(getattr(dialog, "_owner_was_visible", False))
    explicit_return = bool(getattr(dialog, "_explicit_owner_return", False))

    dialog._focus_return_generation = getattr(dialog, "_focus_return_generation", 0) + 1
    generation = dialog._focus_return_generation

    def attempt_focus(attempt=0):
        if (generation != dialog._focus_return_generation
                or getattr(dialog.view, "_floating_focus_suppressed", False)
                or not getattr(dialog.view, "winfo_exists", lambda: True)()):
            return
        parent = getattr(dialog, "_logical_parent", None)
        if parent is not None and parent._closed:
            return

        registry = tuple(getattr(dialog.view, "_floating_dialogs", ()))
        siblings = tuple(
            other for other in registry
            if (other is not dialog and not other._closed and other._visible
                and other._owner_hwnd == dialog._owner_hwnd)
        )
        if any(other is not dialog and not other._closed and other.modal
               and other._visible and other._owner_hwnd == dialog._owner_hwnd
               for other in registry):
            return
        # A newly requested sibling may not have received its HWND yet.  Do not
        # let a delayed close callback activate WinUx between two dialogs.
        if any(not getattr(other, "_hwnd", None) for other in siblings):
            return

        current = foreground()
        if any(other is not dialog and not other._closed and other._visible
               and other._hwnd == current and current != dialog._owner_hwnd
               for other in registry):
            return

        closing_visible = any(
            live and visible for live, visible, _ in map(state, closing_hwnds))
        if closing_visible:
            # While a child HWND is still disappearing, never reveal/activate
            # the owner.  That would recreate the one-frame main-window flash.
            if current not in (*closing_hwnds, dialog._owner_hwnd, 0):
                return
            if attempt < 100:
                dialog.view.after(25, attempt_focus, attempt + 1)
            return

        # At this point every closing HWND is gone/hidden. Repair *visibility*
        # before considering foreground ownership. This operation uses
        # SW_SHOWNOACTIVATE, so an Alt-Tab to another application keeps its
        # focus while WinUx simply returns to the visible state it had before
        # the dialog opened.
        owner_state = state(dialog._owner_hwnd)
        if not owner_state[0]:
            return
        if not owner_state[1] and (owner_was_visible or explicit_return):
            ensure_owner_visible(dialog._owner_hwnd)
            owner_state = state(dialog._owner_hwnd)

        # Focus is stronger than visibility. Respect an unrelated application
        # that became foreground during teardown unless this is an explicit
        # workflow completion such as successful Login.
        current = foreground()
        if (current not in (0, dialog._owner_hwnd, *closing_hwnds)
                and not (explicit_return or force)):
            return
        if not all(owner_state):
            # The owner may still be disabled for a few milliseconds while the
            # modal reference count is unwinding. Retry without changing Z-order.
            if attempt < 100 and owner_state[0]:
                dialog.view.after(25, attempt_focus, attempt + 1)
            return

        # If Windows already handed the foreground slot back to the owner as
        # part of the native owned-window close, do not raise/activate it a
        # second time.  A redundant BringWindowToTop/SetForegroundWindow here
        # is visible as a one-frame desktop flash even though the final Z-order
        # is correct.  The deferred restore is now strictly a recovery path.
        if current == dialog._owner_hwnd:
            return

        restore(dialog._owner_hwnd)
        current = foreground()
        if current == dialog._owner_hwnd or (not current and keyboard(dialog._owner_hwnd)):
            return
        if attempt < 100:
            dialog.view.after(25, attempt_focus, attempt + 1)

    dialog.view.after(0, attempt_focus)
