"""Renderer-neutral controller for Qt-like dock preview presentation.

The controller owns presentation state (visibility, active guide/scope and
prospective result rectangle) while :class:`DockDropPreview` remains the DPG
renderer.  Feature code supplies only the dock-site bounds and its desired
result rectangle.
"""
from __future__ import annotations

from .dock_widget import DockDropPreview
from .drop_target import QDockDropTargetResolver


class QDockPreviewController:
    """Own one shared dock-guide overlay and its retained presentation state."""

    def __init__(self, preview=None, preview_factory=DockDropPreview):
        self._preview = preview
        self._preview_factory = preview_factory
        self._visible = False
        self._bounds = None
        self._target = None
        self._preview_rect = None
        self._lifecycle_bindings = {}

    @staticmethod
    def _normalize_bounds(bounds):
        if bounds is None:
            return None
        try:
            x, y, width, height = map(float, bounds)
        except Exception:
            return None
        if width <= 0.0 or height <= 0.0:
            return None
        return (x, y, width, height)

    @classmethod
    def _normalize_target(cls, target=None, scope=None):
        if isinstance(target, dict):
            scope = target.get("scope", scope)
            target = target.get("area", target.get("target", target.get("zone")))
        area = QDockDropTargetResolver.normalizeArea(target)
        if area is None:
            return None
        scope = str(scope or "inner").strip().lower()
        if scope not in ("inner", "outer"):
            scope = "inner"
        return {"area": area, "scope": scope}


    def bindLifecycle(self, lifecycle, bounds_provider, preview_rect_provider=None):
        """Drive this preview directly from a QDockWindowLifecycle.

        ``bounds_provider`` returns the guide bounds. ``preview_rect_provider``
        receives the normalized semantic target dictionary and may return the
        prospective drop rectangle.  The controller owns all signal
        connections and disconnects them when rebound/destroyed.
        """
        if lifecycle is None or not callable(bounds_provider):
            raise TypeError("lifecycle and callable bounds_provider are required")
        self.unbindLifecycle(lifecycle)

        def render(target=None):
            if not lifecycle.isMoving():
                return False
            try:
                bounds = bounds_provider()
            except Exception:
                bounds = None
            target = lifecycle.dropTarget() if target is None else target
            preview_rect = None
            if target is not None and callable(preview_rect_provider):
                try:
                    preview_rect = preview_rect_provider(target)
                except Exception:
                    preview_rect = None
            return self.show(bounds, target, preview_rect=preview_rect)

        def started(_snapshot=None):
            render(lifecycle.dropTarget())

        def changed(target=None):
            render(target)

        def finished(_result=None):
            self.hide()

        connections = (
            lifecycle.moveStarted.connect(started),
            lifecycle.dropTargetChanged.connect(changed),
            lifecycle.moveFinished.connect(finished),
        )
        self._lifecycle_bindings[id(lifecycle)] = (lifecycle, connections)
        if lifecycle.isMoving():
            render(lifecycle.dropTarget())
        return lifecycle

    def unbindLifecycle(self, lifecycle=None):
        """Disconnect one lifecycle, or all lifecycle bindings when omitted."""
        keys = list(self._lifecycle_bindings) if lifecycle is None else [id(lifecycle)]
        removed = False
        for key in keys:
            binding = self._lifecycle_bindings.pop(key, None)
            if binding is None:
                continue
            removed = True
            for connection in binding[1]:
                try:
                    connection.disconnect()
                except Exception:
                    pass
        return removed

    def preview(self):
        return self._preview

    def ensurePreview(self):
        if self._preview is None:
            try:
                self._preview = self._preview_factory()
            except Exception:
                return None
        return self._preview

    def prepare(self):
        preview = self.ensurePreview()
        if preview is None:
            return False
        try:
            return bool(preview.prepare())
        except Exception:
            return False

    def isVisible(self):
        return bool(self._visible)

    def bounds(self):
        return self._bounds

    def target(self):
        return None if self._target is None else dict(self._target)

    def activeArea(self):
        return None if self._target is None else self._target.get("area")

    def activeScope(self):
        return None if self._target is None else self._target.get("scope")

    def previewRect(self):
        return self._preview_rect

    def show(self, bounds, target=None, *, scope=None, preview_rect=None):
        bounds = self._normalize_bounds(bounds)
        if bounds is None or not self.prepare():
            self.hide()
            return False
        target = self._normalize_target(target, scope)
        if preview_rect is not None:
            preview_rect = self._normalize_bounds(preview_rect)
        self._bounds = bounds
        self._target = target
        self._preview_rect = preview_rect
        preview = self._preview
        try:
            ok = bool(preview.show_zones(
                bounds,
                active=None if target is None else target["area"],
                active_scope=None if target is None else target["scope"],
                preview_rect=preview_rect,
            ))
        except Exception:
            ok = False
        self._visible = bool(ok)
        if not ok:
            self.hide()
        return ok

    def showResult(self, geometry, *, inset=True):
        geometry = self._normalize_bounds(geometry)
        if geometry is None or not self.prepare():
            return False
        try:
            ok = bool(self._preview.show(*geometry, inset=inset))
        except Exception:
            ok = False
        self._visible = bool(ok)
        self._bounds = geometry if ok else None
        self._target = None
        self._preview_rect = geometry if ok else None
        return ok

    def hide(self):
        preview = self._preview
        if preview is not None:
            try:
                preview.hide()
            except Exception:
                pass
        changed = self._visible or self._target is not None or self._bounds is not None
        self._visible = False
        self._bounds = None
        self._target = None
        self._preview_rect = None
        return bool(changed)

    def destroy(self):
        preview = self._preview
        self.unbindLifecycle()
        self.hide()
        if preview is not None:
            try:
                preview.destroy()
            except Exception:
                pass
        self._preview = None

    def snapshot(self):
        return {
            "visible": self._visible,
            "bounds": self._bounds,
            "target": self.target(),
            "previewRect": self._preview_rect,
        }
