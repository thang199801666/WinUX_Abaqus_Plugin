"""Live logical-DPI resolution and per-backend change dispatch for DearUIQt.

The public widget layer stays backend-neutral.  A renderer can expose
``get_logical_dpi``/``logical_dpi`` directly; on Windows the production Dear
PyGui backend falls back to the native top-level HWND so per-monitor DPI works
without adding a renderer-specific dependency to every widget.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from contextvars import ContextVar
import os
import weakref


_dispatch_dpi = ContextVar("dearuiqt_dispatch_dpi", default=None)


def _coerce_dpi(value):
    if isinstance(value, (tuple, list)):
        value = value[0] if value else 0
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return value if value > 0 else 0.0


def _backend_reported_dpi(backend):
    if backend is None:
        return 0.0
    for name in ("get_logical_dpi", "logical_dpi"):
        getter = getattr(backend, name, None)
        if not callable(getter):
            continue
        try:
            value = _coerce_dpi(getter())
        except Exception:
            value = 0.0
        if value:
            return value
    return 0.0


def _windows_window_dpi(backend, item=None):
    """Return GetDpiForWindow for a DearUIQt top-level when available."""
    if os.name != "nt" or backend is None:
        return 0.0
    try:
        import ctypes
        from ctypes import wintypes
        from ..backends.native_windows import NativeWindowBackend

        native = NativeWindowBackend(backend)
        hwnd = 0
        if item is not None:
            tag = getattr(item, "tag", item)
            try:
                if native.isPrimaryItem(tag):
                    hwnd = int(native.primaryWinId() or 0)
                elif native.available() and native.isEnabled():
                    hwnd = int(native.winId(tag) or 0)
            except Exception:
                hwnd = 0
        if not hwnd:
            hwnd = int(native.primaryWinId() or 0)
        if not hwnd:
            return 0.0
        user32 = ctypes.windll.user32
        getter = getattr(user32, "GetDpiForWindow", None)
        if getter is None:
            return 0.0
        getter.argtypes = [wintypes.HWND]
        getter.restype = wintypes.UINT
        value = int(getter(wintypes.HWND(hwnd)) or 0)
        return float(value) if value > 0 else 0.0
    except Exception:
        return 0.0


def logical_dpi_for_backend(backend=None, *, item=None, default=96.0):
    """Resolve current logical DPI without importing platform code at call sites.

    Backend-provided DPI remains authoritative for fake/future renderers.  The
    Win32 HWND fallback makes stock Dear PyGui useful in production, where no
    logical-DPI getter is currently exposed by the Python renderer API. During
    one live-DPI dispatch, nested theme/geometry queries reuse the already
    resolved DPI instead of polling the window system once per control.
    """
    override = _dispatch_dpi.get()
    if override is not None and override[0] == id(backend):
        return float(override[1])
    value = _backend_reported_dpi(backend)
    if not value:
        value = _windows_window_dpi(backend, item=item)
    if not value:
        value = _coerce_dpi(default) or 96.0
    return max(24.0, min(768.0, float(value)))


def dpi_scale_for_backend(backend=None, *, item=None, base_dpi=96.0):
    try:
        base = float(base_dpi)
    except (TypeError, ValueError, OverflowError):
        base = 96.0
    if base <= 0:
        base = 96.0
    return logical_dpi_for_backend(backend, item=item) / base


def _walk_owned(root):
    """Yield a QObject ownership tree once without importing QObject here."""
    stack = [root]
    seen = set()
    while stack:
        current = stack.pop()
        key = id(current)
        if key in seen:
            continue
        seen.add(key)
        yield current
        stack.extend(reversed(tuple(getattr(current, "_children", ()))))


def _dpi_event(old_dpi, new_dpi):
    from ..core.object import QEvent
    return QEvent(
        QEvent.DevicePixelRatioChange,
        oldDpi=float(old_dpi),
        dpi=float(new_dpi),
        oldScale=float(old_dpi) / 96.0,
        scale=float(new_dpi) / 96.0,
    )


def _deliver_dpi_change(root, old_dpi, new_dpi, backend=None):
    """Deliver one retained DPI turn, then invalidate the root layout once."""
    changed = 0
    event_payload = dict(
        oldDpi=float(old_dpi), dpi=float(new_dpi),
        oldScale=float(old_dpi) / 96.0, scale=float(new_dpi) / 96.0,
    )
    token = _dispatch_dpi.set((id(backend), float(new_dpi))) if backend is not None else None
    try:
        for target in _walk_owned(root):
            callback = getattr(target, "_dpi_changed", None)
            if callable(callback):
                try:
                    callback(old_dpi, new_dpi)
                    changed += 1
                    continue
                except Exception:
                    pass
            sender = getattr(target, "sendEvent", None)
            if callable(sender):
                try:
                    from ..core.object import QEvent
                    sender(QEvent(QEvent.DevicePixelRatioChange, **event_payload))
                    changed += 1
                except Exception:
                    pass
    finally:
        if token is not None:
            _dispatch_dpi.reset(token)

    # Layout invalidation is intentionally root-scoped.  Calling
    # QWidget.updateGeometry() for every descendant would turn one monitor move
    # into hundreds of posted LayoutRequest events.
    layout_getter = getattr(root, "layout", None)
    layout = layout_getter() if callable(layout_getter) else getattr(root, "_layout_manager", None)
    if layout is not None:
        invalidate = getattr(layout, "invalidate", None)
        if callable(invalidate):
            try:
                invalidate()
            except Exception:
                pass
    updater = getattr(root, "updateGeometry", None)
    if callable(updater):
        try:
            updater()
        except Exception:
            pass
    else:
        try:
            root._retained_layout_dirty = True
        except Exception:
            pass
    try:
        from ..core.application import QApplication
        application = QApplication.instance()
        if application is not None:
            application.logicalDpiChanged.emit(root, float(old_dpi), float(new_dpi))
    except Exception:
        pass
    return changed


@dataclass
class _BackendDpiState:
    backend: object
    roots: weakref.WeakSet = field(default_factory=weakref.WeakSet)
    loose: weakref.WeakSet = field(default_factory=weakref.WeakSet)
    root_dpi: weakref.WeakKeyDictionary = field(default_factory=weakref.WeakKeyDictionary)
    primary_dpi: float = 0.0


_states: dict[int, _BackendDpiState] = {}


def _state_for(backend):
    key = id(backend)
    state = _states.get(key)
    if state is None or state.backend is not backend:
        state = _BackendDpiState(backend)
        _states[key] = state
    return state


def register_dpi_root(root, backend=None):
    """Register one logical top-level for live DPI notifications."""
    if root is None:
        return False
    backend = backend or getattr(root, "backend", None)
    if backend is None:
        return False
    state = _state_for(backend)
    # QWidget branches created under a legacy/native parent tag are not logical
    # top-level windows even though QObject ownership cannot see that parent.
    # Keep those as primary-viewport participants: unchanged frames then perform
    # one DPI query for the whole group instead of one query per control.
    is_window = getattr(root, "isWindow", None)
    if callable(is_window):
        try:
            if not is_window():
                state.loose.add(root)
                if not state.primary_dpi:
                    state.primary_dpi = logical_dpi_for_backend(backend)
                return True
        except Exception:
            pass
    try:
        state.roots.add(root)
        if root not in state.root_dpi:
            state.root_dpi[root] = logical_dpi_for_backend(backend, item=root)
        return True
    except TypeError:
        return False


def register_dpi_participant(participant, backend=None):
    """Register a non-QObject control that cannot be reached from a root tree."""
    if participant is None:
        return False
    backend = backend or getattr(participant, "backend", None)
    if backend is None:
        return False
    state = _state_for(backend)
    try:
        state.loose.add(participant)
    except TypeError:
        return False
    if not state.primary_dpi:
        state.primary_dpi = logical_dpi_for_backend(backend)
    return True


def unregister_dpi_participant(participant, backend=None):
    backend = backend or getattr(participant, "backend", None)
    if backend is None:
        return False
    state = _states.get(id(backend))
    if state is None:
        return False
    removed = False
    for collection in (state.roots, state.loose):
        try:
            if participant in collection:
                collection.discard(participant)
                removed = True
        except Exception:
            pass
    try:
        state.root_dpi.pop(participant, None)
    except Exception:
        pass
    return removed


def sync_backend_dpi(backend, *, force=False):
    """Poll one backend and dispatch only real per-monitor DPI transitions.

    The common unchanged frame performs only DPI queries and float comparisons;
    no widget tree is traversed, no theme is rebound and no layout is dirtied.
    """
    if backend is None:
        return 0
    state = _states.get(id(backend))
    if state is None:
        return 0

    changed = 0
    roots = tuple(state.roots)
    for root in roots:
        # If a widget that used to be top-level was later reparented, migrate
        # the registration lazily instead of retaining duplicate roots forever.
        window = getattr(root, "window", None)
        if callable(window):
            try:
                actual_root = window()
            except Exception:
                actual_root = root
            if actual_root is not None and actual_root is not root:
                register_dpi_root(actual_root, backend)
                state.roots.discard(root)
                state.root_dpi.pop(root, None)
                continue
        new_dpi = logical_dpi_for_backend(backend, item=root)
        old_dpi = float(state.root_dpi.get(root, new_dpi))
        state.root_dpi[root] = new_dpi
        if force or abs(new_dpi - old_dpi) >= .25:
            changed += _deliver_dpi_change(root, old_dpi, new_dpi, backend)

    # Controls such as the legacy QComboBox are not QObject-owned; they use the
    # primary viewport DPI and are touched only when that DPI actually changes.
    if state.loose:
        new_primary = logical_dpi_for_backend(backend)
        old_primary = state.primary_dpi or new_primary
        state.primary_dpi = new_primary
        if force or abs(new_primary - old_primary) >= .25:
            token = _dispatch_dpi.set((id(backend), float(new_primary)))
            try:
                for participant in tuple(state.loose):
                    callback = getattr(participant, "_dpi_changed", None)
                    if callable(callback):
                        try:
                            callback(old_primary, new_primary)
                            changed += 1
                        except Exception:
                            pass
            finally:
                _dispatch_dpi.reset(token)
    return changed


def clear_backend_dpi_state(backend=None):
    """Drop lifecycle state at renderer/context teardown."""
    if backend is None:
        count = len(_states)
        _states.clear()
        return count
    return 1 if _states.pop(id(backend), None) is not None else 0


__all__ = [
    "logical_dpi_for_backend", "dpi_scale_for_backend", "register_dpi_root",
    "register_dpi_participant", "unregister_dpi_participant",
    "sync_backend_dpi", "clear_backend_dpi_state",
]
