"""Base retained QWidget-like wrapper for Dear PyGui items."""
from __future__ import annotations

import threading

from ..dispatch import LatestCallQueue
from ..core.object import Qt, QPoint, QRect, QSize, QSizePolicy, QObject, QEvent, QCloseEvent


class QWidget(QObject):
    """Base retained wrapper over one Dear PyGui item.

    The API intentionally mirrors the useful subset of QWidget properties:
    object name, dynamic properties, visibility/enabled state, geometry hints,
    tooltip and focus.  DPG remains the renderer and event owner.
    """

    def __init__(self, tag=None, *, parent=None, after=None, backend=None):
        from ..backends import dpg, get_backend
        if backend is dpg:
            backend = get_backend()
        # New code may use the Qt spelling QWidget(parent). Existing retained
        # controls still pass an already-created native tag as the first value.
        if isinstance(tag, QObject) and parent is None:
            parent, tag = tag, None
        if tag is None:
            backend, options = self._construction(parent, backend)
            if options:
                tag = backend.add_child_window(
                    width=-1, height=-1, border=False, no_scrollbar=True,
                    no_scroll_with_mouse=True, **options)
            else:
                tag = backend.add_window(width=640, height=480)
        super().__init__(parent=parent if isinstance(parent, QObject) else None, after=after)
        if backend is None:
            from ..backends import get_backend
            backend = get_backend()
        self.backend = backend
        self.tag = tag
        self._ui_thread = threading.get_ident()
        self._properties = {"enabled": True}
        # During an in-process QDialog hidden-construction transaction, visual
        # property writes are retained here and flushed once per widget before
        # the first layout/show. This collapses repeated configure_item() calls
        # without changing the public synchronous setter contract.
        self._pending_native_config = {}
        self._dynamic_properties = {}
        self._tooltip = None
        self._tooltip_text = None
        self._updates = LatestCallQueue(self._after) if self._after is not None else None
        self._layout_manager = None
        self._window_title = ""
        self._attributes = set()
        self._style_override = None
        self._palette_override = None
        self._polished = False
        self._minimum_size = QSize(0, 0)
        self._maximum_size = QSize(16777215, 16777215)
        self._size_policy = QSizePolicy()
        # Keep Qt visibility as retained state and avoid a native query during
        # construction. DearUIQt-created QWidget items are visible by default;
        # the few wrappers that intentionally create a hidden native item prime
        # the retained state explicitly (for example QStackedWidget pages).
        # This removes one Python/native crossing for every control on first-open.
        initial_visible = True
        self._explicit_visible = initial_visible
        self._effective_visible = bool(initial_visible and self._parent_effectively_visible())
        self._properties.setdefault("show", initial_visible)

    @staticmethod
    def _construction(parent, backend):
        # The legacy module-shaped proxy and its active renderer represent the
        # same backend. Store/compare the renderer, never the proxy identity.
        from ..backends import dpg, get_backend
        if backend is dpg:
            backend = get_backend()
        if isinstance(parent, QObject) and parent._deleted:
            raise RuntimeError("cannot construct a child of a deleted parent")
        if isinstance(parent, QObject) and parent.threadId() != threading.get_ident():
            raise RuntimeError("native child construction requires the parent's thread")
        if isinstance(parent, QWidget):
            parent._require_ui()
            if backend is not None and backend is not parent.backend:
                raise ValueError("parent and child must use the same backend")
        if backend is None:
            backend = getattr(parent, "backend", None)
        if backend is None:
            from ..backends import get_backend
            backend = get_backend()
        native_parent = getattr(parent, "tag", None) if isinstance(parent, QObject) else parent
        options = {} if native_parent is None else {"parent": native_parent}
        return backend, options

    def _on_ui(self, key, callback, *args, **kwargs):
        if self._deleted:
            return
        if threading.get_ident() == self._ui_thread:
            if self._updates is not None:
                self._updates.discard(key)
            callback(*args, **kwargs)
        elif self._updates is not None:
            self._updates.post(key, self._deliver, callback, args, kwargs)
        else:
            raise RuntimeError("worker updates require a UI scheduler")

    def _deliver(self, callback, args, kwargs=None):
        self._require_ui()
        if not self._deleted and self.backend.does_item_exist(self.tag):
            callback(*args, **(kwargs or {}))

    def _require_ui(self):
        if threading.get_ident() != self._ui_thread:
            raise RuntimeError("native widget access requires the UI thread")

    def _layout_tag(self):
        """Native root to move when this control participates in a layout."""
        return self.tag

    def _construction_batch_owner(self):
        current = self.parent
        while current is not None:
            constructing = getattr(current, "isConstructing", None)
            queue = getattr(current, "_queue_construction_widget_config", None)
            if callable(constructing) and callable(queue) and constructing():
                return current
            current = getattr(current, "parent", None)
        return None

    def _configure(self, key, value):
        return bool(self._configure_many(**{key: value}))

    def _configure_many(self, **values):
        """Retain changed properties and minimize Python/native crossings.

        Construction writes are committed by the owning QDialog.  Once the main
        QApplication is running, ordinary QWidget mutations are compressed again
        at event-loop-turn scope: repeated geometry/visibility/enabled changes for
        a widget become one ``configure_item`` call after layout events settle.
        Standalone/process-hosted widgets keep the immediate backend path.
        """
        changed = {key: value for key, value in values.items()
                   if self._properties.get(key, object()) != value}
        if not changed:
            return {}
        self._properties.update(changed)
        self._pending_native_config.update(changed)
        owner = self._construction_batch_owner()
        if owner is not None:
            owner._queue_construction_widget_config(self, changed)
            return changed
        try:
            from ..core.application import QApplication
            application = QApplication.instance()
            if (application is not None and application.threadId() == self.threadId()
                    and application.queueNativeUpdate(self, changed)):
                return changed
        except RuntimeError:
            raise
        except Exception:
            # Backend-light/fake environments without a live QApplication retain
            # the established synchronous configuration path.
            pass
        self._commit_native_config(changed)
        return changed

    def _commit_native_config(self, values):
        """Commit one already-coalesced native configuration transaction."""
        self._require_ui()
        if self._deleted or not values:
            return False
        if hasattr(self.backend, "does_item_exist") and not self.backend.does_item_exist(self.tag):
            return False
        self.backend.configure_item(self.tag, **values)
        for key, value in tuple(values.items()):
            if self._pending_native_config.get(key, object()) == value:
                self._pending_native_config.pop(key, None)
        return True

    def _set_value(self, value):
        if self._properties.get("value", object()) != value:
            self.backend.set_value(self.tag, value)
            self._properties["value"] = value

    def _user_value(self, value):
        # Native interaction is newer than any display value queued by a worker.
        self._require_ui()
        if self._updates is not None:
            self._updates.discard("value")
        self._properties["value"] = value

    def event(self, event):
        event_type = event.type()
        if event_type == QEvent.Show:
            self.showEvent(event)
            return True
        if event_type == QEvent.Hide:
            self.hideEvent(event)
            return True
        if event_type == QEvent.Close:
            self.closeEvent(event)
            return True
        if event_type == QEvent.FocusIn:
            self.focusInEvent(event)
            return True
        if event_type == QEvent.FocusOut:
            self.focusOutEvent(event)
            return True
        if event_type == QEvent.KeyPress:
            self.keyPressEvent(event)
            return event.isAccepted()
        if event_type == QEvent.KeyRelease:
            self.keyReleaseEvent(event)
            return event.isAccepted()
        if event_type == QEvent.ShortcutOverride:
            self.shortcutOverrideEvent(event)
            return event.isAccepted()
        if event_type == QEvent.MouseButtonPress:
            self.mousePressEvent(event)
            return event.isAccepted()
        if event_type == QEvent.MouseButtonRelease:
            self.mouseReleaseEvent(event)
            return event.isAccepted()
        if event_type == QEvent.MouseMove:
            self.mouseMoveEvent(event)
            return event.isAccepted()
        if event_type == QEvent.Enter:
            self.enterEvent(event)
            return event.isAccepted()
        if event_type == QEvent.Leave:
            self.leaveEvent(event)
            return event.isAccepted()
        if event_type == QEvent.Polish:
            self._polished = True
            self.polishEvent(event)
            return True
        if event_type == QEvent.LayoutRequest:
            layout = self.layout()
            if layout is not None:
                layout.activate()
            self.changeEvent(event)
            return True
        if event_type in (QEvent.EnabledChange, QEvent.DynamicPropertyChange,
                          QEvent.ParentChange, QEvent.WindowActivate,
                          QEvent.WindowDeactivate, QEvent.StyleChange,
                          QEvent.PaletteChange, QEvent.ApplicationPaletteChange):
            # QObject.__init__ emits ParentChange before QWidget retained state
            # exists.  Reparenting a live widget later must recompute effective
            # visibility without changing its explicit show/hide state.
            if event_type == QEvent.ParentChange and hasattr(self, "_explicit_visible"):
                self._sync_effective_visibility()
            self.changeEvent(event)
            return True
        return super().event(event)

    def showEvent(self, event):
        pass

    def hideEvent(self, event):
        pass

    def focusInEvent(self, event):
        pass

    def focusOutEvent(self, event):
        pass

    def keyPressEvent(self, event):
        # Base QWidget does not consume keyboard input. Subclasses can handle
        # the event by leaving it accepted or by calling event.accept().
        event.ignore()

    def keyReleaseEvent(self, event):
        event.ignore()

    def shortcutOverrideEvent(self, event):
        event.ignore()

    def mousePressEvent(self, event):
        event.ignore()

    def mouseReleaseEvent(self, event):
        event.ignore()

    def mouseMoveEvent(self, event):
        event.ignore()

    def enterEvent(self, event):
        # Enter/leave notifications are informative by default and should not
        # claim pointer input unless a subclass explicitly accepts them.
        event.ignore()

    def leaveEvent(self, event):
        event.ignore()

    def polishEvent(self, event):
        pass

    def ensurePolished(self):
        """Deliver one Qt-style polish event before first presentation.

        QWidget polish is intentionally retained-state only; it does not create
        a worker or force a render.  Dialog construction can therefore prepare a
        complete tree before it becomes visible.
        """
        if self._deleted or self._polished:
            return False
        self.sendEvent(QEvent(QEvent.Polish))
        return True

    def changeEvent(self, event):
        pass

    # ---------------------------------------------------------------- Qt-like common properties
    def style(self):
        if self._style_override is not None:
            return self._style_override
        try:
            from ..core.application import QApplication
            application = QApplication.instance()
            if application is not None:
                return application.style()
        except Exception:
            pass
        from ..gui.style import QStyleFactory
        return QStyleFactory.create("Fusion")

    def setStyle(self, style):
        from ..gui.style import QStyle, QStyleFactory
        if style is None:
            self._style_override = None
        else:
            if isinstance(style, str):
                style = QStyleFactory.create(style)
                if style is None:
                    raise ValueError("unknown style")
            if not isinstance(style, QStyle):
                raise TypeError("style must be QStyle, a registered name, or None")
            self._style_override = style
        self.sendEvent(QEvent(QEvent.StyleChange, style=self.style()))
        self._refresh_style()

    def palette(self):
        if self._palette_override is not None:
            return self._palette_override.copy()
        try:
            from ..core.application import QApplication
            application = QApplication.instance()
            if application is not None:
                return application.palette()
        except Exception:
            pass
        from ..gui.palette import QPalette
        return QPalette.fusion()

    def setPalette(self, palette):
        from ..gui.palette import QPalette
        if not isinstance(palette, QPalette):
            raise TypeError("palette must be QPalette")
        self._palette_override = palette.copy()
        self.sendEvent(QEvent(QEvent.PaletteChange, palette=self._palette_override.copy()))
        self._refresh_style()

    def unsetPalette(self):
        if self._palette_override is None:
            return
        self._palette_override = None
        self.sendEvent(QEvent(QEvent.PaletteChange, palette=self.palette()))
        self._refresh_style()

    def setObjectName(self, name):
        return super().setObjectName(name)

    def objectName(self):
        return super().objectName()

    def setProperty(self, name, value):
        key = str(name)
        previous = self._dynamic_properties.get(key, object())
        self._dynamic_properties[key] = value
        if previous != value:
            self.sendEvent(QEvent(QEvent.DynamicPropertyChange, name=key, value=value))
        return True

    def property(self, name):
        return self._dynamic_properties.get(str(name))

    def setEnabled(self, enabled):
        self._on_ui("enabled", self._set_enabled_now, bool(enabled))

    def _set_enabled_now(self, enabled):
        enabled = bool(enabled)
        previous = bool(self._properties.get("enabled", True))
        if self._configure("enabled", enabled):
            self._refresh_style()
        if previous != enabled:
            self.sendEvent(QEvent(QEvent.EnabledChange, enabled=enabled))

    def isEnabled(self):
        self._require_ui()
        # Enabled state is wrapper-owned; avoid a native configuration query on
        # every click/shortcut guard. All DearUIQt setters update this cache.
        return bool(self._properties.get("enabled", True))

    def setDisabled(self, disabled):
        self.setEnabled(not bool(disabled))

    def _parent_effectively_visible(self):
        """Return logical ancestor visibility without native polling.

        Layout/helper QObjects can sit between a control and its top-level, so
        walk the ownership chain instead of assuming the direct parent is a
        QWidget.  QtDialog exposes ``_visible_state`` while QWidget exposes
        ``_effective_visible``; both are retained and therefore cheap.
        """
        current = self.parent
        while current is not None:
            if hasattr(current, "_effective_visible"):
                if not bool(current._effective_visible):
                    return False
            elif hasattr(current, "_visible_state"):
                if not bool(current._visible_state):
                    return False
            current = getattr(current, "parent", None)
        return True

    @staticmethod
    def _direct_widget_children(owner):
        """Yield first QWidget descendants through ownership helper QObjects."""
        for child in tuple(getattr(owner, "_children", ())):
            if isinstance(child, QWidget):
                yield child
            else:
                yield from QWidget._direct_widget_children(child)

    def _sync_effective_visibility(self, *, cleanup=True):
        if self._deleted or not hasattr(self, "_explicit_visible"):
            return False
        effective = bool(self._explicit_visible and self._parent_effectively_visible())
        previous = bool(self._effective_visible)
        if previous == effective:
            return False
        self._effective_visible = effective
        if not effective and cleanup:
            try:
                from ..core.application import QApplication
                application = QApplication.instance()
                if application is not None and application.threadId() == self.threadId():
                    application._widget_hidden(self)
            except Exception:
                pass
        self.sendEvent(QEvent(QEvent.Show if effective else QEvent.Hide))
        # Parent hide/show changes effective visibility for descendants without
        # touching their explicit state.  This is the important Qt distinction:
        # a child hidden only by its parent is invisible but isHidden() is False.
        for child in self._direct_widget_children(self):
            child._sync_effective_visibility(cleanup=False)
        return True

    def _prime_visibility_state(self, visible):
        """Adopt a known native show state without another configure_item call."""
        self._explicit_visible = bool(visible)
        self._properties["show"] = bool(visible)
        self._effective_visible = bool(self._explicit_visible and self._parent_effectively_visible())

    def setVisible(self, visible):
        self._on_ui("show", self._set_visible_now, bool(visible))

    def _set_visible_now(self, visible):
        visible = bool(visible)
        previous_explicit = bool(self._explicit_visible)
        if visible == previous_explicit:
            return False
        if visible:
            self.ensurePolished()
            layout = self.layout()
            if layout is not None:
                layout.activate()
        self._explicit_visible = visible
        self._configure("show", visible)
        self._sync_effective_visibility()
        # Explicit hide/show changes layout participation.  Parent-hidden
        # propagation does not call this path, so it never dirties layouts just
        # because an ancestor toggled visibility.
        self.updateGeometry()
        return True

    def isVisible(self):
        """Return effective Qt visibility, including logical ancestors."""
        return bool(not self._deleted and self._effective_visible)

    def show(self):
        self.setVisible(True)

    def hide(self):
        self.setVisible(False)

    def isHidden(self):
        """Return whether this widget itself was explicitly hidden.

        This intentionally differs from ``not isVisible()`` when an ancestor is
        hidden, matching QWidget::isHidden().
        """
        return bool(self._deleted or not self._explicit_visible)

    def isVisibleTo(self, ancestor=None):
        """Return visibility through the logical ownership chain to ancestor."""
        current = self
        while current is not None:
            if hasattr(current, "_explicit_visible") and not bool(current._explicit_visible):
                return False
            if hasattr(current, "_visible_state") and not bool(current._visible_state):
                return False
            if ancestor is not None and current is ancestor:
                return True
            current = getattr(current, "parent", None)
        return ancestor is None

    def updateGeometry(self):
        """Queue one compressed LayoutRequest on the QApplication event loop.

        In-process widgets share one logical GUI event dispatcher.  Routing
        layout invalidation through QApplication mirrors Qt and, importantly,
        turns resize/property bursts from many per-widget scheduler callbacks
        into one application wake-up for the whole UI turn.
        """
        if self._deleted:
            return False
        # QWidget::updateGeometry invalidates the parent layout first.  Let the
        # layout own cache invalidation and bubble a single request to its root.
        layout_parent = self.parent
        if getattr(layout_parent, "_is_layout", False):
            invalidate = getattr(layout_parent, "invalidate", None)
            if callable(invalidate):
                return bool(invalidate())
        # Construction-time invalidation bubbles to the nearest QDialog-like
        # ancestor instead of waking QApplication for every child wrapper.
        # Controls are commonly parented through an ownership QObject, so walk
        # the logical QObject chain rather than assuming a direct QWidget parent.
        ancestor = self.parent
        while ancestor is not None:
            constructing = getattr(ancestor, "isConstructing", None)
            if callable(constructing) and constructing():
                try:
                    ancestor._construction_layout_dirty = True
                except Exception:
                    pass
                return True
            # A retained hidden QDialog has no pixels to reflow. Qt keeps the
            # layout dirty and activates it when the top-level is shown again;
            # do the same instead of waking the application for each child.
            if hasattr(ancestor, "_retained_layout_dirty"):
                visible = getattr(ancestor, "isVisible", None)
                if callable(visible) and not visible():
                    ancestor._retained_layout_dirty = True
                    return True
            ancestor = getattr(ancestor, "parent", None)
        try:
            from ..core.application import QApplication
            application = QApplication.instance()
            if application is not None and application.threadId() == self.threadId():
                return application.postEvent(self, QEvent(QEvent.LayoutRequest))
        except Exception:
            pass
        if self._updates is not None:
            return self._updates.post(
                "layout-request", self.sendEvent, QEvent(QEvent.LayoutRequest))
        self.sendEvent(QEvent(QEvent.LayoutRequest))
        return True

    def setLayout(self, layout):
        """Install one owned layout, matching QWidget::setLayout ownership.

        Layouts in this wrapper are retained native containers. Installing one
        moves its native root under the widget and reparents QObject ownership so
        deleting the widget deterministically disposes the entire layout tree.
        """
        self._require_ui()
        if self._deleted:
            raise RuntimeError("cannot set a layout on a deleted widget")
        if layout is None:
            return self.takeLayout()
        if not getattr(layout, "_is_layout", False):
            raise TypeError("setLayout requires a QLayout")
        if layout is self:
            raise ValueError("a widget cannot use itself as its layout")
        if layout._deleted:
            raise RuntimeError("cannot install a deleted layout")
        if layout.backend is not self.backend:
            raise ValueError("widget and layout must use the same backend")
        if self._layout_manager is not None and self._layout_manager is not layout:
            raise RuntimeError("widget already has a layout")
        try:
            self.backend.move_item(layout._layout_tag(), parent=self.tag)
        except Exception:
            # Some fake/minimal backends expose ownership only; native DPG uses
            # move_item and therefore follows the full retained-tree contract.
            if hasattr(self.backend, "move_item"):
                raise
        layout.setParent(self)
        self._layout_manager = layout
        self.updateGeometry()
        return layout

    def layout(self):
        layout = self._layout_manager
        return None if layout is not None and layout._deleted else layout

    def takeLayout(self):
        self._require_ui()
        layout = self.layout()
        if layout is None:
            self._layout_manager = None
            return None
        native_parent = self.backend.get_item_parent(self.tag) if hasattr(self.backend, "get_item_parent") else None
        if native_parent:
            self.backend.move_item(layout._layout_tag(), parent=native_parent)
        layout.setParent(self.parent)
        self._layout_manager = None
        self.updateGeometry()
        return layout

    def setWindowTitle(self, title):
        self._window_title = str(title or "")
        self._on_ui("label", self._set_window_title_now, self._window_title)

    def _set_window_title_now(self, title):
        try:
            self._configure("label", title)
        except Exception:
            # Child widgets may not expose a native label property. Qt still
            # stores windowTitle on them, so retain the value without failing.
            self._properties["label"] = title

    def windowTitle(self):
        return self._window_title

    def closeEvent(self, event):
        event.accept()

    def close(self):
        """Request QWidget-style close; hide unless WA_DeleteOnClose is set."""
        self._require_ui()
        if self._deleted:
            return True
        event = QCloseEvent()
        self.sendEvent(event)
        if not event.isAccepted():
            return False
        self.hide()
        if self.testAttribute(Qt.WA_DeleteOnClose):
            if self._after is not None:
                self.deleteLater()
            else:
                self.delete()
        return True

    def setAttribute(self, attribute, on=True):
        value = int(attribute)
        if on:
            self._attributes.add(value)
        else:
            self._attributes.discard(value)

    def testAttribute(self, attribute):
        return int(attribute) in self._attributes

    def parentWidget(self):
        """Return the nearest logical QWidget ancestor, skipping helper QObjects."""
        current = self.parent
        while current is not None:
            if isinstance(current, QWidget):
                return current
            current = getattr(current, "parent", None)
        return None

    def window(self):
        """Return the logical top-level object for this widget branch.

        Most branches terminate at a QWidget/QMainWindow. DearUIQt dialogs are
        QObject-based top-levels for compatibility, so this helper also honors
        any ancestor exposing Qt-like ``isWindow()`` semantics.
        """
        current = self
        candidate = self
        while current is not None:
            if isinstance(current, QWidget):
                candidate = current
            if current is not self:
                is_window = getattr(current, "isWindow", None)
                if callable(is_window) and is_window():
                    return current
            parent = getattr(current, "parent", None)
            if parent is None:
                return current if current is not self else candidate
            current = parent
        return candidate

    def topLevelWidget(self):
        return self.window()

    def isWindow(self):
        if isinstance(self.parent, QObject):
            return False
        try:
            return not bool(self.backend.get_item_parent(self.tag))
        except Exception:
            return self.parent is None

    def isAncestorOf(self, child):
        current = getattr(child, "parent", None)
        while current is not None:
            if current is self:
                return True
            current = getattr(current, "parent", None)
        return False

    def sizePolicy(self):
        return self._size_policy.copy()

    def setSizePolicy(self, horizontal, vertical=None):
        if isinstance(horizontal, QSizePolicy) and vertical is None:
            policy = horizontal.copy()
        else:
            if vertical is None:
                raise TypeError("setSizePolicy requires QSizePolicy or horizontal/vertical policies")
            policy = QSizePolicy(horizontal, vertical)
        if policy != self._size_policy:
            self._size_policy = policy
            self.updateGeometry()

    def minimumSize(self):
        return QSize(self._minimum_size.width(), self._minimum_size.height())

    def minimumWidth(self):
        return self._minimum_size.width()

    def minimumHeight(self):
        return self._minimum_size.height()

    def maximumSize(self):
        return QSize(self._maximum_size.width(), self._maximum_size.height())

    def maximumWidth(self):
        return self._maximum_size.width()

    def maximumHeight(self):
        return self._maximum_size.height()

    def setMinimumSize(self, width, height=None):
        size = width if isinstance(width, QSize) and height is None else QSize(width, height)
        size = QSize(max(0, size.width()), max(0, size.height()))
        if size != self._minimum_size:
            self._minimum_size = size
            self.updateGeometry()

    def setMinimumWidth(self, width):
        self.setMinimumSize(width, self._minimum_size.height())

    def setMinimumHeight(self, height):
        self.setMinimumSize(self._minimum_size.width(), height)

    def setMaximumSize(self, width, height=None):
        size = width if isinstance(width, QSize) and height is None else QSize(width, height)
        size = QSize(max(0, size.width()), max(0, size.height()))
        if size != self._maximum_size:
            self._maximum_size = size
            self.updateGeometry()

    def setMaximumWidth(self, width):
        self.setMaximumSize(width, self._maximum_size.height())

    def setMaximumHeight(self, height):
        self.setMaximumSize(self._maximum_size.width(), height)

    def minimumSizeHint(self):
        layout = self.layout()
        if layout is not None:
            hint = layout.minimumSize()
            if hint.isValid():
                return hint.expandedTo(self._minimum_size)
        return QSize(self._minimum_size.width(), self._minimum_size.height())

    def sizeHint(self):
        layout = self.layout()
        if layout is not None:
            hint = layout.sizeHint()
        else:
            width = int(self._properties.get("width", -1) or -1)
            height = int(self._properties.get("height", -1) or -1)
            hint = QSize(width, height)
        if hint.isValid():
            hint = hint.expandedTo(self._minimum_size).boundedTo(self._maximum_size)
        return hint

    def setFixedWidth(self, width):
        width = int(width)
        self._minimum_size = QSize(width, self._minimum_size.height())
        self._maximum_size = QSize(width, self._maximum_size.height())
        self._on_ui("width", self._configure, "width", width)
        self.updateGeometry()

    def setFixedHeight(self, height):
        height = int(height)
        self._minimum_size = QSize(self._minimum_size.width(), height)
        self._maximum_size = QSize(self._maximum_size.width(), height)
        self._on_ui("height", self._configure, "height", height)
        self.updateGeometry()

    def setFixedSize(self, width, height=None):
        size = width if isinstance(width, QSize) and height is None else QSize(width, height)
        width, height = size.width(), size.height()
        self._minimum_size = self._maximum_size = QSize(width, height)
        self._on_ui("size", self._configure_many, width=width, height=height)
        self.updateGeometry()

    def resize(self, width, height=None):
        # QWidget::resize accepts either QSize or width/height and changes
        # current geometry without altering min/max constraints.
        size = width if isinstance(width, QSize) and height is None else QSize(width, height)
        self._on_ui("size", self._configure_many,
                    width=size.width(), height=size.height())
        self.updateGeometry()

    def move(self, x, y=None):
        # Match QWidget::move(QPoint) as well as move(x, y).
        point = x if isinstance(x, QPoint) and y is None else QPoint(x, y)
        self._on_ui("pos", self._configure, "pos", point.toTuple())

    def setGeometry(self, x, y=None, width=None, height=None):
        # Support QWidget::setGeometry(QRect) without breaking the historical
        # four-integer DearUIQt spelling.
        if isinstance(x, QRect) and y is None and width is None and height is None:
            rect = x
        else:
            rect = QRect(x, y, width, height)
        self._on_ui("geometry", self._configure_many, pos=rect.topLeft().toTuple(),
                    width=rect.width(), height=rect.height())

    def pos(self):
        self._require_ui()
        retained = self._properties.get("pos")
        if retained is not None:
            try:
                return QPoint(*retained)
            except (TypeError, ValueError):
                pass
        try:
            return QPoint(*self.backend.get_item_pos(self.tag))
        except Exception:
            try:
                value = self.backend.get_item_configuration(self.tag).get("pos", (0, 0))
                return QPoint(*value)
            except Exception:
                return QPoint()

    def x(self):
        return self.pos().x()

    def y(self):
        return self.pos().y()

    def size(self):
        return QSize(self.width(), self.height())

    def geometry(self):
        point = self.pos()
        size = self.size()
        return QRect(point, size)

    def rect(self):
        size = self.size()
        return QRect(0, 0, size.width(), size.height())

    def width(self):
        self._require_ui()
        retained = self._properties.get("width")
        if retained is not None and int(retained) >= 0:
            return int(retained)
        try:
            return int(self.backend.get_item_configuration(self.tag).get("width", 0))
        except Exception:
            return int(retained or 0)

    def height(self):
        self._require_ui()
        retained = self._properties.get("height")
        if retained is not None and int(retained) >= 0:
            return int(retained)
        try:
            return int(self.backend.get_item_configuration(self.tag).get("height", 0))
        except Exception:
            return int(retained or 0)

    def setFocus(self):
        self._require_ui()
        try:
            from ..core.application import QApplication
            application = QApplication.instance()
            if application is not None and application.threadId() == self.threadId():
                if not application.canFocusWidget(self):
                    return False
                # Focus is a native synchronization point: a widget made visible
                # earlier in this callback must be committed before focus_item().
                application.flushNativeUpdates()
        except Exception:
            pass
        try:
            self.backend.focus_item(self.tag)
        except Exception:
            return False
        try:
            from ..core.application import QApplication
            application = QApplication.instance()
            if application is not None and application.threadId() == self.threadId():
                application._set_focus_widget(self)
        except Exception:
            pass
        return True

    def hasFocus(self):
        self._require_ui()
        try:
            from ..core.application import QApplication
            application = QApplication.instance()
            if application is not None and application.focusWidget() is self:
                return True
        except Exception:
            pass
        try:
            state = self.backend.get_item_state(self.tag) or {}
            return bool(state.get("focused", False) or state.get("active", False))
        except Exception:
            return False

    def clearFocus(self):
        self._require_ui()
        try:
            from ..core.application import QApplication
            application = QApplication.instance()
            if application is not None and application.threadId() == self.threadId():
                return application.clearFocusObject(self)
        except Exception:
            pass
        return False

    def exists(self):
        """Return whether the retained native item still exists.

        QObject lifetime remains authoritative; this helper is for optimized
        views that also need to tolerate renderer-side item replacement.
        """
        if self._deleted:
            return False
        try:
            return bool(self.backend.does_item_exist(self.tag))
        except Exception:
            return True

    def setFont(self, font):
        """Bind a renderer font while retaining it as QWidget state."""
        self._on_ui("font", self._set_font_now, font)
        return self

    def _set_font_now(self, font):
        self._properties["font"] = font
        binder = getattr(self.backend, "bind_item_font", None)
        if callable(binder) and font is not None:
            try:
                native = font.nativeId() if hasattr(font, "nativeId") else font
                binder(self.tag, native)
            except Exception:
                pass

    def font(self):
        return self._properties.get("font")

    def setTheme(self, theme):
        """Bind a DearUIQt theme resource or native materialized theme id."""
        self._require_ui()
        if self._deleted:
            return False
        native = theme.nativeId() if hasattr(theme, "nativeId") else theme
        try:
            self.backend.bind_item_theme(self.tag, native)
        except Exception:
            return False
        self._properties["theme"] = theme
        return True

    def theme(self):
        return self._properties.get("theme")

    def setThemeProvider(self, provider):
        """Bind a state-aware theme factory receiving focused/disabled flags.

        This DearUIQt extension lets compound controls share metrics without
        losing normal focus and enabled-state styling to a static theme.
        """
        self._require_ui()
        if provider is not None and not callable(provider):
            raise TypeError("theme provider must be callable or None")
        previous = getattr(self, '_state_theme_provider', None)
        if previous is None and provider is not None:
            self._provider_previous_theme = self.theme()
        self._state_theme_provider = provider
        if provider is None and previous is not None:
            self._properties['theme'] = self._provider_previous_theme
        refresh = getattr(self, '_refresh_style', None)
        if callable(refresh):
            refresh()

    def _apply_state_theme(self, *, focused=False, disabled=False):
        provider = getattr(self, '_state_theme_provider', None)
        if provider is None:
            return False
        self.setTheme(provider(focused=bool(focused), disabled=bool(disabled)))
        return True

    def underMouse(self):
        self._require_ui()
        try:
            return bool(self.backend.is_item_hovered(self.tag))
        except Exception:
            return False

    def isActive(self):
        self._require_ui()
        try:
            state = self.backend.get_item_state(self.tag) or {}
            return bool(state.get("active", False))
        except Exception:
            try:
                return bool(self.backend.is_item_active(self.tag))
            except Exception:
                return False

    def globalPos(self):
        """Return the renderer-space top-left point of this widget."""
        self._require_ui()
        # DPG 2.x windows omit rect_min and report pos relative to the nearest
        # parent window. Trusting that pos directly turned every child pane
        # rectangle into a (0,0)-origin box, which silently broke click
        # hit-testing. Reconstruct the absolute position from the parent chain
        # before falling back to the renderer state.
        try:
            from ..backends.dearpygui_scroller import dpg_window_rect
            rect = dpg_window_rect(self.backend, self.tag, clip=False)
            if rect is not None:
                return QPoint(int(round(rect[0])), int(round(rect[1])))
        except Exception:
            pass
        try:
            return QPoint(*self.backend.get_item_rect_min(self.tag))
        except Exception:
            return self.pos()

    def globalGeometry(self, *, clipped=False):
        """Return renderer-space geometry after the latest layout pass.

        ``clipped=True`` asks the backend adapter for the visible rectangle of
        scrolling child surfaces.  This is useful for canvas hit testing and
        keeps renderer-specific child-window reconstruction out of application
        code. Backends without a clipped-geometry adapter fall back to the
        ordinary global rectangle.
        """
        self._require_ui()
        if clipped:
            try:
                from ..backends.dearpygui import dpg_window_rect
                rect = dpg_window_rect(self.backend, self.tag, clip=True)
                if rect is not None:
                    left, top, right, bottom = rect
                    return QRect(int(round(left)), int(round(top)),
                                 max(0, int(round(right - left))),
                                 max(0, int(round(bottom - top))))
            except Exception:
                pass
        point = self.globalPos()
        try:
            width, height = self.backend.get_item_rect_size(self.tag)
            return QRect(point.x(), point.y(), int(width), int(height))
        except Exception:
            return QRect(point, self.size())

    def containsGlobalPoint(self, point, *, clipped=False):
        point = point if isinstance(point, QPoint) else QPoint(*point)
        return self.globalGeometry(clipped=clipped).contains(point)

    def nativeParentId(self):
        """Return the retained parent id for transitional/custom surfaces."""
        self._require_ui()
        getter = getattr(self.backend, "get_item_parent", None)
        if not callable(getter):
            return None
        try:
            return getter(self.tag)
        except Exception:
            return None

    def setToolTip(self, text):
        self._require_ui()
        text = str(text or "")
        self._tooltip_text = text
        try:
            if self._tooltip is None or not self.backend.does_item_exist(self._tooltip):
                with self.backend.tooltip(self.tag) as tooltip:
                    self._tooltip = tooltip
                    self.backend.add_text(text)
            else:
                children = self.backend.get_item_children(self._tooltip, 1) or []
                if children:
                    self.backend.set_value(children[0], text)
        except Exception:
            # Fake backends and old DPG builds can still use the property API.
            pass

    def toolTip(self):
        return self._tooltip_text or ""

    def _refresh_style(self):
        """Subclass hook after enabled/style-role changes."""

    def delete(self):
        self._require_ui()
        if self._deleted:
            return
        if self._updates is not None:
            self._updates.close()
        try:
            super().delete()
        finally:
            self._layout_manager = None
            if self.backend.does_item_exist(self.tag):
                self.backend.delete_item(self.tag)


__all__ = ["QWidget"]
