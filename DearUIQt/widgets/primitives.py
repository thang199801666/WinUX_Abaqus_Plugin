"""Small visual primitives used by layouts and application chrome."""
from __future__ import annotations

from ..core.object import Qt, QSize, QSizePolicy
from .widget import QWidget


class QSpacer(QWidget):
    """Retained spacer primitive backed by Dear PyGui ``add_spacer``."""
    def __init__(self, width=0, height=0, *, parent=None, after=None, backend=None,
                 expanding=False):
        backend, options = self._construction(parent, backend)
        tag = backend.add_spacer(width=max(0, int(width)), height=max(0, int(height)), **options)
        super().__init__(tag, parent=parent, after=after, backend=backend)
        self._spacer_size = QSize(max(0, int(width)), max(0, int(height)))
        if expanding:
            self.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding))

    def changeSize(self, width, height):
        width, height = max(0, int(width)), max(0, int(height))
        self._spacer_size = QSize(width, height)
        self._configure_many(width=width, height=height)
        self.updateGeometry()

    def sizeHint(self):
        return QSize(self._spacer_size.width(), self._spacer_size.height())


class QSeparator(QWidget):
    """Horizontal/vertical separator with a stable QWidget lifecycle."""
    def __init__(self, orientation=Qt.Horizontal, *, parent=None, after=None,
                 backend=None, extent=1):
        backend, options = self._construction(parent, backend)
        self._orientation = int(orientation)
        extent = max(1, int(extent))
        if self._orientation == Qt.Horizontal and hasattr(backend, "add_separator"):
            tag = backend.add_separator(**options)
        else:
            width = extent if self._orientation == Qt.Vertical else -1
            height = -1 if self._orientation == Qt.Vertical else extent
            tag = backend.add_spacer(width=width, height=height, **options)
        super().__init__(tag, parent=parent, after=after, backend=backend)
        self._extent = extent

    def orientation(self):
        return self._orientation

    def sizeHint(self):
        if self._orientation == Qt.Vertical:
            return QSize(self._extent, 0)
        return QSize(0, self._extent)


__all__ = ["QSpacer", "QSeparator"]
