"""QObject input adapter for retained surfaces that are not QWidget instances.

DearUIQt prefers real QWidget/QDialog wrappers for ordinary controls.  Some
high-throughput surfaces (draw-list views, native child HWNDs, custom canvases)
intentionally keep a specialized renderer.  ``QInputTarget`` lets those
surfaces participate in QApplication focus and popup keyboard routing without
allocating another Dear PyGui global key registry or pretending to own QWidget
geometry/lifecycle.
"""
from __future__ import annotations

from .object import Qt, QObject, QEvent, QKeyEvent, QMouseEvent, Signal


class QInputTarget(QObject):
    """Logical QApplication input receiver for a non-QWidget surface.

    ``key_handler`` receives ``QKeyEvent``. ``pointer_handler`` receives
    ``QMouseEvent`` plus Enter/Leave events. ``hit_test`` receives a global
    ``(x, y)`` tuple and should return truthy when this target owns that point.
    ``focus_handler`` is optional and is called with a bool for FocusIn/FocusOut
    transitions.
    """

    def __init__(self, *, parent=None, after=None, key_handler=None,
                 pointer_handler=None, hit_test=None, focus_handler=None,
                 object_name=""):
        super().__init__(parent=parent, after=after)
        self._key_handler = key_handler
        self._pointer_handler = pointer_handler
        self._hit_test = hit_test
        self._focus_handler = focus_handler
        self.focusChanged = Signal(self)
        self.popupChanged = Signal(self)
        self._popup_owned = False
        if object_name:
            self.setObjectName(object_name)
        self._sync_pointer_registration()


    def _sync_pointer_registration(self):
        from .application import QApplication
        application = QApplication.instance()
        if application is None or application.threadId() != self.threadId():
            return False
        enabled = self._pointer_handler is not None and self._hit_test is not None
        if enabled:
            return application.registerPointerTarget(self)
        return application.unregisterPointerTarget(self)

    def setPointerHandler(self, handler):
        if handler is not None and not callable(handler):
            raise TypeError("pointer handler must be callable or None")
        self._pointer_handler = handler
        self._sync_pointer_registration()
        return self

    def pointerHandler(self):
        return self._pointer_handler

    def setHitTest(self, hit_test):
        if hit_test is not None and not callable(hit_test):
            raise TypeError("hit test must be callable or None")
        self._hit_test = hit_test
        self._sync_pointer_registration()
        return self

    def hitTest(self, position):
        if self._deleted or self._hit_test is None:
            return False
        return bool(self._hit_test(position))

    def grabMouse(self):
        from .application import QApplication
        application = QApplication.instance()
        if application is None or application.threadId() != self.threadId():
            return False
        return application.setMouseGrabberObject(self)

    def releaseMouse(self):
        from .application import QApplication
        application = QApplication.instance()
        if application is None or application.threadId() != self.threadId():
            return False
        return application.releaseMouseGrabberObject(self)

    def hasMouseGrab(self):
        from .application import QApplication
        application = QApplication.instance()
        return bool(application is not None and application.mouseGrabberObject() is self)

    def setKeyHandler(self, handler):
        if handler is not None and not callable(handler):
            raise TypeError("key handler must be callable or None")
        self._key_handler = handler
        return self

    def keyHandler(self):
        return self._key_handler

    def setFocusHandler(self, handler):
        if handler is not None and not callable(handler):
            raise TypeError("focus handler must be callable or None")
        self._focus_handler = handler
        return self

    def event(self, event):
        event_type = event.type()
        if event_type in (QEvent.KeyPress, QEvent.KeyRelease, QEvent.ShortcutOverride):
            if self._key_handler is not None and isinstance(event, QKeyEvent):
                return bool(self._key_handler(event))
        elif event_type in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseMove):
            if self._pointer_handler is not None and isinstance(event, QMouseEvent):
                return bool(self._pointer_handler(event))
        elif event_type in (QEvent.Enter, QEvent.Leave):
            if self._pointer_handler is not None:
                return bool(self._pointer_handler(event))
        elif event_type in (QEvent.FocusIn, QEvent.FocusOut):
            focused = event_type == QEvent.FocusIn
            if self._focus_handler is not None:
                self._focus_handler(focused)
            self.focusChanged.emit(focused)
            return True
        return super().event(event)

    def setFocus(self):
        if self._deleted:
            return False
        from .application import QApplication
        application = QApplication.instance()
        if application is None or application.threadId() != self.threadId():
            return False
        return application.setFocusObject(self)

    def clearFocus(self):
        from .application import QApplication
        application = QApplication.instance()
        if application is None or application.threadId() != self.threadId():
            return False
        return application.clearFocusObject(self)

    def hasFocus(self):
        from .application import QApplication
        application = QApplication.instance()
        return bool(application is not None and application.focusObject() is self)

    def grabPopup(self):
        """Make this target the exclusive QApplication popup key receiver."""
        if self._deleted:
            return False
        from .application import QApplication
        application = QApplication.instance()
        if application is None or application.threadId() != self.threadId():
            return False
        changed = not self._popup_owned
        self._popup_owned = bool(application._register_popup(self))
        if changed and self._popup_owned:
            self.popupChanged.emit(True)
        return self._popup_owned

    def releasePopup(self):
        from .application import QApplication
        application = QApplication.instance()
        removed = False
        if application is not None and application.threadId() == self.threadId():
            removed = bool(application._unregister_popup(self))
        if self._popup_owned:
            self._popup_owned = False
            self.popupChanged.emit(False)
            return True
        return removed

    def ownsPopup(self):
        return bool(self._popup_owned)

    def delete(self):
        if self._deleted:
            return
        try:
            self.releasePopup()
        finally:
            try:
                self.releaseMouse()
            finally:
                try:
                    self.clearFocus()
                finally:
                    try:
                        from .application import QApplication
                        application = QApplication.instance()
                        if application is not None:
                            application.unregisterPointerTarget(self)
                    finally:
                        super().delete()


