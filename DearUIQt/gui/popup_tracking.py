"""Weak, frame-driven popup anchors; movement never reopens a popup."""
from __future__ import annotations

import weakref

_tracked = {}


def _backend_key(backend):
    from ..backends import _BackendProxy, get_backend
    return id(get_backend() if isinstance(backend, _BackendProxy) else backend)


def track_popup(menu):
    _tracked.setdefault(_backend_key(menu.backend), weakref.WeakSet()).add(menu)


def untrack_popup(menu):
    menus = _tracked.get(_backend_key(menu.backend))
    if menus is not None:
        menus.discard(menu)


def update_popup_positions(backend):
    menus = _tracked.get(_backend_key(backend))
    if not menus:
        return
    def depth(menu):
        result = 0
        while getattr(menu, '_parent_menu', None) is not None:
            result += 1
            menu = menu._parent_menu
        return result
    # A submenu reads its parent's new native position in the same pass.
    for menu in sorted(tuple(menus), key=depth):
        if menu not in menus:
            continue
        if not menu.exists():
            menus.discard(menu)
            continue
        try:
            # Visibility can be transient during native maximize/restore.
            # Explicit hide/delete unregisters the popup; do not turn an
            # intermediate renderer state into an extra Hide/Show cycle here.
            menu._refresh_popup_position()
        except Exception:
            # A disappearing native anchor is a recoverable popup lifecycle
            # event, not a reason to abort the application's renderer loop.
            menu.hide()
            menus.discard(menu)


def clear_popup_tracking(backend):
    _tracked.pop(_backend_key(backend), None)
