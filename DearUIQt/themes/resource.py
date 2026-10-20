"""QObject-owned materialized theme resources.

Applications should normally pass :class:`QTheme` to ``QWidget.setTheme`` or
``QDialog.setTheme`` instead of retaining/deleting renderer theme ids.  The
resource keeps DearPyGui lifetime management at the DearUIQt boundary while
remaining compatible with existing theme factories that return native ids.
"""
from __future__ import annotations

from ..backends import get_backend
from ..core import QObject
from .spec import ThemeSpec, create_theme


class QTheme(QObject):
    """Own one materialized renderer theme with QObject lifetime semantics."""

    def __init__(self, spec=None, *, theme_id=None, backend=None, parent=None,
                 after=None, owns=True):
        super().__init__(parent=parent, after=after)
        self.backend = backend or get_backend()
        if spec is not None and theme_id is not None:
            raise ValueError("provide either spec or theme_id, not both")
        if spec is not None:
            if not isinstance(spec, ThemeSpec):
                raise TypeError("spec must be a ThemeSpec")
            theme_id = create_theme(spec, backend=self.backend)
        if theme_id is None:
            raise ValueError("QTheme requires a ThemeSpec or theme_id")
        self._theme_id = theme_id
        self._owns = bool(owns)

    def nativeId(self):
        return self._theme_id

    @property
    def tag(self):
        return self._theme_id

    def exists(self):
        tag = self._theme_id
        if tag is None:
            return False
        try:
            return bool(self.backend.does_item_exist(tag))
        except Exception:
            return True

    def bind(self, widget):
        setter = getattr(widget, "setTheme", None)
        if not callable(setter):
            raise TypeError("theme target must provide setTheme()")
        return setter(self)

    def release(self):
        """Relinquish native ownership and return the renderer theme id."""
        self._owns = False
        return self._theme_id

    def delete(self):
        if self._deleted:
            return
        tag = self._theme_id
        owns = self._owns
        self._theme_id = None
        self._owns = False
        try:
            super().delete()
        finally:
            if owns and tag is not None:
                try:
                    if self.backend.does_item_exist(tag):
                        self.backend.delete_item(tag)
                except Exception:
                    pass


__all__ = ["QTheme"]