class QItemInputBinding(QObject):
    """Own item-scoped native pointer handlers behind Qt mouse-button values.

    This is a migration primitive for high-throughput retained surfaces such as
    ``QCanvas``.  It keeps DearPyGui handler registries inside DearUIQt while
    application code expresses pointer buttons with ``Qt.LeftButton`` /
    ``Qt.RightButton`` /
    ``Qt.MiddleButton``.  Bindings are QObject-owned and the native registry is
    deleted with the binding.
    """

    def __init__(self, target, *, backend=None, parent=None, after=None):
        if parent is None and isinstance(target, QObject):
            parent = target
        super().__init__(parent=parent if isinstance(parent, QObject) else None, after=after)
        if backend is None:
            backend = getattr(target, "backend", None)
        if backend is None:
            from ..backends import get_backend
            backend = get_backend()
        self.backend = backend
        self.target = getattr(target, "tag", target)
        self._registry = None
        self._specs = []

    @staticmethod
    def _button_name(button):
        return {
            Qt.LeftButton: "mvMouseButton_Left",
            Qt.RightButton: "mvMouseButton_Right",
            Qt.MiddleButton: "mvMouseButton_Middle",
        }.get(int(button))

    def _native_button(self, button):
        name = self._button_name(button)
        return getattr(self.backend, name, None) if name else None

    def onClick(self, button, callback):
        if not callable(callback):
            raise TypeError("pointer callback must be callable")
        self._specs.append(("click", int(button), callback))
        return self

    def onHover(self, callback):
        if not callable(callback):
            raise TypeError("hover callback must be callable")
        self._specs.append(("hover", None, callback))
        return self

    def onFocus(self, callback):
        """Invoke ``callback`` when the native item receives keyboard focus."""
        if not callable(callback):
            raise TypeError("focus callback must be callable")
        self._specs.append(("focus", None, callback))
        return self

    def onActivated(self, callback):
        """Invoke ``callback`` when the retained item becomes active."""
        if not callable(callback):
            raise TypeError("activation callback must be callable")
        self._specs.append(("activated", None, callback))
        return self

    def onDeactivated(self, callback):
        """Invoke ``callback`` when the retained item finishes activation."""
        if not callable(callback):
            raise TypeError("deactivation callback must be callable")
        self._specs.append(("deactivated", None, callback))
        return self

    def onResize(self, callback):
        """Invoke ``callback`` after the retained item is resized."""
        if not callable(callback):
            raise TypeError("resize callback must be callable")
        self._specs.append(("resize", None, callback))
        return self

    def onVisible(self, callback):
        """Invoke ``callback`` when the backend reports the item visible."""
        if not callable(callback):
            raise TypeError("visible callback must be callable")
        self._specs.append(("visible", None, callback))
        return self

    def activate(self):
        return self._rebuild()

    def _guard_item_callback(self, callback):
        """Drop callbacks that outlive their native target.

        Dear PyGui may have already queued an item-handler callback when a
        dialog, popup, or composite widget deletes that item.  Running the
        callback after teardown lets higher-level code query stale item ids
        (notably QComboBox hover/focus refreshes) and produces Error 1005.
        """
        def guarded(sender=None, app_data=None, user_data=None):
            if self._deleted:
                return None
            target = self.target
            exists = getattr(self.backend, "does_item_exist", None)
            if target is not None and callable(exists):
                try:
                    if not exists(target):
                        return None
                except Exception:
                    return None
            return callback(sender, app_data, user_data)
        return guarded

    def clear(self):
        self._specs.clear()
        self._rebuild()
        return self

    def _delete_registry(self):
        registry = self._registry
        self._registry = None
        if registry is None:
            return False
        try:
            if self.backend.does_item_exist(registry):
                self.backend.delete_item(registry)
                return True
        except Exception:
            pass
        return False

    def _rebuild(self):
        self._delete_registry()
        if self._deleted or not self._specs:
            return self
        try:
            with self.backend.item_handler_registry() as registry:
                for kind, button, callback in self._specs:
                    callback = self._guard_item_callback(callback)
                    if kind == "click":
                        native = self._native_button(button)
                        if native is not None:
                            self.backend.add_item_clicked_handler(
                                button=native, callback=callback)
                    elif kind == "hover":
                        handler = getattr(self.backend, "add_item_hover_handler", None)
                        if callable(handler):
                            handler(callback=callback)
                    elif kind == "focus":
                        handler = getattr(self.backend, "add_item_focus_handler", None)
                        if callable(handler):
                            handler(callback=callback)
                    elif kind == "activated":
                        handler = getattr(self.backend, "add_item_activated_handler", None)
                        if callable(handler):
                            handler(callback=callback)
                    elif kind == "deactivated":
                        handler = getattr(self.backend, "add_item_deactivated_handler", None)
                        if callable(handler):
                            handler(callback=callback)
                    elif kind == "resize":
                        handler = getattr(self.backend, "add_item_resize_handler", None)
                        if callable(handler):
                            handler(callback=callback)
                    elif kind == "visible":
                        handler = getattr(self.backend, "add_item_visible_handler", None)
                        if callable(handler):
                            handler(callback=callback)
            self.backend.bind_item_handler_registry(self.target, registry)
            self._registry = registry
        except Exception:
            self._registry = None
        return self

    def delete(self):
        if self._deleted:
            return
        try:
            self._delete_registry()
        finally:
            super().delete()


