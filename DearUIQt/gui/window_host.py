"""Qt-style retained host boundary for top-level/floating renderer surfaces.

The object deliberately contains no WinUx policy.  It gives DearUIQt widgets one
stable place to ask which native/renderer host owns them, map coordinates and
coalesce update requests.  Native HWND/viewport details stay behind callbacks
supplied by the platform/runtime adapter.
"""
from __future__ import annotations

from enum import Enum
from collections import deque
import itertools
import time

from ..core.object import QObject, QPointer, QPoint, QRect, Signal
from .lifecycle import QLifecycleTransitionRecord
from .lifecycle_diagnostics import filter_transition_records, compact_transition_records


_HOST_CORRELATION_SEQUENCE = itertools.count(1)


class QWindowHostState(str, Enum):
    Alive = "alive"
    Closing = "closing"
    Closed = "closed"


class QWindowHost(QObject):
    Alive = QWindowHostState.Alive
    Closing = QWindowHostState.Closing
    Closed = QWindowHostState.Closed

    """Retained description of one visual/native window host.

    ``QWindowHost`` is intentionally backend-neutral.  A runtime may attach
    mapping/update callbacks while tests and non-native hosts can use the
    retained geometry fallback.  Dirty rectangles are coalesced so hover/state
    churn produces one host update request instead of repeated full invalidates.
    """

    def __init__(self, parent=None, *, native_handle=0, viewport_id=0,
                 geometry=None, map_to_global=None, map_from_global=None,
                 request_update=None, activate=None, close=None):
        super().__init__(parent=parent)
        # Canonical runtime hosts are infrastructure roots when no QApplication
        # exists yet; lifecycle diagnostics should not report the backend cache
        # itself as a user orphan.
        self._diagnostic_infrastructure_root = True
        self.geometryChanged = Signal(self)
        self.updateRequested = Signal(self)
        self.activated = Signal(self)
        self.aboutToClose = Signal(self)
        self.closed = Signal(self)
        self.stateChanged = Signal(self)
        self._correlation_id = "window-host-{}".format(next(_HOST_CORRELATION_SEQUENCE))
        self._transition_serial = 0
        self._teardown_correlation_id = None
        self._native_handle = int(native_handle or 0)
        self._viewport_id = viewport_id
        self._geometry = self._coerce_rect(geometry)
        self._map_to_global = map_to_global
        self._map_from_global = map_from_global
        self._request_update = request_update
        self._activate = activate
        self._close = close
        self._dirty_region = None
        self._state = self.Alive
        self._teardown_reason = None
        self._last_transition_reason = "created"
        self._owner_object = QPointer()
        self._owner_destroy_connection = None
        self._transition_history = deque(maxlen=16)
        self._recordTransition(self.Alive, "created")

    @staticmethod
    def _coerce_rect(value):
        if isinstance(value, QRect):
            return QRect(value.x(), value.y(), value.width(), value.height())
        if value is None:
            return QRect(0, 0, 0, 0)
        try:
            x, y, w, h = value
            return QRect(int(x), int(y), max(0, int(w)), max(0, int(h)))
        except Exception:
            return QRect(0, 0, 0, 0)

    @staticmethod
    def _coerce_point(value):
        if isinstance(value, QPoint):
            return QPoint(value.x(), value.y())
        try:
            x, y = value
            return QPoint(int(x), int(y))
        except Exception:
            return QPoint(0, 0)



    def _recordTransition(self, state, reason=None):
        value = state.value if isinstance(state, QWindowHostState) else str(state)
        self._transition_history.append(QLifecycleTransitionRecord(
            serial=int(self._transition_serial),
            time_monotonic=float(time.monotonic()),
            action="state",
            state=value,
            reason=None if reason is None else str(reason),
            teardown_correlation_id=self._teardown_correlation_id,
        ))

    def transitionHistory(self, *, state=None, reason=None, limit=None):
        """Return a filtered bounded copy of recent lifecycle transitions."""
        state_value = state.value if isinstance(state, QWindowHostState) else state
        return filter_transition_records(
            self._transition_history, state=state_value, reason=reason, limit=limit)

    def compactTransitionHistory(self):
        """Return crash-report friendly lifecycle history with stable short keys."""
        return compact_transition_records(self._transition_history, kind="host")

    def compactDiagnosticsSnapshot(self):
        """Return a small JSON-friendly host snapshot for crash/hang logs."""
        g = self._geometry
        dirty = self._dirty_region
        return {
            "id": self._correlation_id,
            "tc": self._teardown_correlation_id,
            "state": self._state.value if isinstance(self._state, QWindowHostState) else str(self._state),
            "reason": self._teardown_reason or self._last_transition_reason,
            "hwnd": int(self._native_handle or 0),
            "vp": self._viewport_id,
            "g": (g.x(), g.y(), g.width(), g.height()),
            "dirty": None if dirty is None else (dirty.x(), dirty.y(), dirty.width(), dirty.height()),
            "h": list(self.compactTransitionHistory()),
        }

    def correlationId(self):
        """Stable process-local id used to correlate popup/host diagnostics."""
        return self._correlation_id

    def teardownCorrelationId(self):
        return self._teardown_correlation_id

    def ownerObject(self):
        """Return the QObject that owns this host lifecycle, if any."""
        return self._owner_object.data()

    def setOwnerObject(self, owner):
        """Bind host teardown to a process/application QObject lifecycle.

        The owner is retained weakly.  Destroying the application closes the
        host, but transient QGuiRuntime wrappers never become host owners.
        """
        if owner is not None and not isinstance(owner, QObject):
            raise TypeError("window host owner must be QObject or None")
        current = self.ownerObject()
        if current is owner:
            return False
        connection = self._owner_destroy_connection
        self._owner_destroy_connection = None
        if connection is not None:
            try:
                connection.disconnect()
            except Exception:
                pass
        self._owner_object.assign(owner)
        if owner is not None:
            try:
                self._owner_destroy_connection = owner.destroyed.connect(
                    lambda *_args, _self=self: _self.close(reason="owner_destroyed"))
            except Exception:
                self._owner_destroy_connection = None
        return True

    def nativeHandle(self):
        return self._native_handle

    def setNativeHandle(self, handle):
        self._native_handle = int(handle or 0)

    def viewportId(self):
        return self._viewport_id

    def setViewportId(self, viewport_id):
        self._viewport_id = viewport_id

    def geometry(self):
        return QRect(self._geometry.x(), self._geometry.y(),
                     self._geometry.width(), self._geometry.height())

    def setGeometry(self, rect):
        rect = self._coerce_rect(rect)
        old = self._geometry
        if (old.x(), old.y(), old.width(), old.height()) == (
                rect.x(), rect.y(), rect.width(), rect.height()):
            return False
        self._geometry = rect
        self.geometryChanged.emit(self.geometry())
        return True

    def mapToGlobal(self, point):
        point = self._coerce_point(point)
        if callable(self._map_to_global):
            try:
                return self._coerce_point(self._map_to_global(point))
            except Exception:
                pass
        return QPoint(self._geometry.x() + point.x(), self._geometry.y() + point.y())

    def mapFromGlobal(self, point):
        point = self._coerce_point(point)
        if callable(self._map_from_global):
            try:
                return self._coerce_point(self._map_from_global(point))
            except Exception:
                pass
        return QPoint(point.x() - self._geometry.x(), point.y() - self._geometry.y())

    @staticmethod
    def _union(a, b):
        if a is None:
            return QRect(b.x(), b.y(), b.width(), b.height())
        left = min(a.x(), b.x())
        top = min(a.y(), b.y())
        right = max(a.x() + a.width(), b.x() + b.width())
        bottom = max(a.y() + a.height(), b.y() + b.height())
        return QRect(left, top, max(0, right - left), max(0, bottom - top))

    def requestUpdate(self, region=None):
        """Coalesce a dirty region and notify the host once per accumulated set."""
        if self._state != self.Alive:
            return False
        if region is None:
            region = QRect(0, 0, self._geometry.width(), self._geometry.height())
        else:
            region = self._coerce_rect(region)
        first = self._dirty_region is None
        self._dirty_region = self._union(self._dirty_region, region)
        if first:
            if callable(self._request_update):
                try:
                    self._request_update()
                except Exception:
                    pass
            self.updateRequested.emit(self.dirtyRegion())
        return True

    def hasPendingUpdate(self):
        return self._dirty_region is not None

    def dirtyRegion(self):
        region = self._dirty_region
        if region is None:
            return None
        return QRect(region.x(), region.y(), region.width(), region.height())

    def takeDirtyRegion(self):
        region = self.dirtyRegion()
        self._dirty_region = None
        return region


    def diagnosticsSnapshot(self):
        """Small retained-state snapshot; never queries or activates native UI."""
        g = self._geometry
        dirty = self._dirty_region
        return {
            "correlation_id": self._correlation_id,
            "teardown_correlation_id": self._teardown_correlation_id,
            "transition_serial": int(self._transition_serial),
            "native_handle": int(self._native_handle or 0),
            "viewport_id": self._viewport_id,
            "geometry": (g.x(), g.y(), g.width(), g.height()),
            "dirty_region": None if dirty is None else (
                dirty.x(), dirty.y(), dirty.width(), dirty.height()),
            "state": self._state.value if isinstance(self._state, QWindowHostState) else str(self._state),
            "closing": self._state == self.Closing,
            "closed": self._state == self.Closed,
            "teardown_reason": self._teardown_reason,
            "last_transition_reason": self._last_transition_reason,
            "owner_alive": self.ownerObject() is not None,
            "owner_type": None if self.ownerObject() is None else type(self.ownerObject()).__name__,
            "transition_history": list(self.transitionHistory()),
        }

    def activate(self):
        if self._state != self.Alive:
            return False
        result = True
        if callable(self._activate):
            try:
                result = self._activate() is not False
            except Exception:
                result = False
        if result:
            self.activated.emit()
        return result

    def state(self):
        return self._state

    def isAlive(self):
        return self._state == self.Alive

    def isClosing(self):
        return self._state == self.Closing

    def isClosed(self):
        return self._state == self.Closed

    def teardownReason(self):
        return self._teardown_reason

    def _setState(self, state, reason=None):
        try:
            state = state if isinstance(state, QWindowHostState) else QWindowHostState(str(state))
        except Exception:
            raise ValueError("invalid QWindowHost state")
        if state == self._state:
            return False
        self._state = state
        self._transition_serial += 1
        if reason is not None:
            self._last_transition_reason = str(reason)
        self._recordTransition(state, reason)
        self.stateChanged.emit(state)
        return True

    def close(self, reason="requested"):
        if self._state != self.Alive:
            return False
        reason = str(reason or "requested")
        # Create the correlation before aboutToClose so child popup surfaces can
        # record exactly which host transition caused their teardown.
        self._teardown_correlation_id = "{}/close-{}".format(
            self._correlation_id, self._transition_serial + 1)
        self._setState(self.Closing, reason)
        self.aboutToClose.emit()
        result = True
        if callable(self._close):
            try:
                result = self._close() is not False
            except Exception:
                result = False
        if result:
            self._dirty_region = None
            self._teardown_reason = reason
            self._setState(self.Closed, reason)
            self.closed.emit()
        else:
            # A rejected native close returns ownership to the live host; the
            # attempted correlation remains observable for diagnostics while no
            # teardown reason is committed.
            self._setState(self.Alive, "close_rejected")
        return result


__all__ = ["QWindowHost", "QWindowHostState"]
