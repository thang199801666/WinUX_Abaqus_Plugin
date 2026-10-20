"""Qt-style application/event dispatcher for the retained wrapper layer.

The class deliberately does not own Dear PyGui's render loop.  It owns the
*logical* Qt responsibilities that should be process-global: posted events,
focus/active-window bookkeeping and orderly application shutdown.  A host can
supply its existing ``after`` scheduler, so no worker thread is created.
"""
from __future__ import annotations

from collections import OrderedDict
import threading

from .object import QObject, QEvent, QKeyEvent, QMouseEvent, QPointer, Qt, Signal


class QApplication(QObject):
    _instance = None
    _instance_lock = threading.Lock()

    def __init__(self, *, after=None):
        with self._instance_lock:
            current = type(self)._instance
            if current is not None and not current._deleted:
                raise RuntimeError("only one QApplication may exist")
            super().__init__(after=after)
            type(self)._instance = self
        self.focusChanged = Signal(self)
        self.focusObjectChanged = Signal(self)
        self.activeWindowChanged = Signal(self)
        # Emitted for native keyboard/pointer input seen by the application.
        # Hosts can use this as a Qt-like application activity signal without
        # installing another process-global Dear PyGui handler registry.
        self.userActivity = Signal(self)
        self.aboutToQuit = Signal(self)
        self.paletteChanged = Signal(self)
        self.styleChanged = Signal(self)
        # Style and palette are renderer-neutral policy objects. They are lazy
        # imports here to keep QtCore-style module resolution backend-light.
        from ..gui.style import QStyleFactory
        from ..gui.palette import QPalette
        self._style = QStyleFactory.create("Fusion")
        self._palette = QPalette.fusion()
        self._focus_widget = None
        # QGuiApplication distinguishes the QObject receiving key/input events
        # from QWidget focus bookkeeping.  Most DearUIQt widgets make these the
        # same object, but optimized/native host surfaces can participate in
        # application input through a lightweight QObject adapter without
        # pretending to be a QWidget.
        self._focus_object = None
        self._active_window = None
        # Qt keeps popup/modal activation as application state rather than in
        # each widget implementation. Store guarded pointers so opening a menu
        # or modal never keeps a deleted top-level alive.
        self._popup_stack = []
        self._modal_stack = []
        # One native keyboard bridge per QApplication replaces the many global
        # handler registries historically installed by individual widgets.
        # The backend remains optional so QtCore-style imports stay lightweight.
        self._input_backend = None
        self._input_handler_registry = None
        self._input_keys = ()
        self._pointer_bridge_installed = False
        self._pointer_targets = []
        self._mouse_grabber = None
        self._hover_pointer_target = None
        self._native_mouse_buttons_state = Qt.NoButton
        # Buttons owned by an implicit Qt grab. A lost OS mouse-up must not
        # route the next independent press to the previous widget.
        self._implicit_grab_buttons = Qt.NoButton
        self._posted = OrderedDict()
        self._posted_lock = threading.Lock()
        # QWidget native configuration is retained until the end of the same
        # QApplication turn.  Keeping it beside posted events lets geometry,
        # visibility and enabled-state bursts share one scheduler wake-up with
        # the LayoutRequest they usually generate.
        self._native_updates = OrderedDict()
        self._posted_scheduled = False
        self._processing_turn = False
        # Deleting a large QObject/QWidget subtree used to make every child
        # independently scan the posted-event/native-update queues. Dialogs or
        # tables with thousands of controls could therefore turn teardown into
        # near O(N^2) bookkeeping before the renderer even released native
        # resources. Keep deletion as an application transaction: the first
        # object in a tree purges application state once, descendants are then
        # covered by that root until recursive QObject disposal completes.
        # A stack supports re-entrant deletion of an unrelated tree from a
        # destroyed/cleanup callback without weakening the subtree fast path.
        self._deletion_roots = []
        # Keep one posted-event turn bounded so a layout/delete storm cannot
        # monopolize the Dear ImGui render thread. Qt naturally interleaves its
        # posted events with native event processing; use the same cooperative
        # budget in this wrapper.
        self._posted_event_budget = 128
        self._native_update_budget = 256
        self._quitting = False

    @classmethod
    def instance(cls):
        current = cls._instance
        return None if current is not None and current._deleted else current

    def style(self):
        return self._style

    def setStyle(self, style):
        from ..gui.style import QStyle, QStyleFactory
        if isinstance(style, str):
            style = QStyleFactory.create(style)
            if style is None:
                raise ValueError("unknown style")
        if not isinstance(style, QStyle):
            raise TypeError("style must be QStyle or a registered style name")
        previous = self._style
        if previous is style:
            return style
        if previous is not None:
            previous.unpolish(self)
        self._style = style
        style.polish(self)
        self.styleChanged.emit(style)
        # Existing widgets inherit application style unless they have an
        # explicit override. Deliver retained events without native polling.
        for child in tuple(getattr(self, "_children", ())):
            try:
                child.sendEvent(QEvent(QEvent.StyleChange, style=style))
            except Exception:
                pass
        return style

    def palette(self):
        return self._palette.copy()

    def setPalette(self, palette):
        from ..gui.palette import QPalette
        if not isinstance(palette, QPalette):
            raise TypeError("palette must be QPalette")
        palette = palette.copy()
        if palette == self._palette:
            return
        self._palette = palette
        self.paletteChanged.emit(palette.copy())
        for child in tuple(getattr(self, "_children", ())):
            try:
                child.sendEvent(QEvent(QEvent.ApplicationPaletteChange, palette=palette.copy()))
            except Exception:
                pass

    def sendEvent(self, receiver_or_event, event=None):
        """Deliver an event in both Qt static and QObject instance forms.

        ``QApplication.sendEvent(receiver, event)`` remains supported, while an
        application that is itself a QObject parent can also receive
        ``app.sendEvent(event)`` during ChildAdded/ChildRemoved notifications.
        """
        if isinstance(self, QApplication):
            if event is None:
                receiver = self
                event = receiver_or_event
            else:
                receiver = receiver_or_event
            application = self
        else:
            # Compatibility with the historical static spelling when invoked
            # on the class: QApplication.sendEvent(receiver, event).
            receiver = self
            event = receiver_or_event
            application = QApplication.instance()
        if not isinstance(receiver, QObject):
            raise TypeError("receiver must be QObject")
        if not isinstance(event, QEvent):
            raise TypeError("event must be QEvent")
        if application is not None and application.threadId() == receiver.threadId():
            return application.notify(receiver, event)
        return QObject.sendEvent(receiver, event)

    def notify(self, receiver, event):
        """Deliver one event through the application dispatcher.

        Keeping the hook at QApplication level mirrors Qt's notify() contract and
        gives the wrapper one place for future tracing/input policy without adding
        per-widget workers or callback layers.
        """
        if not isinstance(receiver, QObject):
            raise TypeError("receiver must be QObject")
        if not isinstance(event, QEvent):
            raise TypeError("event must be QEvent")
        if receiver._deleted:
            return False
        # In Qt, an event filter installed on QApplication observes events for
        # every QObject in the GUI thread. Keep this centralized here instead of
        # adding global callback plumbing to each widget/dialog implementation.
        if receiver is not self:
            for filter_object in reversed(tuple(self._event_filters)):
                if filter_object._deleted:
                    self.removeEventFilter(filter_object)
                    continue
                if bool(filter_object.eventFilter(receiver, event)):
                    return True
        return receiver._send_event_local(event)

    _DEFAULT_INPUT_KEY_NAMES = (
        "mvKey_Escape", "mvKey_Return", "mvKey_Enter", "mvKey_NumPadEnter",
        "mvKey_Tab", "mvKey_Up", "mvKey_Down", "mvKey_Left", "mvKey_Right",
        "mvKey_Home", "mvKey_End", "mvKey_Prior", "mvKey_Next",
        "mvKey_PageUp", "mvKey_PageDown", "mvKey_Spacebar", "mvKey_Space",
        "mvKey_Delete", "mvKey_A", "mvKey_C", "mvKey_X", "mvKey_V",
        "mvKey_R", "mvKey_F2", "mvKey_F4", "mvKey_F5", "mvKey_F7",
    )

    @staticmethod
    def _native_modifier_state(backend):
        modifiers = Qt.NoModifier
        groups = (
            (Qt.ShiftModifier, ("mvKey_LShift", "mvKey_RShift")),
            (Qt.ControlModifier, ("mvKey_LControl", "mvKey_RControl")),
            (Qt.AltModifier, ("mvKey_LAlt", "mvKey_RAlt")),
            (Qt.MetaModifier, ("mvKey_LWin", "mvKey_RWin")),
        )
        for flag, names in groups:
            for name in names:
                key = getattr(backend, name, None)
                if key is None:
                    continue
                try:
                    if backend.is_key_down(key):
                        modifiers |= flag
                        break
                except Exception:
                    continue
        return modifiers

    _NATIVE_MOUSE_BUTTON_NAMES = (
        ("mvMouseButton_Left", Qt.LeftButton),
        ("mvMouseButton_Right", Qt.RightButton),
        ("mvMouseButton_Middle", Qt.MiddleButton),
    )

    @classmethod
    def _native_mouse_button_pairs(cls, backend):
        pairs = []
        for name, qt_button in cls._NATIVE_MOUSE_BUTTON_NAMES:
            native = getattr(backend, name, None)
            if native is not None:
                pairs.append((native, qt_button))
        return tuple(pairs)

    @staticmethod
    def _native_mouse_position(backend):
        try:
            return tuple(map(float, backend.get_mouse_pos(local=False)))
        except Exception:
            try:
                return tuple(map(float, backend.get_mouse_pos()))
            except Exception:
                return (0.0, 0.0)

    def _native_mouse_buttons(self, backend):
        state = Qt.NoButton
        checker = getattr(backend, "is_mouse_button_down", None)
        if checker is not None:
            for native, qt_button in self._native_mouse_button_pairs(backend):
                try:
                    if checker(native):
                        state |= qt_button
                except Exception:
                    pass
        if state == Qt.NoButton:
            state = int(self._native_mouse_buttons_state)
        return state

    def installInputBackend(self, backend, key_names=None):
        """Install one DearPyGui-style keyboard source for the application.

        Native key callbacks are translated into QKeyEvent and routed through
        QApplication.  Repeated calls for the same backend are idempotent.
        Backends without handler-registry support simply return ``False``.
        The host must create its native context before calling this method;
        real Dear PyGui may terminate the process rather than raise if a
        handler registry is allocated before create_context().
        """
        if backend is None or self._deleted:
            return False
        if (self._input_backend is backend and self._input_handler_registry is not None):
            try:
                if backend.does_item_exist(self._input_handler_registry):
                    return True
            except Exception:
                pass
        self.removeInputBackend()
        names = tuple(key_names or self._DEFAULT_INPUT_KEY_NAMES)
        keys = []
        seen = set()
        for name in names:
            key = getattr(backend, name, None)
            if key is None or key in seen:
                continue
            seen.add(key)
            keys.append(key)
        pointer_pairs = self._native_mouse_button_pairs(backend)
        has_pointer_press = callable(getattr(backend, "add_mouse_click_handler", None))
        has_pointer_release = callable(getattr(backend, "add_mouse_release_handler", None))
        has_pointer_move = callable(getattr(backend, "add_mouse_move_handler", None))
        has_pointer_drag = callable(getattr(backend, "add_mouse_drag_handler", None))
        pointer_bridge = bool(
            pointer_pairs and has_pointer_press and has_pointer_release
            and (has_pointer_move or has_pointer_drag)
        )
        if not keys and not pointer_bridge:
            return False
        try:
            with backend.handler_registry() as registry:
                for key in keys:
                    backend.add_key_press_handler(
                        key=key, callback=self._native_key_pressed, user_data=key)
                if pointer_bridge:
                    for native_button, qt_button in pointer_pairs:
                        backend.add_mouse_click_handler(
                            button=native_button, callback=self._native_pointer_pressed,
                            user_data=qt_button)
                        backend.add_mouse_release_handler(
                            button=native_button, callback=self._native_pointer_released,
                            user_data=qt_button)
                    if has_pointer_move:
                        backend.add_mouse_move_handler(callback=self._native_pointer_moved)
                    elif has_pointer_drag:
                        left_native = next((native for native, qt_button in pointer_pairs
                                            if qt_button == Qt.LeftButton), None)
                        if left_native is not None:
                            backend.add_mouse_drag_handler(
                                button=left_native, threshold=0.0,
                                callback=self._native_pointer_moved)
            self._input_backend = backend
            self._input_handler_registry = registry
            self._input_keys = tuple(keys)
            self._pointer_bridge_installed = pointer_bridge
            return True
        except Exception:
            self._input_backend = None
            self._input_handler_registry = None
            self._input_keys = ()
            self._pointer_bridge_installed = False
            return False

    def removeInputBackend(self):
        backend = self._input_backend
        registry = self._input_handler_registry
        self._input_backend = None
        self._input_handler_registry = None
        self._input_keys = ()
        self._pointer_bridge_installed = False
        self._native_mouse_buttons_state = Qt.NoButton
        self._implicit_grab_buttons = Qt.NoButton
        self.releaseMouseGrabberObject()
        if backend is None or registry is None:
            return False
        try:
            if backend.does_item_exist(registry):
                backend.delete_item(registry)
            return True
        except Exception:
            return False

    def inputBackend(self):
        """Return the live native input backend owned by this application."""
        backend = self._input_backend
        registry = self._input_handler_registry
        if backend is None or registry is None:
            return None
        try:
            if not backend.does_item_exist(registry):
                return None
        except Exception:
            # Backend-light test doubles may not expose native item lifetime;
            # the retained registration is still authoritative in that case.
            pass
        return backend

    def _query_backend(self):
        backend = self.inputBackend()
        if backend is not None:
            return backend
        try:
            from ..backends import get_backend
            return get_backend()
        except Exception:
            return None

    def clipboard(self):
        """Return a QClipboard facade bound to the active GUI backend."""
        from ..gui.system import QClipboard
        return QClipboard(backend=self._query_backend())

    def primaryScreen(self):
        """Return the retained renderer's primary viewport as a QScreen."""
        from ..gui.system import QScreen
        return QScreen(backend=self._query_backend())

    def keyboardModifiers(self):
        backend = self._query_backend()
        return Qt.NoModifier if backend is None else self._native_modifier_state(backend)

    def mouseButtons(self):
        backend = self._query_backend()
        return Qt.NoButton if backend is None else self._native_mouse_buttons(backend)

    def frameCount(self):
        backend = self._query_backend()
        getter = getattr(backend, "get_frame_count", None) if backend is not None else None
        if not callable(getter):
            return 0
        try:
            return max(0, int(getter()))
        except Exception:
            return 0

    def hasInputBackend(self, backend=None):
        current = self.inputBackend()
        return current is not None and (backend is None or current is backend)

    def hasPointerInputBackend(self, backend=None):
        current = self.inputBackend()
        return bool(
            self._pointer_bridge_installed and current is not None
            and (backend is None or current is backend)
        )

    @staticmethod
    def _compact_pointer_targets(targets):
        live = []
        seen = set()
        for pointer in targets:
            target = pointer.data() if isinstance(pointer, QPointer) else None
            if target is None or id(target) in seen:
                continue
            seen.add(id(target))
            live.append(pointer)
        if len(live) != len(targets):
            targets[:] = live
        return live

    def registerPointerTarget(self, target):
        if not isinstance(target, QObject):
            raise TypeError("pointer target must be QObject")
        if target._deleted:
            return False
        if target.threadId() != self.threadId():
            raise RuntimeError("pointer target must belong to QApplication thread")
        self.unregisterPointerTarget(target)
        self._pointer_targets.append(QPointer(target))
        return True

    def unregisterPointerTarget(self, target):
        removed = False
        live = []
        for pointer in self._pointer_targets:
            candidate = pointer.data()
            if candidate is None:
                continue
            if candidate is target:
                removed = True
            else:
                live.append(pointer)
        self._pointer_targets[:] = live
        if self.mouseGrabberObject() is target:
            # Clearing only the QPointer leaves _implicit_grab_buttons latched
            # when a native/modal close eats the corresponding mouse-up.  Use
            # the normal release path so the next independent click is routed.
            self.releaseMouseGrabberObject(target)
        if self.hoverPointerObject() is target:
            self._set_hover_pointer_target(None)
        return removed

    def mouseGrabberObject(self):
        pointer = self._mouse_grabber
        return pointer.data() if isinstance(pointer, QPointer) else None

    def setMouseGrabberObject(self, target):
        if target is None:
            self._mouse_grabber = None
            return True
        if not isinstance(target, QObject):
            raise TypeError("mouse grabber must be QObject")
        if (target._deleted or target.threadId() != self.threadId()
                or not self._pointer_capture_target_is_eligible(target)):
            return False
        self._mouse_grabber = QPointer(target)
        return True

    def releaseMouseGrabberObject(self, target=None):
        current = self.mouseGrabberObject()
        if current is None:
            self._mouse_grabber = None
            self._implicit_grab_buttons = Qt.NoButton
            return False
        if target is not None and current is not target:
            return False
        self._mouse_grabber = None
        self._implicit_grab_buttons = Qt.NoButton
        return True

    def hoverPointerObject(self):
        pointer = self._hover_pointer_target
        return pointer.data() if isinstance(pointer, QPointer) else None

    def _pointer_target_at(self, position):
        grabber = self.mouseGrabberObject()
        if grabber is not None:
            if self._pointer_capture_target_is_eligible(grabber):
                return grabber
            # Retained objects can outlive their native visibility. A stale
            # grab must never make an invisible dialog the permanent pointer
            # receiver for Explorer/ListView.
            self.releaseMouseGrabberObject(grabber)

        popup = self.activePopupWidget()
        while popup is not None and not self._pointer_capture_target_is_eligible(popup):
            self._unregister_popup(popup)
            popup = self.activePopupWidget()
        if popup is not None:
            return popup

        modal = self.activeModalWidget()
        while modal is not None and not self._pointer_capture_target_is_eligible(modal):
            self._unregister_modal(modal)
            modal = self.activeModalWidget()
        if modal is not None:
            return modal
        # Mouse move is a high-frequency path. Avoid allocating a fresh list
        # and set for every pointer event; purge expired QPointers only when
        # one is actually observed. Registration already deduplicates targets.
        stale = False
        for pointer in reversed(self._pointer_targets):
            target = pointer.data()
            if target is None:
                stale = True
                continue
            hit_test = getattr(target, "hitTest", None)
            if not callable(hit_test):
                continue
            try:
                if hit_test(position):
                    if stale:
                        self._compact_pointer_targets(self._pointer_targets)
                    return target
            except Exception:
                continue
        if stale:
            self._compact_pointer_targets(self._pointer_targets)
        return None

    def _set_hover_pointer_target(self, target):
        previous = self.hoverPointerObject()
        if previous is target:
            return False
        if previous is not None:
            self.notify(previous, QEvent(QEvent.Leave))
        self._hover_pointer_target = QPointer(target) if isinstance(target, QObject) else None
        if target is not None and not target._deleted:
            self.notify(target, QEvent(QEvent.Enter))
        return True

    @staticmethod
    def _pointer_capture_target_is_eligible(target):
        """Return whether *target* can own an implicit mouse grab right now.

        QObject lifetime alone is insufficient for retained widgets: hidden
        dialogs intentionally stay alive for fast re-open.  Qt releases mouse
        capture when a widget/top-level becomes hidden, so mirror that rule
        before establishing post-press implicit capture.
        """
        if target is None or getattr(target, "_deleted", False):
            return False
        visible = getattr(target, "isVisible", None)
        if callable(visible):
            try:
                if not bool(visible()):
                    return False
            except Exception:
                return False
        exists = getattr(target, "winfo_exists", None)
        if callable(exists):
            try:
                if not bool(exists()):
                    return False
            except Exception:
                return False
        return True

    def dispatchPointerEvent(self, event):
        """Route one pointer event through popup/modal/hit-test priority.

        A handled press establishes Qt-like implicit mouse capture until the
        final button release, so drags continue to the press owner outside its
        geometry without each view allocating a process-global handler.
        """
        if not isinstance(event, QMouseEvent):
            raise TypeError("event must be QMouseEvent")
        if (event.type() == QEvent.MouseButtonPress and event.button() != Qt.NoButton
                and (self._implicit_grab_buttons & event.button())):
            # A second press of the *same* button cannot happen while that
            # physical button is still held. Its missing release was lost to
            # an OS activation transition, a native window, or a callback.
            # Drop only this stale implicit capture. Chorded presses with a
            # different button still belong to the current drag owner.
            self.releaseMouseGrabberObject()
        target = self._pointer_target_at(event.globalPosition())
        if event.type() == QEvent.MouseMove:
            hover_target = target if self.mouseGrabberObject() is None else self.mouseGrabberObject()
            self._set_hover_pointer_target(hover_target)
        if target is None or getattr(target, "_deleted", False):
            if event.type() == QEvent.MouseMove:
                self._set_hover_pointer_target(None)
            return False
        handled = bool(self.notify(target, event))
        if event.type() == QEvent.MouseButtonPress and handled:
            # A handler may synchronously open *or close* a popup/modal.  The
            # post-callback state is authoritative.  In particular, never
            # restore implicit capture to a retained dialog that hid itself in
            # its OK/Cancel callback; QPointer remains live even though the
            # top-level is no longer an eligible input receiver.
            capture = self.activePopupWidget() or self.activeModalWidget()
            if capture is not None and not self._pointer_capture_target_is_eligible(capture):
                capture = None
            if capture is None:
                current_grabber = self.mouseGrabberObject()
                if self._pointer_capture_target_is_eligible(current_grabber):
                    capture = current_grabber
                elif self._pointer_capture_target_is_eligible(target):
                    capture = target
            if capture is not None and self.setMouseGrabberObject(capture):
                self._implicit_grab_buttons |= event.button()
            else:
                self.releaseMouseGrabberObject()
        elif event.type() == QEvent.MouseButtonRelease:
            self._implicit_grab_buttons &= ~event.button()
            if event.buttons() == Qt.NoButton:
                self.releaseMouseGrabberObject()
                self._set_hover_pointer_target(self._pointer_target_at(event.globalPosition()))
        return handled

    def _legacy_pointer_input_blocked(self):
        try:
            from ..input_gate import native_modal_input_active, popup_input_active
            if native_modal_input_active():
                return True
            if popup_input_active() and self.activePopupWidget() is None:
                return True
        except Exception:
            pass
        if self.activeModalWidget() is None and self.activePopupWidget() is None:
            try:
                from ..modal import MODAL_TAGS, visible_modal_window_exists
                if MODAL_TAGS and visible_modal_window_exists():
                    return True
            except Exception:
                pass
        return False

    def _native_pointer_event(self, event_type, button=Qt.NoButton):
        backend = self._input_backend
        if (backend is None or self._deleted or self._quitting
                or not self._pointer_bridge_installed):
            return False
        # Preserve an already accepted drag so a modal opened by the release
        # callback cannot swallow the final release and leave capture stuck.
        if self.mouseGrabberObject() is None and self._legacy_pointer_input_blocked():
            return False
        position = self._native_mouse_position(backend)
        buttons = self._native_mouse_buttons(backend)
        if event_type == QEvent.MouseButtonPress:
            buttons |= int(button)
        elif event_type == QEvent.MouseButtonRelease:
            buttons &= ~int(button)
        event = QMouseEvent(
            event_type, position, button=button, buttons=buttons,
            modifiers=self._native_modifier_state(backend))
        return self.dispatchPointerEvent(event)

    def _native_pointer_pressed(self, sender=None, app_data=None, user_data=None):
        button = int(user_data or Qt.NoButton)
        self._native_mouse_buttons_state |= button
        self.userActivity.emit("pointer-press")
        return self._native_pointer_event(QEvent.MouseButtonPress, button)

    def _native_pointer_released(self, sender=None, app_data=None, user_data=None):
        button = int(user_data or Qt.NoButton)
        self._native_mouse_buttons_state &= ~button
        self.userActivity.emit("pointer-release")
        return self._native_pointer_event(QEvent.MouseButtonRelease, button)

    def _native_pointer_moved(self, sender=None, app_data=None, user_data=None):
        self.userActivity.emit("pointer-move")
        return self._native_pointer_event(QEvent.MouseMove, Qt.NoButton)

    def _native_key_pressed(self, sender=None, app_data=None, user_data=None):
        backend = self._input_backend
        if backend is None or self._deleted or self._quitting:
            return False
        self.userActivity.emit("key-press")
        # Native/process-hosted modals and legacy Explorer popups still own
        # their established input path. Do not let the shared bridge route the
        # same physical key into a retained widget behind those surfaces.
        try:
            from ..input_gate import native_modal_input_active, popup_input_active
            if native_modal_input_active():
                return False
            if popup_input_active() and self.activePopupWidget() is None:
                return False
        except Exception:
            pass
        if self.activeModalWidget() is None and self.activePopupWidget() is None:
            try:
                # Deferred visual destruction can leave a hidden tag in the
                # registry for one UI turn. Only an actually visible modal may
                # block application keyboard routing.
                from ..modal import MODAL_TAGS, visible_modal_window_exists
                if MODAL_TAGS and visible_modal_window_exists():
                    return False
            except Exception:
                pass
        event = QKeyEvent(
            QEvent.KeyPress, user_data, self._native_modifier_state(backend))
        return self.dispatchKeyEvent(event)

    def _key_event_chain(self):
        """Return the Qt priority chain for one application key event.

        A popup is exclusive, then a modal is exclusive.  Otherwise keyboard
        delivery starts at the focus object and bubbles through QObject parents
        until the active top-level is reached.
        """
        popup = self.activePopupWidget()
        if popup is not None:
            return [popup]
        modal = self.activeModalWidget()
        if modal is not None:
            return [modal]
        start = self.focusObject() or self.focusWidget() or self.activeWindow()
        if start is None:
            return []
        chain = []
        current = start
        seen = set()
        while isinstance(current, QObject) and id(current) not in seen:
            seen.add(id(current))
            chain.append(current)
            current = getattr(current, "parent", None)
        active = self.activeWindow()
        if isinstance(active, QObject) and active not in chain:
            chain.append(active)
        return chain

    def dispatchKeyEvent(self, event):
        """Synchronously route QKeyEvent using Qt-like popup/modal priority."""
        if not isinstance(event, QKeyEvent):
            raise TypeError("event must be QKeyEvent")
        if event.type() not in (QEvent.KeyPress, QEvent.KeyRelease, QEvent.ShortcutOverride):
            raise ValueError("not a keyboard event")
        chain = self._key_event_chain()
        for receiver in chain:
            if receiver._deleted:
                continue
            if self.notify(receiver, event):
                return True
        return False

    def postEvent(self, receiver, event):
        """Post an event for the next UI turn, compressing safe event types.

        Qt compresses layout/update traffic heavily.  We do the same for
        LayoutRequest and duplicate DeferredDelete events while preserving FIFO identity
        for ordinary events.  One scheduler wake-up drains the whole turn.
        """
        if self._deleted or self._quitting or receiver._deleted:
            return False
        if receiver.threadId() != self.threadId():
            raise RuntimeError("posted receiver must belong to QApplication thread")
        if self._after is None:
            raise RuntimeError("QApplication.postEvent requires a UI scheduler")
        event_type = event.type()
        compress = event_type in (QEvent.LayoutRequest, QEvent.DeferredDelete)
        key = (id(receiver), event_type) if compress else object()
        with self._posted_lock:
            absorbed = False
            if event_type == QEvent.LayoutRequest:
                # LayoutRequest has a stable receiver/type key, so the common
                # duplicate case is O(1). For hierarchy compression, walk only
                # the receiver's ancestors and descendants instead of scanning
                # every unrelated pending event. This keeps a wide widget tree
                # (many sibling controls invalidating together) near O(N).
                if key in self._posted:
                    self._posted[key] = (receiver, event)
                    absorbed = True
                else:
                    ancestor = getattr(receiver, "parent", None)
                    while ancestor is not None:
                        ancestor_key = (id(ancestor), QEvent.LayoutRequest)
                        if ancestor_key in self._posted:
                            absorbed = True
                            break
                        ancestor = getattr(ancestor, "parent", None)
                    if not absorbed:
                        stack = list(getattr(receiver, "_children", ()))
                        while stack:
                            descendant = stack.pop()
                            descendant_key = (id(descendant), QEvent.LayoutRequest)
                            self._posted.pop(descendant_key, None)
                            stack.extend(getattr(descendant, "_children", ()))
            if not absorbed:
                self._posted[key] = (receiver, event)
            schedule = not self._posted_scheduled and not self._processing_turn
            if schedule:
                self._posted_scheduled = True
        if schedule:
            try:
                self._after(0, self._process_posted_turn)
            except Exception:
                with self._posted_lock:
                    self._posted_scheduled = False
                    self._posted.clear()
                raise
        return True

    def _process_posted_turn(self):
        if self._deleted or self._quitting:
            return 0
        return self.processEvents(max_events=self._posted_event_budget)

    def queueNativeUpdate(self, widget, values):
        """Merge one QWidget native configuration into the current UI turn.

        QWidget setters update their retained Qt state synchronously.  The Dear
        PyGui mutation is a paint/backend detail and may therefore be compressed
        until control returns to the event loop, just like Qt batches update and
        geometry traffic before repaint.
        """
        if (self._deleted or self._quitting or getattr(widget, "_deleted", False)
                or not values or self._after is None):
            return False
        if widget.threadId() != self.threadId():
            raise RuntimeError("native update receiver must belong to QApplication thread")
        with self._posted_lock:
            pending = self._native_updates.setdefault(widget, {})
            pending.update(values)
            schedule = not self._posted_scheduled and not self._processing_turn
            if schedule:
                self._posted_scheduled = True
        if schedule:
            try:
                self._after(0, self._process_posted_turn)
            except Exception:
                with self._posted_lock:
                    self._posted_scheduled = False
                    self._native_updates.pop(widget, None)
                raise
        return True

    def removeNativeUpdates(self, widget, *, subtree=False):
        """Discard deferred native mutations for a widget or ownership subtree."""
        if widget is None:
            return 0
        removed = 0
        with self._posted_lock:
            for candidate in tuple(self._native_updates):
                if candidate is widget or (subtree and self._is_descendant(candidate, widget)):
                    self._native_updates.pop(candidate, None)
                    removed += 1
        return removed

    def _take_native_updates(self, max_widgets=None, only_widget=None):
        """Detach only the native updates that fit in this application turn.

        ``OrderedDict.popitem(last=False)`` keeps the unprocessed tail in place.
        The previous implementation copied the whole transaction to a list and
        then sliced it, which made a bounded 256-widget flush allocate O(N) for
        an arbitrarily large pending queue. Keeping the tail resident also
        preserves insertion order for writes posted re-entrantly during flush.
        """
        with self._posted_lock:
            if only_widget is not None:
                values = self._native_updates.pop(only_widget, None)
                return [] if not values else [(only_widget, values)]
            if max_widgets is None:
                limit = len(self._native_updates)
            else:
                limit = min(len(self._native_updates), max(0, int(max_widgets)))
            items = []
            for _ in range(limit):
                items.append(self._native_updates.popitem(last=False))
            return items

    def flushNativeUpdates(self, widget=None, max_widgets=None):
        """Commit retained QWidget configuration on the GUI thread.

        ``widget`` is an optional synchronization point used before native focus
        operations.  Ordinary callers should let QApplication flush the whole
        transaction automatically at the end of the event-loop turn.
        """
        if threading.get_ident() != self.threadId():
            raise RuntimeError("flushNativeUpdates requires QApplication thread")
        work = self._take_native_updates(max_widgets=max_widgets, only_widget=widget)
        error = None
        committed = 0
        for target, values in work:
            if getattr(target, "_deleted", False):
                continue
            try:
                commit = getattr(target, "_commit_native_config", None)
                if callable(commit) and commit(values):
                    committed += 1
            except Exception as exc:
                # One stale/reparented native item must not prevent unrelated
                # widgets in the same Qt-style transaction from being committed.
                if error is None:
                    error = exc
        if error is not None:
            raise error
        return committed

    def processEvents(self, max_events=None):
        """Deliver one Qt-style UI turn and commit native widget mutations.

        Posted events are delivered first so layout activation may add/replace
        geometry in the same native transaction. The transaction is then
        flushed once before the render loop regains control.

        A bounded turn drains only its ready prefix from the ordered queue. The
        unprocessed tail remains in-place with its original compression keys,
        avoiding the full-queue copy/reinsert cycle that used to scale with all
        pending events even when this turn could deliver only 128 of them.
        """
        if threading.get_ident() != self.threadId():
            raise RuntimeError("processEvents requires QApplication thread")
        # A native callback may synchronously invoke processEvents while an
        # outer event turn is delivering its ready prefix. Re-entering used to
        # clear _processing_turn prematurely and schedule multiple drain turns.
        # Preserve FIFO by leaving newly posted events to the outer turn.
        if self._processing_turn:
            return 0
        with self._posted_lock:
            self._posted_scheduled = False
            self._processing_turn = True
            if max_events is None:
                limit = len(self._posted)
            else:
                limit = min(len(self._posted), max(0, int(max_events)))
            ready = []
            for _ in range(limit):
                _key, payload = self._posted.popitem(last=False)
                ready.append(payload)

        error = None
        try:
            for receiver, event in ready:
                if not receiver._deleted:
                    try:
                        self.notify(receiver, event)
                    except Exception as exc:
                        if error is None:
                            error = exc
            # Layout handlers above may have queued geometry writes. Commit all
            # currently-ready widgets in one backend phase before yielding.
            try:
                self.flushNativeUpdates(max_widgets=self._native_update_budget)
            except Exception as exc:
                if error is None:
                    error = exc
        finally:
            schedule = False
            with self._posted_lock:
                self._processing_turn = False
                if ((self._posted or self._native_updates) and
                        not self._posted_scheduled and not self._quitting):
                    self._posted_scheduled = True
                    schedule = True
            if schedule:
                try:
                    self._after(0, self._process_posted_turn)
                except Exception:
                    with self._posted_lock:
                        self._posted_scheduled = False
                    raise
        if error is not None:
            raise error
        return len(ready)

    def removePostedEvents(self, receiver, event_type=None):
        """Drop queued events for a receiver, matching QCoreApplication cleanup.

        Deleted/hidden-heavy widgets should not keep stale event objects alive until
        the next scheduler turn.  This also prevents a burst of obsolete layout work
        from running after a retained dialog has already changed state.
        """
        if receiver is None:
            return 0
        event_type = None if event_type is None else int(event_type)
        removed = 0
        with self._posted_lock:
            for key, (candidate, event) in tuple(self._posted.items()):
                if candidate is receiver and (event_type is None or event.type() == event_type):
                    self._posted.pop(key, None)
                    removed += 1
        return removed

    def _deletion_cleanup_covered(self, obj):
        """Return whether an active delete transaction already covers *obj*."""
        if obj is None:
            return False
        return any(self._is_descendant(obj, root) for root in self._deletion_roots)

    def _purge_object_subtree_state(self, root):
        """Drop QApplication references for one QObject ownership subtree.

        This is intentionally one pass over each application-owned queue.  It
        replaces the historical per-child ``removePostedEvents`` and
        ``removeNativeUpdates(..., subtree=True)`` scans performed during
        recursive QObject deletion.
        """
        if root is None:
            return 0
        removed = 0
        with self._posted_lock:
            for key, (candidate, _event) in tuple(self._posted.items()):
                if self._is_descendant(candidate, root):
                    self._posted.pop(key, None)
                    removed += 1
            for candidate in tuple(self._native_updates):
                if self._is_descendant(candidate, root):
                    self._native_updates.pop(candidate, None)
                    removed += 1

        self._unregister_stack_widget(self._popup_stack, root, subtree=True)
        self._unregister_stack_widget(self._modal_stack, root, subtree=True)

        live_targets = []
        for pointer in self._pointer_targets:
            target = pointer.data()
            if target is None:
                continue
            if self._is_descendant(target, root):
                removed += 1
            else:
                live_targets.append(pointer)
        self._pointer_targets[:] = live_targets

        grabber = self.mouseGrabberObject()
        if grabber is not None and self._is_descendant(grabber, root):
            # A dialog can delete itself from its Cancel/Close callback before
            # the platform delivers the matching mouse-up.  Releasing through
            # the public path also clears _implicit_grab_buttons, preventing an
            # invisible dialog from owning every later ListView/button press.
            self.releaseMouseGrabberObject(grabber)
        hover = self.hoverPointerObject()
        if hover is not None and self._is_descendant(hover, root):
            self._set_hover_pointer_target(None)

        focus = self.focusObject()
        if focus is not None and self._is_descendant(focus, root):
            if focus is self.focusWidget():
                self._set_focus_widget(None)
            else:
                self.clearFocusObject(focus)
        active = self.activeWindow()
        if active is not None and self._is_descendant(active, root):
            self._set_active_window(None)
        return removed

    def _begin_object_tree_delete(self, root):
        """Begin one recursive QObject deletion transaction.

        Returns ``True`` only for the object that owns the newly-created
        transaction. Descendant ``delete()`` calls return ``False`` and skip
        all application queue scans.
        """
        if root is None or self._deleted:
            return False
        if self._deletion_cleanup_covered(root):
            return False
        self._deletion_roots.append(root)
        self._purge_object_subtree_state(root)
        return True

    def _end_object_tree_delete(self, root):
        """Finish a transaction started by :meth:`_begin_object_tree_delete`."""
        for index in range(len(self._deletion_roots) - 1, -1, -1):
            if self._deletion_roots[index] is root:
                self._deletion_roots.pop(index)
                return True
        return False

    @staticmethod
    def _is_descendant(widget, ancestor):
        current = widget
        while current is not None:
            if current is ancestor:
                return True
            current = getattr(current, "parent", None)
        return False

    def _widget_hidden(self, widget):
        # Qt does not spend a hidden subtree's next event-loop turn relaying
        # geometry that cannot affect visible pixels. Drop queued layout work
        # for the subtree; dirty layouts remain retained and activate on show.
        removed_layout = 0
        with self._posted_lock:
            for key, (candidate, event) in tuple(self._posted.items()):
                if (event.type() == QEvent.LayoutRequest and
                        self._is_descendant(candidate, widget)):
                    self._posted.pop(key, None)
                    removed_layout += 1
        if removed_layout and hasattr(widget, "_retained_layout_dirty"):
            widget._retained_layout_dirty = True

        # QWidget::hide() implicitly releases mouse/hover ownership for the
        # hidden subtree.  This is critical for retained QDialogs: an OK/Cancel
        # press may hide the dialog synchronously while QApplication is still
        # dispatching that same physical press.  Leaving the implicit grab on a
        # live-but-hidden dialog makes every later Explorer/ListView event route
        # back into the invisible top-level.
        grabber = self.mouseGrabberObject()
        if grabber is not None and self._is_descendant(grabber, widget):
            self.releaseMouseGrabberObject(grabber)
        hover = self.hoverPointerObject()
        if hover is not None and self._is_descendant(hover, widget):
            self._set_hover_pointer_target(None)

        focus = self.focusObject()
        if focus is not None and self._is_descendant(focus, widget):
            if focus is self.focusWidget():
                self._set_focus_widget(None)
            else:
                self.clearFocusObject(focus)
        active = self.activeWindow()
        if active is not None and self._is_descendant(active, widget):
            self._set_active_window(None)

    def focusWidget(self):
        widget = self._focus_widget
        return None if widget is not None and widget._deleted else widget

    def focusObject(self):
        """Return the QObject currently receiving application input events.

        This mirrors ``QGuiApplication.focusObject()``.  QWidget focus normally
        makes ``focusObject()`` and ``focusWidget()`` identical, while a
        ``QInputTarget`` can own keyboard routing for an optimized/native
        surface that is intentionally not implemented as a QWidget.
        """
        target = self._focus_object
        return None if target is not None and target._deleted else target

    def activeWindow(self):
        window = self._active_window
        return None if window is not None and window._deleted else window

    @staticmethod
    def _compact_widget_stack(stack):
        live = []
        for pointer in stack:
            widget = pointer.data() if isinstance(pointer, QPointer) else None
            if widget is not None:
                live.append(pointer)
        if len(live) != len(stack):
            stack[:] = live
        return live

    @classmethod
    def _stack_active_widget(cls, stack):
        live = cls._compact_widget_stack(stack)
        return live[-1].data() if live else None

    @classmethod
    def _register_stack_widget(cls, stack, widget):
        if widget is None or getattr(widget, "_deleted", False):
            return False
        cls._compact_widget_stack(stack)
        stack[:] = [pointer for pointer in stack if pointer.data() is not widget]
        stack.append(QPointer(widget))
        return True

    @classmethod
    def _unregister_stack_widget(cls, stack, widget, *, subtree=False):
        removed = False
        live = []
        for pointer in stack:
            candidate = pointer.data()
            if candidate is None:
                continue
            matches = candidate is widget
            if not matches and subtree and widget is not None:
                matches = cls._is_descendant(candidate, widget)
            if matches:
                removed = True
            else:
                live.append(pointer)
        stack[:] = live
        return removed

    def activePopupWidget(self):
        """Return the top-most live QMenu-like popup registered with the app."""
        return self._stack_active_widget(self._popup_stack)

    def activeModalWidget(self):
        """Return the top-most live modal QDialog registered with the app."""
        return self._stack_active_widget(self._modal_stack)

    def _register_popup(self, widget):
        """Register *widget* as the exclusive popup pointer target.

        Qt popup windows take application-level mouse ownership without laying
        a fullscreen visual surface over the parent window.  Move hover state
        to the popup immediately so a background item cannot retain a stale
        hover highlight while the popup is open.
        """
        registered = self._register_stack_widget(self._popup_stack, widget)
        if registered:
            # Opening a popup supersedes an existing implicit press grab. This
            # matters for context menus opened from a view's press callback: the
            # subsequent move/release must not continue to target that view.
            current = self.mouseGrabberObject()
            if current is not None and current is not widget:
                self.releaseMouseGrabberObject(current)
            self._set_hover_pointer_target(widget)
        return registered

    def _unregister_popup(self, widget):
        removed = self._unregister_stack_widget(self._popup_stack, widget)
        if removed:
            if self.mouseGrabberObject() is widget:
                self.releaseMouseGrabberObject(widget)
            if self.hoverPointerObject() is widget:
                # Do not guess the background hit target without a fresh mouse
                # position. The next native MouseMove will repopulate it.
                self._set_hover_pointer_target(self.activePopupWidget())
        return removed

    def _register_modal(self, widget):
        registered = self._register_stack_widget(self._modal_stack, widget)
        if registered:
            # A modal may open from the owner's mouse callback, before its
            # release arrives. Never let that owner's grab steal the first
            # click on the new dialog. Same rule as QMenu popup activation.
            current = self.mouseGrabberObject()
            if current is not None and current is not widget:
                self.releaseMouseGrabberObject(current)
            self._set_hover_pointer_target(widget)
        return registered

    def _unregister_modal(self, widget):
        return self._unregister_stack_widget(self._modal_stack, widget)

    @staticmethod
    def _window_for(widget):
        if widget is None:
            return None
        current = widget
        while current is not None:
            is_window = getattr(current, "isWindow", None)
            if callable(is_window) and is_window():
                return current
            parent = getattr(current, "parent", None)
            if parent is None:
                return current
            current = parent
        return widget

    def _set_active_window(self, window):
        if window is not None and getattr(window, "_deleted", False):
            window = None
        previous = self.activeWindow()
        if previous is window:
            return False
        if previous is not None:
            previous.sendEvent(QEvent(QEvent.WindowDeactivate))
        self._active_window = window
        if window is not None:
            window.sendEvent(QEvent(QEvent.WindowActivate))
        self.activeWindowChanged.emit(window)
        return True

    def canFocusWidget(self, widget):
        """Keep deferred background focus out of a live modal/popup subtree.

        Some retained controls still use a native parent tag rather than a
        QObject parent. Resolve that renderer ancestry as well, before a native
        focus request can cancel the foreground control's first mouse gesture.
        """
        if widget is None or getattr(widget, "_deleted", False):
            return widget is None
        boundary = self.activePopupWidget() or self.activeModalWidget()
        if boundary is None or self._is_descendant(widget, boundary):
            return True
        belongs = getattr(boundary, "_item_belongs_to", None)
        tag, boundary_tag = getattr(widget, "tag", None), getattr(boundary, "tag", None)
        if callable(belongs) and tag is not None and boundary_tag is not None:
            return bool(belongs(tag, boundary_tag))
        return False

    def _set_focus_widget(self, widget):
        if widget is not None and getattr(widget, "_deleted", False):
            widget = None
        if widget is not None and not self.canFocusWidget(widget):
            return False
        previous = self.focusWidget()
        previous_object = self.focusObject()
        if previous is widget and previous_object is widget:
            self._set_active_window(self._window_for(widget))
            return False
        if previous_object is not None and previous_object is not widget:
            previous_object.sendEvent(QEvent(QEvent.FocusOut))
        self._focus_widget = widget
        self._focus_object = widget
        if widget is not None:
            widget.sendEvent(QEvent(QEvent.FocusIn))
        self._set_active_window(self._window_for(widget))
        if previous_object is not widget:
            self.focusObjectChanged.emit(widget)
        if previous is not widget:
            self.focusChanged.emit(previous, widget)
        return True

    def setFocusObject(self, target):
        """Route application input to a non-QWidget QObject focus target.

        The active top-level is deliberately left unchanged.  This is useful
        for retained draw-list/native surfaces whose logical keyboard focus is
        application-owned even though no DearUIQt QWidget owns their pixels.
        """
        if target is not None:
            if not isinstance(target, QObject):
                raise TypeError("focus object must be QObject")
            if target._deleted:
                target = None
            elif target.threadId() != self.threadId():
                raise RuntimeError("focus object must belong to QApplication thread")
        previous_object = self.focusObject()
        if previous_object is target:
            return False
        previous_widget = self.focusWidget()
        if previous_object is not None:
            previous_object.sendEvent(QEvent(QEvent.FocusOut))
        self._focus_object = target
        if previous_widget is not None and previous_widget is not target:
            self._focus_widget = None
            self.focusChanged.emit(previous_widget, None)
        if target is not None:
            target.sendEvent(QEvent(QEvent.FocusIn))
        self.focusObjectChanged.emit(target)
        return True

    def clearFocusObject(self, target=None):
        """Clear logical focus if ``target`` currently owns it."""
        current = self.focusObject()
        if target is not None and current is not target:
            return False
        if current is None:
            return False
        if current is self.focusWidget():
            return self._set_focus_widget(None)
        current.sendEvent(QEvent(QEvent.FocusOut))
        self._focus_object = None
        self.focusObjectChanged.emit(None)
        return True

    def _clear_widget(self, widget):
        # Kept as a compatibility hook for callers that explicitly remove a
        # live widget from application routing without deleting it. Recursive
        # QObject.delete() now uses the transaction API above.
        return self._purge_object_subtree_state(widget)

    def quit(self):
        if self._quitting:
            return
        self._quitting = True
        self.aboutToQuit.emit()
        with self._posted_lock:
            self._posted.clear()
            self._native_updates.clear()
        self._popup_stack.clear()
        self._modal_stack.clear()
        self._pointer_targets.clear()
        self._mouse_grabber = None
        self._hover_pointer_target = None
        self._deletion_roots.clear()
        self.removeInputBackend()

    def delete(self):
        if self._deleted:
            return
        self.quit()
        try:
            super().delete()
        finally:
            with self._instance_lock:
                if type(self)._instance is self:
                    type(self)._instance = None


QCoreApplication = QApplication


__all__ = ["QApplication", "QCoreApplication"]