class QGlobalInputBinding(QObject):
    """Own one backend global handler registry using Qt key/button constants.

    Build the binding with ``onKeyPress``/``onMouse*`` and call ``activate``
    once.  This keeps renderer key constants and handler-registry lifetime out
    of application code while preserving the backend callback signatures.
    """

    _KEY_NAMES = {
        Qt.Key_Escape: ("mvKey_Escape",),
        Qt.Key_Tab: ("mvKey_Tab",),
        Qt.Key_Backspace: ("mvKey_Back", "mvKey_Backspace"),
        Qt.Key_Return: ("mvKey_Return", "mvKey_Enter"),
        Qt.Key_Enter: ("mvKey_NumPadEnter", "mvKey_Enter"),
        Qt.Key_Insert: ("mvKey_Insert",),
        Qt.Key_Delete: ("mvKey_Delete",),
        Qt.Key_Home: ("mvKey_Home",),
        Qt.Key_End: ("mvKey_End",),
        Qt.Key_Left: ("mvKey_Left",),
        Qt.Key_Up: ("mvKey_Up",),
        Qt.Key_Right: ("mvKey_Right",),
        Qt.Key_Down: ("mvKey_Down",),
        Qt.Key_PageUp: ("mvKey_Prior", "mvKey_PageUp"),
        Qt.Key_PageDown: ("mvKey_Next", "mvKey_PageDown"),
        Qt.Key_F1: ("mvKey_F1",), Qt.Key_F2: ("mvKey_F2",),
        Qt.Key_F3: ("mvKey_F3",), Qt.Key_F4: ("mvKey_F4",),
        Qt.Key_F5: ("mvKey_F5",), Qt.Key_F6: ("mvKey_F6",),
        Qt.Key_F7: ("mvKey_F7",), Qt.Key_F8: ("mvKey_F8",),
        Qt.Key_F9: ("mvKey_F9",), Qt.Key_F10: ("mvKey_F10",),
        Qt.Key_F11: ("mvKey_F11",), Qt.Key_F12: ("mvKey_F12",),
        Qt.Key_Space: ("mvKey_Spacebar", "mvKey_Space"),
    }
    for _letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        _KEY_NAMES[getattr(Qt, "Key_" + _letter, ord(_letter))] = ("mvKey_" + _letter,)

    def __init__(self, *, backend=None, parent=None, after=None):
        super().__init__(parent=parent if isinstance(parent, QObject) else None, after=after)
        if backend is None:
            from ..backends import get_backend
            backend = get_backend()
        self.backend = backend
        self._registry = None
        self._specs = []

    @classmethod
    def nativeKeyFor(cls, key, backend=None):
        if backend is None:
            from ..backends import get_backend
            backend = get_backend()
        for name in cls._KEY_NAMES.get(int(key), ()):
            value = getattr(backend, name, None)
            if value is not None:
                return value
        return None

    @classmethod
    def qtKeyForNative(cls, native_key, backend=None):
        """Translate one renderer key code back to its Qt key value."""
        if backend is None:
            from ..backends import get_backend
            backend = get_backend()
        for qt_key, names in cls._KEY_NAMES.items():
            for name in names:
                value = getattr(backend, name, None)
                if value is not None and value == native_key:
                    return qt_key
        return native_key

    def _native_key(self, key):
        return self.nativeKeyFor(key, self.backend)

    @staticmethod
    def _button_name(button):
        return {
            Qt.LeftButton: "mvMouseButton_Left",
            Qt.RightButton: "mvMouseButton_Right",
            Qt.MiddleButton: "mvMouseButton_Middle",
        }.get(int(button))

    def _native_button(self, button):
        name = self._button_name(button)
        return getattr(self.backend, name, None) if name else None

    def onKeyPress(self, key, callback, *, user_data=None):
        if not callable(callback):
            raise TypeError("key callback must be callable")
        self._specs.append(("key", int(key), callback, user_data, 0.0))
        return self

    def onMouseWheel(self, callback):
        if not callable(callback):
            raise TypeError("wheel callback must be callable")
        self._specs.append(("wheel", None, callback, None, 0.0))
        return self

    def onMouseMove(self, callback):
        if not callable(callback):
            raise TypeError("move callback must be callable")
        self._specs.append(("move", None, callback, None, 0.0))
        return self

    def onMouseDrag(self, button, callback, *, threshold=1.0):
        if not callable(callback):
            raise TypeError("drag callback must be callable")
        self._specs.append(("drag", int(button), callback, None, float(threshold)))
        return self

    def onMouseRelease(self, button, callback):
        if not callable(callback):
            raise TypeError("release callback must be callable")
        self._specs.append(("release", int(button), callback, None, 0.0))
        return self

    def onMouseClick(self, button, callback):
        if not callable(callback):
            raise TypeError("click callback must be callable")
        self._specs.append(("click", int(button), callback, None, 0.0))
        return self

    def _delete_registry(self):
        registry = self._registry
        self._registry = None
        if registry is None:
            return False
        try:
            if self.backend.does_item_exist(registry):
                self.backend.delete_item(registry)
                return True
        except Exception:
            pass
        return False

    def activate(self):
        self._delete_registry()
        if self._deleted or not self._specs:
            return self
        try:
            with self.backend.handler_registry() as registry:
                for kind, value, callback, user_data, threshold in self._specs:
                    if kind == "key":
                        native = self._native_key(value)
                        if native is not None:
                            self.backend.add_key_press_handler(
                                key=native, callback=callback, user_data=user_data)
                    elif kind == "wheel":
                        self.backend.add_mouse_wheel_handler(callback=callback)
                    elif kind == "move":
                        handler = getattr(self.backend, "add_mouse_move_handler", None)
                        if callable(handler):
                            handler(callback=callback)
                    else:
                        native = self._native_button(value)
                        if native is None:
                            continue
                        if kind == "drag":
                            self.backend.add_mouse_drag_handler(
                                button=native, threshold=threshold, callback=callback)
                        elif kind == "release":
                            self.backend.add_mouse_release_handler(
                                button=native, callback=callback)
                        elif kind == "click":
                            self.backend.add_mouse_click_handler(
                                button=native, callback=callback)
            self._registry = registry
        except Exception:
            self._registry = None
        return self

    def clear(self):
        self._specs.clear()
        self._delete_registry()
        return self

    def delete(self):
        if self._deleted:
            return
        try:
            self._delete_registry()
        finally:
            super().delete()


__all__ = ["QInputTarget", "QItemInputBinding", "QGlobalInputBinding"]
