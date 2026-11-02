"""Shared popup geometry; bounds and anchors always use the same coordinates."""
from __future__ import annotations


def fit_popup(position, size, bounds):
    left, top, right, bottom = bounds
    width, height = size
    x, y = position
    return (max(left, min(x, max(left, right - width))),
            max(top, min(y, max(top, bottom - height))))


def below_anchor(anchor, size, bounds):
    """Prefer below, flip above when needed, then keep the popup reachable."""
    left, top, right, bottom = anchor
    width, height = size
    y = bottom
    if y + height > bounds[3]:
        y = top - height
    return fit_popup((left, y), (width, height), bounds)


def at_point(position, size, bounds):
    x, y = position
    width, height = size
    if x + width > bounds[2]:
        x -= width
    if y + height > bounds[3]:
        y -= height
    return fit_popup((x, y), size, bounds)


def item_screen_rect(backend, item):
    """Map a rendered item's bounds through its own native client origin.

    Never calibrate against the cursor: programmatic opens and nested dialogs
    may have a cursor in a completely different window or monitor.
    """
    from ..backends.dearpygui import dpg_window_rect
    rect = dpg_window_rect(backend, item, clip=False)
    if rect is None:
        x, y = backend.get_item_rect_min(item)
        width, height = backend.get_item_rect_size(item)
        rect = (x, y, x + width, y + height)
    else:
        # Window states describe layout positions, before ancestor scrolling.
        # Draw/item rect_min already describes painted geometry, so only apply
        # this adjustment to the reconstructed window case above.
        parent = backend.get_item_parent(item)
        while parent:
            kind = backend.get_item_info(parent)['type'].split('::')[-1]
            if kind in ('mvChildWindow', 'mvWindowAppItem', 'mvWindowApp'):
                sx, sy = backend.get_x_scroll(parent), backend.get_y_scroll(parent)
                rect = (rect[0] - sx, rect[1] - sy, rect[2] - sx, rect[3] - sy)
            parent = backend.get_item_parent(parent)
    from ..backends.native_windows import NativeWindowBackend
    native = NativeWindowBackend(backend)
    if not native.isEnabled():
        return rect
    root = item
    while (parent := backend.get_item_parent(root)):
        root = parent
    root_rect = dpg_window_rect(backend, root, clip=False)
    if root_rect is None:
        return rect
    try:
        import ctypes
        from ctypes import wintypes
        tag = backend.get_alias_id(root) if isinstance(root, str) else root
        hwnd = native.winId(tag)
        if not hwnd and native.isPrimaryItem(tag):
            hwnd = native.primaryWinId()
        origin = wintypes.POINT()
        if hwnd and ctypes.windll.user32.ClientToScreen(
                wintypes.HWND(hwnd), ctypes.byref(origin)):
            dx, dy = origin.x - root_rect[0], origin.y - root_rect[1]
            return (rect[0] + dx, rect[1] + dy, rect[2] + dx, rect[3] + dy)
    except (AttributeError, OSError, RuntimeError, ValueError):
        pass
    return rect


def visible_item_screen_rect(backend, item):
    """A live popup anchor, or None when an ancestor is hidden/minimized."""
    if not backend.does_item_exist(item):
        return None
    root = item
    current = item
    while current:
        if not backend.is_item_shown(current):
            return None
        root = current
        current = backend.get_item_parent(current)
    from ..backends.native_windows import NativeWindowBackend
    native = NativeWindowBackend(backend)
    if native.isEnabled():
        try:
            import ctypes
            from ctypes import wintypes
            tag = backend.get_alias_id(root) if isinstance(root, str) else root
            hwnd = native.winId(tag)
            if not hwnd and native.isPrimaryItem(tag):
                hwnd = native.primaryWinId()
            if hwnd and (ctypes.windll.user32.IsIconic(wintypes.HWND(hwnd))
                         or not ctypes.windll.user32.IsWindowVisible(wintypes.HWND(hwnd))):
                return None
        except (AttributeError, OSError, RuntimeError, ValueError):
            pass
    return item_screen_rect(backend, item)
