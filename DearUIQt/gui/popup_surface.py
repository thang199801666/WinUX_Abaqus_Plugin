"""Canonical popup lifecycle state shared by DearUIQt transient widgets."""
from __future__ import annotations

from collections import deque
import itertools
import time

from ..core.object import QObject, QPointer, QRect, Signal
from .lifecycle import QLifecycleTransitionRecord
from .lifecycle_diagnostics import filter_transition_records, compact_transition_records


_POPUP_CORRELATION_SEQUENCE = itertools.count(1)


class QPopupSurface(QObject):
    """Retained popup state that keeps visual/input ownership in one object.

    A popup may not claim input ownership before its visual surface has been
    requested.  This simple invariant prevents the historical failure mode in
    which a hidden/missing menu surface still retained clickable action regions.
    """

    Hidden, Showing, Visible, Hiding = range(4)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.aboutToShow = Signal(self)
        self.shown = Signal(self)
        self.aboutToHide = Signal(self)
        self.hidden = Signal(self)
        self.damageRequested = Signal(self)
        self._correlation_id = "popup-surface-{}".format(next(_POPUP_CORRELATION_SEQUENCE))
        self._owner = QPointer()
        self._host = QPointer()
        self._geometry = QRect(0, 0, 0, 0)
        self._state = self.Hidden
        self._visual_requested = False
        self._input_owned = False
        self._host_close_connection = None
        self._generation = 0
        self._host_correlation_id = None
        self._last_teardown_correlation_id = None
        self._last_hide_reason = None
        self._transition_serial = 0
        self._transition_history = deque(maxlen=24)
        self._recordTransition("created")


    def _recordTransition(self, action, reason=None):
        self._transition_serial += 1
        self._transition_history.append(QLifecycleTransitionRecord(
            serial=int(self._transition_serial),
            time_monotonic=float(time.monotonic()),
            action=str(action),
            reason=None if reason is None else str(reason),
            state=str(int(self._state)),
            generation=int(self._generation),
            visual_requested=bool(self._visual_requested),
            input_owned=bool(self._input_owned),
            host_correlation_id=self._host_correlation_id,
            teardown_correlation_id=self._last_teardown_correlation_id,
        ))

    def transitionHistory(self, *, action=None, reason=None, limit=None):
        """Return a filtered bounded copy of recent popup lifecycle transitions."""
        def _popup_transform(record, item):
            item["state"] = int(record.state)
            return item
        return filter_transition_records(
            self._transition_history, action=action, reason=reason, limit=limit,
            transform=_popup_transform)

    def compactTransitionHistory(self):
        """Return bounded popup history suitable for compact crash reports."""
        return compact_transition_records(self._transition_history, kind="popup")

    def compactDiagnosticsSnapshot(self):
        """Return compact JSON-friendly popup state for crash/hang logging."""
        g = self._geometry
        return {
            "id": self._correlation_id,
            "hc": self._host_correlation_id,
            "tc": self._last_teardown_correlation_id,
            "hide": self._last_hide_reason,
            "s": int(self._state),
            "gen": int(self._generation),
            "v": bool(self._visual_requested),
            "i": bool(self._input_owned),
            "ok": bool(self.isConsistent()),
            "g": (g.x(), g.y(), g.width(), g.height()),
            "h": list(self.compactTransitionHistory()),
        }

    def correlationId(self):
        return self._correlation_id

    def owner(self):
        return self._owner.data()

    def host(self):
        return self._host.data()

    def geometry(self):
        g = self._geometry
        return QRect(g.x(), g.y(), g.width(), g.height())

    def setGeometry(self, rect):
        if isinstance(rect, QRect):
            self._geometry = QRect(rect.x(), rect.y(), rect.width(), rect.height())
        else:
            x, y, w, h = rect
            self._geometry = QRect(int(x), int(y), max(0, int(w)), max(0, int(h)))

    def state(self):
        return self._state

    def isVisible(self):
        return self._state in (self.Showing, self.Visible)

    def visualRequested(self):
        return self._visual_requested

    def ownsInput(self):
        return self._input_owned


    def generation(self):
        return self._generation

    def invalidate(self, region=None):
        """Request repaint through the owning QWindowHost.

        Popup widgets only report retained damage here; they never activate,
        show/hide or otherwise mutate the native window as a side effect.
        This keeps hover repaint independent from Win32 foreground/chrome state.
        """
        if self._state == self.Hidden and not self._visual_requested:
            return False
        if region is None:
            region = self.geometry()
        elif not isinstance(region, QRect):
            try:
                x, y, w, h = region
                region = QRect(int(x), int(y), max(0, int(w)), max(0, int(h)))
            except Exception:
                return False
        host = self.host()
        requested = False
        if host is not None and hasattr(host, "requestUpdate"):
            try:
                requested = bool(host.requestUpdate(region))
            except Exception:
                requested = False
        self.damageRequested.emit(QRect(region.x(), region.y(), region.width(), region.height()))
        return requested or host is None

    def diagnosticsSnapshot(self):
        """Return immutable-friendly state for runtime diagnostics/tests."""
        g = self._geometry
        owner = self.owner()
        host = self.host()
        return {
            "correlation_id": self._correlation_id,
            "host_correlation_id": self._host_correlation_id,
            "last_teardown_correlation_id": self._last_teardown_correlation_id,
            "last_hide_reason": self._last_hide_reason,
            "state": int(self._state),
            "generation": int(self._generation),
            "visual_requested": bool(self._visual_requested),
            "input_owned": bool(self._input_owned),
            "consistent": bool(self.isConsistent()),
            "geometry": (g.x(), g.y(), g.width(), g.height()),
            "owner_alive": owner is not None,
            "host_alive": host is not None,
            "host_native_handle": int(getattr(host, "nativeHandle", lambda: 0)() or 0) if host is not None else 0,
            "transition_history": list(self.transitionHistory()),
        }

    def _disconnect_host(self):
        connection = self._host_close_connection
        self._host_close_connection = None
        if connection is not None:
            try:
                connection.disconnect()
            except Exception:
                pass

    def _host_about_to_close(self, *args):
        host = self.host()
        if host is not None:
            getter = getattr(host, "teardownCorrelationId", None)
            if callable(getter):
                self._last_teardown_correlation_id = getter()
        if self._state != self.Hidden:
            self.beginHide(reason="host_closing")
            self.markHidden()

    def beginShow(self, *, owner=None, host=None, geometry=None):
        if self._state in (self.Showing, self.Visible):
            if geometry is not None:
                self.setGeometry(geometry)
            return False
        self._disconnect_host()
        self._owner = QPointer(owner) if isinstance(owner, QObject) else QPointer()
        self._host = QPointer(host) if isinstance(host, QObject) else QPointer()
        getter = getattr(host, "correlationId", None) if host is not None else None
        self._host_correlation_id = getter() if callable(getter) else None
        self._last_teardown_correlation_id = None
        self._last_hide_reason = None
        if isinstance(host, QObject):
            signal = getattr(host, "aboutToClose", None)
            if signal is not None and hasattr(signal, "connect"):
                try:
                    self._host_close_connection = signal.connect(
                        self._host_about_to_close, receiver=self)
                except Exception:
                    self._host_close_connection = None
        if geometry is not None:
            self.setGeometry(geometry)
        self._generation += 1
        self._visual_requested = True
        self._input_owned = False
        self._state = self.Showing
        self._recordTransition("begin_show")
        self.aboutToShow.emit()
        self.invalidate()
        return True

    def markVisible(self):
        if not self._visual_requested:
            return False
        self._state = self.Visible
        self._recordTransition("visible")
        self.shown.emit()
        return True

    def acquireInput(self):
        # Never allow an input-only popup surface.
        if not self._visual_requested or self._state not in (self.Showing, self.Visible):
            return False
        self._input_owned = True
        self._recordTransition("acquire_input")
        return True

    def releaseInput(self):
        changed = self._input_owned
        self._input_owned = False
        if changed:
            self._recordTransition("release_input")
        return changed

    def beginHide(self, reason="requested"):
        if self._state == self.Hidden:
            return False
        self._last_hide_reason = str(reason or "requested")
        self._state = self.Hiding
        self._recordTransition("begin_hide", self._last_hide_reason)
        self.aboutToHide.emit()
        # Repaint the old popup footprint while the host relationship is still
        # valid so the exposed owner content is restored without a full frame.
        self.invalidate()
        self._input_owned = False
        return True

    def markHidden(self):
        was_hidden = self._state == self.Hidden
        self._state = self.Hidden
        self._visual_requested = False
        self._input_owned = False
        self._owner = QPointer()
        self._host = QPointer()
        self._disconnect_host()
        if not was_hidden:
            self._recordTransition("hidden", self._last_hide_reason)
            self.hidden.emit()
        return not was_hidden

    def isConsistent(self):
        if self._input_owned and not self._visual_requested:
            return False
        if self._state == self.Hidden and (self._visual_requested or self._input_owned):
            return False
        return True


__all__ = ["QPopupSurface"]
