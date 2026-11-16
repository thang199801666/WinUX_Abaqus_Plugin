"""Qt-like lifecycle model shared by docked/floating tool windows.

The renderer/native host remains responsible for actual HWND/DPG movement. This
object owns retained dock/floating state, move transactions, semantic drop
feedback and persisted geometry so feature code does not need parallel gesture
state machines.
"""
from __future__ import annotations

from ..core.object import Signal


class QDockWindowLifecycle:
    Docked = "docked"
    Floating = "floating"
    Moving = "moving"
    Hidden = "hidden"

    def __init__(self, mode="docked", visible=True, geometry=None):
        self.stateChanged = Signal()
        self.topLevelChanged = Signal()
        self.visibilityChanged = Signal()
        self.geometryChanged = Signal()
        self.moveStarted = Signal()
        self.moveFinished = Signal()
        self.dropTargetChanged = Signal()
        self._mode = self._normalize_mode(mode)
        self._visible = bool(visible)
        self._moving = False
        self._geometry = self._normalize_geometry(geometry)
        self._drop_target = None

    @staticmethod
    def _normalize_mode(mode):
        return QDockWindowLifecycle.Floating if str(mode).lower() == "floating" else QDockWindowLifecycle.Docked

    @staticmethod
    def _normalize_geometry(geometry):
        if not geometry:
            return None
        try:
            pos = tuple(map(int, geometry.get("pos", (0, 0))))
            size = tuple(map(int, geometry.get("size", (0, 0))))
            if len(pos) != 2 or len(size) != 2 or size[0] <= 0 or size[1] <= 0:
                return None
            return {"pos": pos, "size": size}
        except Exception:
            return None

    @staticmethod
    def _normalize_drop_target(target=None, scope=None):
        if target is None:
            return None
        if isinstance(target, dict):
            area = target.get("area", target.get("target", target.get("zone")))
            scope = target.get("scope", scope)
        else:
            area = target
        if area is None:
            return None
        area = str(area).strip().lower()
        if not area:
            return None
        result = {"area": area}
        if scope is not None:
            normalized_scope = str(scope).strip().lower()
            if normalized_scope:
                result["scope"] = normalized_scope
        return result

    def mode(self):
        return self._mode

    def isFloating(self):
        return self._mode == self.Floating

    def isDocked(self):
        return self._mode == self.Docked

    def isMoving(self):
        return bool(self._moving)

    def isVisible(self):
        return bool(self._visible)

    def state(self):
        if not self._visible:
            return self.Hidden
        if self._moving:
            return self.Moving
        return self._mode

    def setMode(self, mode):
        mode = self._normalize_mode(mode)
        if mode == self._mode:
            return False
        old_state = self.state()
        old_floating = self.isFloating()
        self._mode = mode
        self._moving = False
        self.clearDropTarget()
        self.topLevelChanged.emit(self.isFloating())
        self.stateChanged.emit(old_state, self.state())
        return old_floating != self.isFloating()

    def setVisible(self, visible):
        visible = bool(visible)
        if visible == self._visible:
            return False
        old_state = self.state()
        self._visible = visible
        if not visible:
            self._moving = False
            self.clearDropTarget()
        self.visibilityChanged.emit(visible)
        self.stateChanged.emit(old_state, self.state())
        return True

    def beginMove(self, target=None, scope=None):
        if self._moving:
            if target is not None:
                self.setDropTarget(target, scope)
            return False
        old_state = self.state()
        self._moving = True
        self.setDropTarget(target, scope)
        self.moveStarted.emit(self.snapshot())
        self.stateChanged.emit(old_state, self.state())
        return True

    def dropTarget(self):
        return None if self._drop_target is None else dict(self._drop_target)

    def setDropTarget(self, target=None, scope=None):
        value = self._normalize_drop_target(target, scope)
        if value == self._drop_target:
            return False
        self._drop_target = value
        self.dropTargetChanged.emit(self.dropTarget())
        return True

    def clearDropTarget(self):
        return self.setDropTarget(None)

    def endMove(self, docked=None, target=None, scope=None, canceled=False, source=None):
        old_state = self.state()
        was_moving = self._moving
        if target is not None:
            self.setDropTarget(target, scope)
        final_target = self.dropTarget()
        self._moving = False
        top_level_changed = False
        if docked is not None:
            target_mode = self.Docked if bool(docked) else self.Floating
            if target_mode != self._mode:
                self._mode = target_mode
                top_level_changed = True
                self.topLevelChanged.emit(self.isFloating())
        self.clearDropTarget()
        if was_moving or old_state != self.state():
            self.stateChanged.emit(old_state, self.state())
        if was_moving:
            self.moveFinished.emit({
                "docked": self.isDocked(),
                "floating": self.isFloating(),
                "canceled": bool(canceled),
                "target": final_target,
                **({"source": str(source)} if source is not None else {}),
            })
        return bool(was_moving or top_level_changed or old_state != self.state())

    def cancelMove(self, docked=None, source=None):
        return self.endMove(docked=docked, canceled=True, source=source)

    def geometry(self):
        return None if self._geometry is None else dict(self._geometry)

    def setGeometry(self, geometry):
        geometry = self._normalize_geometry(geometry)
        if geometry == self._geometry:
            return False
        self._geometry = geometry
        self.geometryChanged.emit(self.geometry())
        return True

    def snapshot(self):
        return {
            "mode": self._mode,
            "visible": self._visible,
            "moving": self._moving,
            "geometry": self.geometry(),
            "dropTarget": self.dropTarget(),
        }
