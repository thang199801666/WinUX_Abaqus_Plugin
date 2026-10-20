"""Migration-safe retained item facade.

``QRetainedItem`` is the DearUIQt boundary for native items that are created by
specialized renderer facilities (draw primitives, legacy host containers, etc.)
but still need ordinary Qt-style geometry/state/lifetime access.  Application
code should use this facade instead of querying/configuring backend item ids.
"""
from __future__ import annotations

from ..core.object import QObject, QPoint, QRect, QSize
from .widget import QWidget


class QRetainedItem(QWidget):
    """Non-owning QWidget-like view over one existing retained native item.

    Set ``owns_native=True`` only when DearUIQt is the canonical owner of the
    native item.  The default is deliberately non-owning so temporary adapters
    can be used around host-created ids without changing their lifetime.
    """

    def __init__(self, tag, *, parent=None, after=None, backend=None,
                 owns_native=False):
        if tag is None:
            raise ValueError("QRetainedItem requires an existing native id")
        super().__init__(tag, parent=parent, after=after, backend=backend)
        # Existing native items may already be hidden. QWidget's construction
        # default (visible=True) is valid only for DearUIQt-created items; keep
        # retained visibility unknown until queried or explicitly configured so
        # the first ``show=True`` write is never coalesced away incorrectly.
        self._properties.pop("show", None)
        self._owns_native = bool(owns_native)

    @classmethod
    def focusedItem(cls, *, backend=None, parent=None):
        """Return a non-owning facade for the renderer-focused native item.

        This is the migration-safe equivalent of querying the renderer focus id
        directly. It deliberately returns ``None`` when no valid retained item
        owns focus, so application code can keep Qt-style focus scoping without
        importing the backend.
        """
        if backend is None:
            from ..backends import get_backend
            backend = get_backend()
        getter = getattr(backend, "get_focused_item", None)
        if not callable(getter):
            return None
        try:
            tag = getter()
        except Exception:
            return None
        if tag in (None, 0, ""):
            return None
        exists = getattr(backend, "does_item_exist", None)
        if callable(exists):
            try:
                if not exists(tag):
                    return None
            except Exception:
                return None
        return cls(tag, parent=parent, backend=backend, owns_native=False)

    def ownsNativeItem(self):
        return self._owns_native

    def setNativeOwnership(self, owns=True):
        self._owns_native = bool(owns)
        return self

    def configure(self, **values):
        """Apply retained native item properties through DearUIQt."""
        if "show" in values:
            visible = bool(values["show"])
            self._explicit_visible = visible
            self._effective_visible = bool(visible and self._parent_effectively_visible())
        self._on_ui("configure", self._configure_many, **values)
        return self

    def isVisible(self):
        """Query native visibility because adapted items may be mutated externally."""
        if self._deleted or not self.exists():
            return False
        getter = getattr(self.backend, "is_item_shown", None)
        if callable(getter):
            try:
                return bool(getter(self.tag))
            except Exception:
                pass
        return super().isVisible()

    def setVisible(self, visible):
        """Synchronize external native visibility before applying a Qt write.

        A retained facade can be constructed around an item that was hidden by
        legacy/renderer code.  QWidget's construction default is visible, so a
        plain ``show()`` could otherwise be coalesced as a no-op.  Re-snapshot
        the native state before the inherited transition to preserve correct
        show/hide semantics during migration.
        """
        visible = bool(visible)
        if not self._deleted and self.exists():
            getter = getattr(self.backend, "is_item_shown", None)
            if callable(getter):
                try:
                    current = bool(getter(self.tag))
                    self._explicit_visible = current
                    self._effective_visible = bool(current and self._parent_effectively_visible())
                    self._properties["show"] = current
                except Exception:
                    pass
        return super().setVisible(visible)

    def isActive(self):
        getter = getattr(self.backend, "is_item_active", None)
        if callable(getter):
            try:
                return bool(getter(self.tag))
            except Exception:
                pass
        return super().isActive()

    def underMouse(self):
        getter = getattr(self.backend, "is_item_hovered", None)
        if callable(getter):
            try:
                return bool(getter(self.tag))
            except Exception:
                pass
        return super().underMouse()

    def clear(self):
        self._require_ui()
        if not self.exists():
            return False
        self.backend.delete_item(self.tag, children_only=True)
        return True

    def setValue(self, value):
        self._on_ui("value", self._set_value, value)
        return self

    def value(self, default=None):
        self._require_ui()
        if not self.exists():
            return default
        try:
            value = self.backend.get_value(self.tag)
            self._properties["value"] = value
            return value
        except Exception:
            return self._properties.get("value", default)

    def verticalScrollValue(self):
        getter = getattr(self.backend, "get_y_scroll", None)
        if not callable(getter) or not self.exists():
            return 0.0
        try:
            return float(getter(self.tag))
        except Exception:
            return 0.0

    def setVerticalScrollValue(self, value):
        setter = getattr(self.backend, "set_y_scroll", None)
        if not callable(setter) or not self.exists():
            return False
        try:
            setter(self.tag, float(value))
            return True
        except Exception:
            return False

    def verticalScrollMaximum(self):
        getter = getattr(self.backend, "get_y_scroll_max", None)
        if not callable(getter) or not self.exists():
            return 0.0
        try:
            return float(getter(self.tag))
        except Exception:
            return 0.0

    def horizontalScrollValue(self):
        getter = getattr(self.backend, "get_x_scroll", None)
        if not callable(getter) or not self.exists():
            return 0.0
        try:
            return float(getter(self.tag))
        except Exception:
            return 0.0

    def setHorizontalScrollValue(self, value):
        setter = getattr(self.backend, "set_x_scroll", None)
        if not callable(setter) or not self.exists():
            return False
        try:
            setter(self.tag, float(value))
            return True
        except Exception:
            return False

    def horizontalScrollMaximum(self):
        getter = getattr(self.backend, "get_x_scroll_max", None)
        if not callable(getter) or not self.exists():
            return 0.0
        try:
            return float(getter(self.tag))
        except Exception:
            return 0.0

    def parentItem(self):
        self._require_ui()
        if not self.exists():
            return None
        try:
            return self.backend.get_item_parent(self.tag)
        except Exception:
            return None

    def itemInfo(self):
        self._require_ui()
        if not self.exists():
            return {}
        try:
            return dict(self.backend.get_item_info(self.tag) or {})
        except Exception:
            return {}

    def nativeConfiguration(self):
        """Return a snapshot of renderer configuration for this retained item.

        This is a migration-only escape hatch for host/runtime code which must
        inspect renderer-owned flags before the item has a dedicated typed
        DearUIQt API. Application feature code should prefer QWidget methods.
        """
        self._require_ui()
        if not self.exists():
            return {}
        getter = getattr(self.backend, "get_item_configuration", None)
        if not callable(getter):
            return {}
        try:
            return dict(getter(self.tag) or {})
        except Exception:
            return {}

    def nativeState(self):
        """Return a snapshot of renderer state behind this retained item.

        ``QRetainedItem`` is deliberately the migration boundary for native
        surfaces which do not yet have a dedicated Qt widget.  Exposing the
        snapshot here keeps ``get_item_state`` and its backend dependency out of
        application code while callers gradually move to typed QWidget APIs.
        """
        self._require_ui()
        if not self.exists():
            return {}
        getter = getattr(self.backend, "get_item_state", None)
        if not callable(getter):
            return {}
        try:
            return dict(getter(self.tag) or {})
        except Exception:
            return {}

    def childIds(self, slot=1):
        """Return native child ids for a retained container slot.

        Slot traversal is retained-only compatibility functionality. New
        QObject-owned composites should keep direct child references instead.
        """
        self._require_ui()
        if not self.exists():
            return ()
        getter = getattr(self.backend, "get_item_children", None)
        if not callable(getter):
            return ()
        try:
            return tuple(getter(self.tag, int(slot)) or ())
        except Exception:
            return ()

    def childItems(self, slot=1):
        return tuple(type(self)(tag, backend=self.backend, owns_native=False)
                     for tag in self.childIds(slot))

    def itemType(self):
        return str(self.itemInfo().get("type", "") or "")

    def setPosition(self, pos):
        if isinstance(pos, QPoint):
            pos = pos.toTuple()
        self.move(*pos)
        return self

    def rect(self):
        geometry = self.globalGeometry()
        return QRect(0, 0, geometry.width(), geometry.height())


    def reparent(self, parent, *, before=None):
        """Move this retained item under another native/Qt parent.

        This is the migration-safe equivalent of the renderer ``move_item``
        primitive.  Ownership is unchanged; only retained hierarchy changes.
        """
        self._require_ui()
        if not self.exists():
            return False
        native_parent = getattr(parent, "tag", parent)
        native_before = getattr(before, "tag", before) if before is not None else None
        mover = getattr(self.backend, "move_item", None)
        if not callable(mover):
            return False
        kwargs = {"parent": native_parent}
        if native_before is not None:
            kwargs["before"] = native_before
        try:
            mover(self.tag, **kwargs)
            return True
        except TypeError:
            try:
                if native_before is None:
                    mover(self.tag, parent=native_parent)
                else:
                    mover(self.tag, parent=native_parent, before=native_before)
                return True
            except Exception:
                return False
        except Exception:
            return False

    def setLabel(self, text):
        self.configure(label=str(text or ""))
        return self

    def setTexture(self, texture):
        native = texture.nativeId() if hasattr(texture, "nativeId") else texture
        self.configure(texture_tag=native)
        return self

    def deleteNative(self):
        self._require_ui()
        if self.exists():
            self.backend.delete_item(self.tag)
            return True
        return False

    def delete(self):
        if self._deleted:
            return
        if self._owns_native:
            return super().delete()
        # Preserve QWidget bookkeeping without deleting the host-owned native id.
        if self._updates is not None:
            self._updates.close()
        try:
            from ..core.application import QApplication
            application = QApplication.instance()
            if application is not None:
                application._clear_widget(self)
        except Exception:
            pass
        self._layout_manager = None
        QObject.delete(self)


__all__ = ["QRetainedItem"]
