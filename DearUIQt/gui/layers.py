"""Owned retained paint layers for QCanvas/QPainter."""
from __future__ import annotations

from ..backends import get_backend
from ..core.object import QObject


class QPaintLayer(QObject):
    """Own one renderer draw layer while exposing only retained layer semantics."""
    def __init__(self, parent, *, after=None, backend=None):
        super().__init__(parent=parent if isinstance(parent, QObject) else None, after=after)
        self.backend = backend or getattr(parent, "backend", None) or get_backend()
        native_parent = getattr(parent, "tag", parent)
        kwargs = {"parent": native_parent}
        if after is not None:
            kwargs["after"] = getattr(after, "tag", after)
        cm = self.backend.draw_layer(**kwargs)
        self.tag = cm.__enter__()
        cm.__exit__(None, None, None)

    def nativeId(self):
        return self.tag

    def exists(self):
        try:
            return bool(self.backend.does_item_exist(self.tag))
        except Exception:
            return False

    def clear(self):
        if not self.exists():
            return False
        self.backend.delete_item(self.tag, children_only=True)
        return True

    def painter(self):
        from .painting import QPainter
        return QPainter(self, backend=self.backend)

    def delete(self):
        if self._deleted:
            return
        native = self.tag
        self.tag = None
        super().delete()
        if native is not None:
            try:
                if self.backend.does_item_exist(native):
                    self.backend.delete_item(native)
            except Exception:
                pass


__all__ = ["QPaintLayer"]
