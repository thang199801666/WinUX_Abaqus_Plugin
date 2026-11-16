"""Base retained QWidget-like wrapper for Dear PyGui items."""
from __future__ import annotations

import threading
import weakref

from ..dispatch import LatestCallQueue
from ..core.object import Qt, QPoint, QRect, QSize, QSizePolicy, QObject, QEvent, QCloseEvent


# Most widgets never receive worker writes. Allocate their dispatch lock/queue
# only on demand; this one lock protects first-use racing with widget teardown.
_updates_creation_lock = threading.Lock()
_closed_updates = LatestCallQueue(None)
_closed_updates.close()


class QWidget(QObject):
    _live_widgets = weakref.WeakSet()
    """Base retained wrapper over one Dear PyGui item.

    The API intentionally mirrors the useful subset of QWidget properties:
    object name, dynamic properties, visibility/enabled state, geometry hints,
    tooltip and focus.  DPG remains the renderer and event owner.
    """

    def moveToThread(self, thread):
        """QWidget is GUI-thread-only, matching Qt's widget affinity rule."""
        raise RuntimeError("QWidget objects cannot be moved to another thread")

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
        # Monotonic identity for the renderer generation owned by this wrapper.
        # Deferred QApplication native writes capture this value; teardown or
        # explicit native replacement invalidates all work queued for an older
        # generation even if a backend later reuses the same numeric tag.
        self._native_generation = 0
        self._ui_thread = threading.get_ident()
        self._properties = {"enabled": True}
        # Keep the historical DearUIQt behavior (ordinary retained controls are
        # keyboard-focusable) while exposing Qt's explicit focus-policy API.
        # Specialized non-interactive widgets such as QLabel override this to
        # NoFocus in their constructor.
        self._focus_policy = Qt.StrongFocus
        self._focus_proxy = None
        self._widget_actions = []
        self._widget_action_shortcuts = {}
        self._widget_action_connections = {}
        # During an in-process QDialog hidden-construction transaction, visual
        # property writes are retained here and flushed once per widget before
        # the first layout/show. This collapses repeated configure_item() calls
        # without changing the public synchronous setter contract.
        self._pending_native_config = {}
        self._dynamic_properties = {}
        self._tooltip = None
        self._tooltip_text = None
        self._updates = None
        self._layout_manager = None
        self._window_title = ""
        # Retained top-level state mirrors QWidget::windowState(). Native
        # backends may synchronize this value from the OS without making
        # every query cross the Python/native boundary.
        self._window_state = Qt.WindowNoState
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
        # QWindow-like retained exposure state for top-level widgets. Native
        # hosts can adopt the OS-observed value without issuing a second show/hide.
        self._exposed = bool(initial_visible)
        # Register only the logical top-level.  The DPI lifecycle walks QObject
        # descendants on an actual monitor transition, so unchanged render
        # frames never iterate every widget.
        try:
            from ..gui.dpi import register_dpi_root
            register_dpi_root(self.window(), self.backend)
        except Exception:
            pass

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
            return
        if self._after is None:
            raise RuntimeError("worker updates require a UI scheduler")

        # Route worker writes through the process-global QApplication whenever
        # possible. ``postCallLatest`` preserves the historical latest-value
        # semantics while replacing many per-widget LatestCallQueue instances
        # with one keyed canonical dispatcher entry.
        try:
            from ..core.application import QCoreApplication
            application = QCoreApplication.instance()
        except Exception:
            application = None
        if (application is not None and
                application.threadId() == self._ui_thread and
                not getattr(application, "_quitting", False)):
            token = application.postCallLatest(
                ("QWidget.update", id(self), key),
                self._deliver, callback, args, kwargs)
            if token is not None and token is not False:
                return
        # Standalone widgets and legacy hosts keep the old local queue.
        self._update_queue().post(key, self._deliver, callback, args, kwargs)

    def _update_queue(self):
        updates = self._updates
        if updates is None:
            with _updates_creation_lock:
                if self._updates is None:
                    self._updates = (_closed_updates if self._deleted
                                     else LatestCallQueue(self._after, time_budget_ms=4.0))
                updates = self._updates
        return updates

    def _close_updates(self):
        with _updates_creation_lock:
            updates = self._updates
            self._updates = _closed_updates
        if updates is not None:
            updates.close()

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

    def controlMetrics(self):
        """Return metrics for this widget's current logical top-level screen."""
        from ..gui.style import metrics_for_backend
        try:
            surface = self.window()
        except Exception:
            surface = None
        return metrics_for_backend(self.backend, item=surface)

    def _dpi_changed(self, old_dpi, new_dpi):
        """Internal live-DPI hook shared by retained QWidget subclasses.

        The lifecycle invalidates the root layout once after walking the tree;
        individual widgets therefore refresh only native style/geometry that is
        explicitly DPI-derived and do not post their own LayoutRequest storms.
        """
        if self._deleted:
            return False
        event = QEvent(
            QEvent.DevicePixelRatioChange, oldDpi=float(old_dpi), dpi=float(new_dpi),
            oldScale=float(old_dpi) / 96.0, scale=float(new_dpi) / 96.0)
        self.sendEvent(event)
        try:
            self._refresh_style()
        except Exception:
            pass
        hook = getattr(self, "_apply_dpi_geometry", None)
        if callable(hook):
            try:
                hook(float(old_dpi), float(new_dpi))
            except Exception:
                pass
        return True

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
        """Commit one already-coalesced native configuration transaction.

        ``QApplication`` detaches a ready batch from its queue before the native
        flush begins.  A re-entrant layout/navigation pass may therefore write a
        newer retained value for the same widget while an older detached batch
        is still waiting to commit.  Never replay those superseded values: doing
        so can resize/reconfigure a renderer item against a native generation
        that has already moved on, and Dear PyGui may raise from
        ``configure_item`` even though the tag itself still exists.
        """
        self._require_ui()
        if self._deleted or not values:
            return False
        if hasattr(self.backend, "does_item_exist") and not self.backend.does_item_exist(self.tag):
            return False

        # A value is current only while both retained state and the pending
        # native mirror still agree with the detached batch.  Newer writes stay
        # queued for the next turn and must win over this older transaction.
        current = {
            key: value for key, value in values.items()
            if self._properties.get(key, object()) == value
            and self._pending_native_config.get(key, object()) == value
        }
        if not current:
            return False

        self.backend.configure_item(self.tag, **current)
        for key, value in tuple(current.items()):
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
        if event_type == QEvent.Wheel:
            self.wheelEvent(event)
            return event.isAccepted()
        if event_type == QEvent.Enter:
            self.enterEvent(event)
            return event.isAccepted()
        if event_type == QEvent.Leave:
            self.leaveEvent(event)
            return event.isAccepted()
        if event_type == QEvent.Move:
            self.moveEvent(event)
            return True
        if event_type == QEvent.Resize:
            self.resizeEvent(event)
            return True
        if event_type == QEvent.Expose:
            self.exposeEvent(event)
            return True
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
                          QEvent.PaletteChange, QEvent.ApplicationPaletteChange,
                          QEvent.ScreenChangeInternal, QEvent.DevicePixelRatioChange,
                          QEvent.WindowStateChange, QEvent.ActivationChange):
            # QObject.__init__ emits ParentChange before QWidget retained state
            # exists.  Reparenting a live widget later must recompute effective
            # visibility without changing its explicit show/hide state.
            if event_type == QEvent.ParentChange and hasattr(self, "_explicit_visible"):
                self._sync_effective_visibility()
                try:
                    from ..gui.dpi import register_dpi_root
                    register_dpi_root(self.window(), self.backend)
                except Exception:
                    pass
            self.changeEvent(event)
            return True
        return super().event(event)

    def showEvent(self, event):
        pass

    def hideEvent(self, event):
        pass

    def moveEvent(self, event):
        pass

    def resizeEvent(self, event):
        pass

    def exposeEvent(self, event):
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

    def wheelEvent(self, event):
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

    def _hide_owned_top_levels(self):
        """Hide QObject-owned top-level dialogs before this QWidget hides.

        QWidget descendants already inherit effective visibility through the
        normal retained tree.  QDialog is historically a QObject top-level in
        DearUIQt, so it needs an explicit ownership edge to avoid an orphaned
        modal/modeless window when a QMainWindow or parent widget closes.
        """
        try:
            from ..dialogs.qt_dialog import QtDialog
        except Exception:
            QtDialog = ()
        pending = list(getattr(self, "_children", ()))
        seen = set()
        while pending:
            child = pending.pop(0)
            if child is None or id(child) in seen:
                continue
            seen.add(id(child))
            if isinstance(child, QWidget):
                # Native QWidget descendants already inherit effective
                # visibility from this owner; do not turn their implicit hide
                # into an explicit hide. Their own top-level QObject children
                # are handled when they become an ownership root.
                continue
            if not isinstance(child, QtDialog):
                pending.extend(tuple(getattr(child, "_children", ())))
                continue
            try:
                if not child.isVisible():
                    continue
                child._owner_teardown_in_progress = True
                child.hide()
            except Exception:
                try:
                    child.destroy()
                except Exception:
                    pass
            finally:
                try:
                    child._owner_teardown_in_progress = False
                except Exception:
                    pass

    def setVisible(self, visible):
        self._on_ui("show", self._set_visible_now, bool(visible))

    def _set_visible_now(self, visible):
        visible = bool(visible)
        previous_explicit = bool(self._explicit_visible)
        if visible == previous_explicit:
            return False
        if not visible:
            self._hide_owned_top_levels()
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
        if self._after is not None:
            return self._update_queue().post(
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

    @staticmethod
    def _normalized_window_state(state):
        state = int(state)
        presentation = state & (Qt.WindowMinimized | Qt.WindowMaximized | Qt.WindowFullScreen)
        # Qt window presentation states are mutually exclusive. Be tolerant of
        # callers passing a bitmask and choose the strongest explicit state.
        if presentation & Qt.WindowFullScreen:
            presentation = Qt.WindowFullScreen
        elif presentation & Qt.WindowMaximized:
            presentation = Qt.WindowMaximized
        elif presentation & Qt.WindowMinimized:
            presentation = Qt.WindowMinimized
        else:
            presentation = Qt.WindowNoState
        return presentation | (state & Qt.WindowActive)

    def windowState(self):
        return int(self._window_state)

    def _apply_window_state_native(self, state):
        if not self.isWindow():
            return False
        try:
            from ..backends.native_windows import NativeWindowBackend
            native = NativeWindowBackend(self.backend)
            return bool(native.setWindowState(self, int(state)))
        except Exception:
            return False

    def _set_window_state_now(self, state, *, apply_native=True, source="api"):
        if self._deleted or not self.isWindow():
            return False
        state = self._normalized_window_state(state)
        previous = int(self._window_state)
        if previous == state:
            return False
        self._window_state = state
        if apply_native:
            self._apply_window_state_native(state)
        self.sendEvent(QEvent(
            QEvent.WindowStateChange, oldState=previous, state=state, source=str(source)))
        return True

    def setWindowState(self, state):
        self._on_ui("window-state", self._set_window_state_now, int(state))

    def syncWindowStateFromNative(self, state):
        """Adopt an OS-observed top-level state without writing it back.

        Native event/message-pump integrations use this to keep retained Qt
        state authoritative after taskbar, caption-button or Win+Arrow actions.
        """
        self._require_ui()
        return self._set_window_state_now(state, apply_native=False, source="native")

    def isExposed(self):
        """Return retained QWindow-like exposure for a top-level QWidget."""
        if not self.isWindow() or self._deleted:
            return False
        return bool(self._exposed and self.isVisible() and not self.isMinimized())

    def syncExposureFromNative(self, exposed):
        """Adopt native visibility/exposure without issuing show/hide calls."""
        self._require_ui()
        if self._deleted or not self.isWindow():
            return False
        exposed = bool(exposed)
        previous = bool(self._exposed)
        if previous == exposed:
            return False
        self._exposed = exposed
        self.sendEvent(QEvent(QEvent.Expose, exposed=exposed, oldExposed=previous, source="native"))
        return True

    def syncGeometryFromNative(self, rect):
        """Adopt an OS-observed top-level frame rectangle without write-back.

        This mirrors QWindow move/resize notifications: only changed position
        or size generates an event, and native synchronization never calls
        configure_item/SetWindowPos again.
        """
        self._require_ui()
        if self._deleted or not self.isWindow():
            return False
        rect = rect if isinstance(rect, QRect) else QRect(*rect)
        old_pos = self.pos()
        old_size = self.size()
        new_pos, new_size = rect.topLeft(), rect.size()
        moved = old_pos != new_pos
        resized = old_size != new_size
        if not moved and not resized:
            return False
        self._properties["pos"] = new_pos.toTuple()
        self._properties["width"] = new_size.width()
        self._properties["height"] = new_size.height()
        if moved:
            self.sendEvent(QEvent(QEvent.Move, oldPos=old_pos, pos=new_pos, source="native"))
        if resized:
            self.sendEvent(QEvent(QEvent.Resize, oldSize=old_size, size=new_size, source="native"))
            self.updateGeometry()
        return True

    def showMinimized(self):
        self.setWindowState(Qt.WindowMinimized)
        self.show()

    def showMaximized(self):
        self.setWindowState(Qt.WindowMaximized)
        self.show()

    def showFullScreen(self):
        self.setWindowState(Qt.WindowFullScreen)
        self.show()

    def showNormal(self):
        self.setWindowState(Qt.WindowNoState)
        self.show()

    def isMinimized(self):
        return bool(self.windowState() & Qt.WindowMinimized)

    def isMaximized(self):
        return bool(self.windowState() & Qt.WindowMaximized)

    def isFullScreen(self):
        return bool(self.windowState() & Qt.WindowFullScreen)

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

    def activateWindow(self):
        """Mark this top-level as active through QApplication state.

        Platform-specific top-levels may extend this to perform native focus or
        Z-order work, but the logical Qt activation transition is centralized
        here for ordinary QWidget surfaces.
        """
        if self._deleted or not self.isWindow():
            return False
        try:
            from ..core.application import QApplication
            application = QApplication.instance()
            if application is None:
                return False
            changed = application.setActiveWindow(self)
            application.setFocusWidget(self)
            return bool(changed or application.activeWindow() is self)
        except Exception:
            return False

    def isActiveWindow(self):
        try:
            from ..core.application import QApplication
            application = QApplication.instance()
            return bool(application is not None and application.activeWindow() is self)
        except Exception:
            return False

    def isAncestorOf(self, child):
        current = getattr(child, "parent", None)
        while current is not None:
            if current is self:
                return True
            current = getattr(current, "parent", None)
        return False

    def sizePolicy(self):
        return self._size_policy.copy()

    def hasHeightForWidth(self):
        """Return whether this widget or its installed layout depends on width."""
        if self._size_policy.hasHeightForWidth():
            return True
        layout = getattr(self, "_layout_manager", None)
        if layout is not None and getattr(layout, "_deleted", False):
            layout = None
        callback = getattr(layout, "hasHeightForWidth", None) if layout is not None else None
        return bool(callback()) if callable(callback) else False

    def heightForWidth(self, width):
        """Return preferred height for *width*, delegating to the installed layout."""
        layout = getattr(self, "_layout_manager", None)
        if layout is not None and getattr(layout, "_deleted", False):
            layout = None
        callback = getattr(layout, "heightForWidth", None) if layout is not None else None
        if callable(callback):
            try:
                value = int(callback(int(width)))
                if value >= 0:
                    return value
            except (TypeError, ValueError, OverflowError):
                pass
        return -1

    def hasWidthForHeight(self):
        """DearUIQt reciprocal sizing extension, including installed layouts."""
        if self._size_policy.hasWidthForHeight():
            return True
        layout = getattr(self, "_layout_manager", None)
        if layout is not None and getattr(layout, "_deleted", False):
            layout = None
        callback = getattr(layout, "hasWidthForHeight", None) if layout is not None else None
        return bool(callback()) if callable(callback) else False

    def baselineOffset(self, width=None):
        """Return text baseline from the widget top, or ``-1`` when undefined.

        Text-bearing controls override this lightweight hook.  Layouts use it
        only when an item explicitly requests ``Qt.AlignBaseline``.
        """
        del width
        return -1

    def widthForHeight(self, height):
        """Return preferred width for *height*, delegating to the installed layout."""
        layout = getattr(self, "_layout_manager", None)
        if layout is not None and getattr(layout, "_deleted", False):
            layout = None
        callback = getattr(layout, "widthForHeight", None) if layout is not None else None
        if callable(callback):
            try:
                value = int(callback(int(height)))
                if value >= 0:
                    return value
            except (TypeError, ValueError, OverflowError):
                pass
        return -1

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

    def _resize_now(self, size, *, source="api"):
        old_size = self.size()
        if old_size == size:
            return False
        self._configure_many(width=size.width(), height=size.height())
        self.sendEvent(QEvent(QEvent.Resize, oldSize=old_size, size=size, source=str(source)))
        self.updateGeometry()
        return True

    def resize(self, width, height=None):
        # QWidget::resize accepts either QSize or width/height and changes
        # current geometry without altering min/max constraints.
        size = width if isinstance(width, QSize) and height is None else QSize(width, height)
        self._on_ui("size", self._resize_now, size)

    def _move_now(self, point, *, source="api"):
        old_pos = self.pos()
        if old_pos == point:
            return False
        self._configure("pos", point.toTuple())
        self.sendEvent(QEvent(QEvent.Move, oldPos=old_pos, pos=point, source=str(source)))
        return True

    def move(self, x, y=None):
        # Match QWidget::move(QPoint) as well as move(x, y).
        point = x if isinstance(x, QPoint) and y is None else QPoint(x, y)
        self._on_ui("pos", self._move_now, point)

    def _set_geometry_now(self, rect, *, source="api"):
        old_pos, old_size = self.pos(), self.size()
        new_pos, new_size = rect.topLeft(), rect.size()
        moved, resized = old_pos != new_pos, old_size != new_size
        if not moved and not resized:
            return False
        self._configure_many(pos=new_pos.toTuple(), width=new_size.width(), height=new_size.height())
        if moved:
            self.sendEvent(QEvent(QEvent.Move, oldPos=old_pos, pos=new_pos, source=str(source)))
        if resized:
            self.sendEvent(QEvent(QEvent.Resize, oldSize=old_size, size=new_size, source=str(source)))
            self.updateGeometry()
        return True

    def setGeometry(self, x, y=None, width=None, height=None):
        # Support QWidget::setGeometry(QRect) without breaking the historical
        # four-integer DearUIQt spelling.
        if isinstance(x, QRect) and y is None and width is None and height is None:
            rect = x
        else:
            rect = QRect(x, y, width, height)
        self._on_ui("geometry", self._set_geometry_now, rect)

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

    def addAction(self, action):
        from ..gui.action import QAction
        if isinstance(action, str):
            action = QAction(action, parent=self)
        if not isinstance(action, QAction):
            raise TypeError("addAction requires QAction or text")
        if action in self._widget_actions:
            return action
        self._widget_actions.append(action)
        self._widget_action_connections[action] = action.changed.connect(
            lambda _action=action: self._sync_action_shortcuts(_action), receiver=self)
        action.destroyed.connect(lambda *_args, _action=action: self.removeAction(_action), receiver=self)
        self._sync_action_shortcuts(action)
        return action

    def actions(self):
        return [action for action in self._widget_actions if not action._deleted]

    def removeAction(self, action):
        if action not in self._widget_actions:
            return False
        self._widget_actions.remove(action)
        connection = self._widget_action_connections.pop(action, None)
        if connection is not None:
            connection.disconnect()
        for shortcut in self._widget_action_shortcuts.pop(action, []):
            if not shortcut._deleted:
                shortcut.delete()
        return True

    def _sync_action_shortcuts(self, action):
        from ..gui.shortcut import QShortcut
        for shortcut in self._widget_action_shortcuts.pop(action, []):
            if not shortcut._deleted:
                shortcut.delete()
        if action._deleted or not action.isVisible():
            return
        shortcuts = []
        for sequence in action.shortcuts():
            shortcut = QShortcut(sequence, self, context=action.shortcutContext())
            shortcut._action_owner = action
            shortcut.setEnabled(action.isEnabled())
            shortcut.activated.connect(lambda _action=action: _action.trigger(), receiver=self)
            shortcuts.append(shortcut)
        self._widget_action_shortcuts[action] = shortcuts

    def setFocusPolicy(self, policy):
        """Set the QWidget focus policy used by Qt-style traversal.

        Dear PyGui remains the native renderer, so this policy primarily owns
        DearUIQt's logical Tab/click routing rather than changing a backend
        flag.  The values intentionally match Qt.FocusPolicy.
        """
        policy = int(policy)
        allowed = {Qt.NoFocus, Qt.TabFocus, Qt.ClickFocus, Qt.StrongFocus, Qt.WheelFocus}
        if policy not in allowed:
            raise ValueError("invalid Qt focus policy")
        self._focus_policy = policy
        return self

    def focusPolicy(self):
        return int(self._focus_policy)

    def setFocusProxy(self, proxy):
        """Redirect logical focus to another QWidget, mirroring QWidget.

        A proxy must be live, on the same UI thread/backend and may not create
        a proxy cycle.  ``None`` clears the proxy.
        """
        if proxy is None:
            self._focus_proxy = None
            return self
        if not isinstance(proxy, QWidget):
            raise TypeError("focus proxy must be QWidget or None")
        if proxy is self:
            raise ValueError("a widget cannot be its own focus proxy")
        if proxy._deleted:
            raise RuntimeError("cannot use a deleted widget as focus proxy")
        if proxy.threadId() != self.threadId():
            raise RuntimeError("focus proxy must belong to the same UI thread")
        if proxy.backend is not self.backend:
            raise ValueError("focus proxy must use the same backend")
        current = proxy
        seen = {id(self)}
        for _ in range(64):
            if id(current) in seen:
                raise ValueError("focus proxy cycle detected")
            seen.add(id(current))
            current = getattr(current, "_focus_proxy", None)
            if current is None:
                break
        else:
            raise ValueError("focus proxy chain is too deep")
        self._focus_proxy = proxy
        return self

    def focusProxy(self):
        proxy = self._focus_proxy
        if proxy is not None and proxy._deleted:
            self._focus_proxy = None
            return None
        return proxy

    def _effective_focus_widget(self):
        current = self
        seen = set()
        for _ in range(64):
            proxy = getattr(current, "_focus_proxy", None)
            if proxy is None or proxy._deleted or id(proxy) in seen:
                return current
            seen.add(id(current))
            current = proxy
        return current

    def acceptsTabFocus(self):
        return bool(self.focusPolicy() & Qt.TabFocus)

    def acceptsClickFocus(self):
        return bool(self.focusPolicy() & Qt.ClickFocus)

    def setFocus(self):
        self._require_ui()
        target = self._effective_focus_widget()
        if target is not self:
            return target.setFocus()
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
                application.setFocusWidget(self)
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
        previous = self._properties.get("font")
        self._properties["font"] = font
        binder = getattr(self.backend, "bind_item_font", None)
        if callable(binder) and font is not None:
            try:
                native = font.nativeId() if hasattr(font, "nativeId") else font
                binder(self.tag, native)
            except Exception:
                pass
        if previous is not font:
            self.updateGeometry()

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
                from ..tooltip import TOOLTIP_DELAY
                with self.backend.tooltip(self.tag, delay=TOOLTIP_DELAY, hide_on_activity=True) as tooltip:
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

    def _invalidate_native_generation(self):
        self._native_generation = int(getattr(self, "_native_generation", 0)) + 1
        return self._native_generation

    def delete(self):
        self._require_ui()
        if self._deleted:
            return
        # Invalidate detached event-turn writes before any native child/root is
        # removed.  A reused backend tag must never make an older transaction
        # appear current again.
        self._invalidate_native_generation()
        # Direct QObject-style deletion must tear down owned top-levels before
        # the logical ownership tree starts disappearing.  Otherwise an owned
        # QDialog can run its normal hide/destroy focus-return path while this
        # QWidget owner is already inside deletion, briefly reactivating a
        # window that is about to vanish.  QWidget::close() already reaches the
        # same ordering through hide(); make explicit delete() equally safe.
        self._hide_owned_top_levels()
        try:
            from ..gui.dpi import unregister_dpi_participant
            unregister_dpi_participant(self, self.backend)
        except Exception:
            pass
        for action in list(self._widget_actions):
            self.removeAction(action)
        self._close_updates()
        # Purge event-turn native mutations before the renderer tag is removed.
        # Model/view rebuilds can delete a table and recreate another table in
        # the same turn; leaving an old configure transaction queued lets it
        # replay against the dead native generation on the next posted turn.
        try:
            from ..core.application import QApplication
            application = QApplication.instance()
            if application is not None and application.threadId() == self.threadId():
                application.removeNativeUpdates(self, subtree=True)
        except Exception:
            pass
        try:
            super().delete()
        finally:
            self._layout_manager = None
            if self.backend.does_item_exist(self.tag):
                self.backend.delete_item(self.tag)


__all__ = ["QWidget"]
