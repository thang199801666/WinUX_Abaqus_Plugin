"""Retained Qt-like state controller for :class:`DockWidget`.

The controller makes one object the owner of QDockWidget logical state while
renderer/native hosts remain responsible for presentation.  Existing host
callbacks may still perform asynchronous dock/float transitions; when they
commit, ``DockWidget.set_floating`` adopts the committed mode into this
controller rather than maintaining a second lifecycle model.
"""
from __future__ import annotations

import weakref

from ..core.object import Signal
from .window_lifecycle import QDockWindowLifecycle


class QDockWidgetStateController:
    """Own retained visibility/top-level/geometry state for one dock widget.

    ``requestFloating`` mirrors QDockWidget::setFloating semantics: a request is
    emitted to the host transition adapter first.  The committed renderer path
    calls :meth:`adoptFloating`, which updates the shared lifecycle and emits
    the canonical top-level state exactly once.
    """

    def __init__(self, mode="docked", visible=True, geometry=None,
                 request_floating=None, dock_area=None):
        self.floatingRequested = Signal()
        self.topLevelChanged = Signal()
        self.visibilityChanged = Signal()
        self.geometryChanged = Signal()
        self.dockAreaChanged = Signal()
        self.mainWindowChanged = Signal()
        self.tabGroupChanged = Signal()
        self.activeTabChanged = Signal()
        self.splitTopologyChanged = Signal()
        self.topologyChanged = Signal()
        self.stateChanged = Signal()
        self._lifecycle = QDockWindowLifecycle(mode, visible, geometry)
        self._request_floating = request_floating
        self._request_in_progress = False
        self._requested_floating = None
        self._dock_area = self._normalize_area(dock_area)
        self._main_window_ref = None
        self._tab_group_id = None
        self._tabified_keys = ()
        self._active_tab_key = None
        self._split_orientation = None
        self._split_path = None

        self._lifecycle.topLevelChanged.connect(self.topLevelChanged.emit)
        self._lifecycle.visibilityChanged.connect(self.visibilityChanged.emit)
        self._lifecycle.geometryChanged.connect(self.geometryChanged.emit)
        self._lifecycle.stateChanged.connect(self.stateChanged.emit)


    @staticmethod
    def _normalize_area(area):
        if area is None:
            return None
        value = str(area).strip().lower()
        return value if value in ("left", "right", "top", "bottom") else None

    def dockArea(self):
        return self._dock_area

    def setDockArea(self, area):
        area = self._normalize_area(area)
        if area is None or area == self._dock_area:
            return False
        self._dock_area = area
        self.dockAreaChanged.emit(area)
        self.stateChanged.emit(self.snapshot())
        return True

    def mainWindow(self):
        ref = self._main_window_ref
        if ref is None:
            return None
        try:
            return ref()
        except TypeError:
            return ref

    def isManaged(self):
        return self.mainWindow() is not None

    def attachToMainWindow(self, main_window, area=None):
        if main_window is None:
            return self.detachFromMainWindow()
        previous = self.mainWindow()
        owner_changed = previous is not main_window
        if owner_changed:
            try:
                self._main_window_ref = weakref.ref(main_window)
            except TypeError:
                self._main_window_ref = main_window
        area_changed = self.setDockArea(area) if area is not None else False
        if owner_changed:
            self.mainWindowChanged.emit(main_window)
            self.stateChanged.emit(self.snapshot())
        return bool(owner_changed or area_changed)

    def detachFromMainWindow(self, main_window=None):
        previous = self.mainWindow()
        if previous is None:
            return False
        if main_window is not None and previous is not main_window:
            return False
        self._main_window_ref = None
        self.mainWindowChanged.emit(None)
        self.stateChanged.emit(self.snapshot())
        return True

    def tabGroupId(self):
        return self._tab_group_id

    def tabifiedKeys(self):
        return tuple(self._tabified_keys)

    def activeTabKey(self):
        return self._active_tab_key

    def isActiveTab(self):
        return self._active_tab_key is not None and self._active_tab_key not in self._tabified_keys

    def splitOrientation(self):
        return self._split_orientation

    def splitPath(self):
        return self._split_path

    def adoptTopology(self, topology=None):
        """Mirror canonical DockManager topology into retained dock state."""
        topology = dict(topology or {})
        group_id = topology.get("tabGroupId")
        tabified = tuple(str(key) for key in (topology.get("tabifiedKeys") or ()))
        active = topology.get("activeTabKey")
        active = None if active is None else str(active)
        orientation = topology.get("splitOrientation")
        orientation = None if orientation is None else str(orientation)
        path = topology.get("splitPath")
        path = None if path is None else tuple(int(index) for index in path)
        area = topology.get("area")

        old_group = (self._tab_group_id, self._tabified_keys)
        old_active = self._active_tab_key
        old_split = (self._split_orientation, self._split_path)
        area_changed = self.setDockArea(area) if area is not None else False

        self._tab_group_id = group_id
        self._tabified_keys = tabified
        self._active_tab_key = active
        self._split_orientation = orientation
        self._split_path = path

        changed = bool(area_changed)
        if old_group != (group_id, tabified):
            self.tabGroupChanged.emit(group_id, tabified)
            changed = True
        if old_active != active:
            self.activeTabChanged.emit(active)
            changed = True
        if old_split != (orientation, path):
            self.splitTopologyChanged.emit(orientation, path)
            changed = True
        if changed:
            snapshot = self.topologySnapshot()
            self.topologyChanged.emit(snapshot)
            self.stateChanged.emit(self.snapshot())
        return changed

    def clearTopology(self):
        return self.adoptTopology({})

    def topologySnapshot(self):
        return {
            "dockArea": self._dock_area,
            "tabGroupId": self._tab_group_id,
            "tabifiedKeys": tuple(self._tabified_keys),
            "activeTabKey": self._active_tab_key,
            "splitOrientation": self._split_orientation,
            "splitPath": self._split_path,
        }

    def lifecycle(self):
        return self._lifecycle

    def setRequestFloatingHandler(self, handler):
        self._request_floating = handler

    def requestedFloating(self):
        return self._requested_floating

    def requestInProgress(self):
        return bool(self._request_in_progress)

    def isFloating(self):
        return self._lifecycle.isFloating()

    def isVisible(self):
        return self._lifecycle.isVisible()

    def geometry(self):
        return self._lifecycle.geometry()

    def setVisible(self, visible):
        return self._lifecycle.setVisible(visible)

    def setGeometry(self, geometry):
        return self._lifecycle.setGeometry(geometry)

    def requestFloating(self, floating, context=None):
        """Request a dock/float transition without prematurely committing it."""
        desired = bool(floating)
        if desired == self.isFloating() and not self._request_in_progress:
            return False
        if self._request_in_progress and desired == self._requested_floating:
            return False
        self._request_in_progress = True
        self._requested_floating = desired
        self.floatingRequested.emit(desired, context)
        handler = self._request_floating
        if not callable(handler):
            self.adoptFloating(desired)
            return True
        try:
            result = handler(desired)
        except Exception:
            self._request_in_progress = False
            self._requested_floating = None
            raise
        if result is False:
            self._request_in_progress = False
            self._requested_floating = None
            return False
        return True

    def adoptFloating(self, floating):
        """Adopt a transition already committed by the renderer/native host."""
        desired = bool(floating)
        changed = self._lifecycle.setMode(
            QDockWindowLifecycle.Floating if desired
            else QDockWindowLifecycle.Docked)
        if self._requested_floating == desired:
            self._request_in_progress = False
            self._requested_floating = None
        return changed

    def cancelFloatingRequest(self):
        if not self._request_in_progress:
            return False
        self._request_in_progress = False
        self._requested_floating = None
        return True

    def snapshot(self):
        result = self._lifecycle.snapshot()
        result.update({
            "requestInProgress": bool(self._request_in_progress),
            "requestedFloating": self._requested_floating,
            "dockArea": self._dock_area,
            "managed": self.isManaged(),
            "tabGroupId": self._tab_group_id,
            "tabifiedKeys": tuple(self._tabified_keys),
            "activeTabKey": self._active_tab_key,
            "splitOrientation": self._split_orientation,
            "splitPath": self._split_path,
        })
        return result
