"""Small host/runtime abstractions for standalone Dear PyGui UI surfaces."""
from __future__ import annotations

import heapq
import time
import itertools
import threading
from queue import Queue, Empty

from .core.object import QSize


class StandaloneUiHost:
    """Minimal scheduler expected by the shared retained Dear ImGui wrappers.

    The host deliberately contains no application-specific state.  A feature can
    therefore create its own DearPyGui context/viewport and still reuse the same
    retained controls/dialog wrappers as the main application.
    """

    def __init__(self, backend=None):
        if backend is None:
            from .backends import get_backend
            backend = get_backend()
        self.backend = backend
        self.is_standalone_ui_host = True
        self._queue = []
        self._incoming = Queue()
        self._sequence = itertools.count(1)
        # Heap entries carry only lightweight schedule tokens; callback/args
        # live in a separately cancellable map. ``after_cancel`` can therefore
        # release an obsolete bound-method closure immediately even when its
        # due timestamp is far in the future.
        self._scheduled_callbacks = {}
        self._scheduled_lock = threading.Lock()
        self._floating_focus_suppressed = True
        self._native_hwnd = 0
        self.use_native_file_selectors = False

    def _find_main_viewport_hwnd(self):
        return self._native_hwnd

    def show_error(self, title, message):
        callback = getattr(self, "on_error", None)
        if callable(callback):
            callback("{}: {}".format(title, message))

    def after(self, delay_ms, callback, *args):
        sequence = next(self._sequence)
        due = time.monotonic() + max(0, int(delay_ms or 0)) / 1000.0
        with self._scheduled_lock:
            self._scheduled_callbacks[sequence] = (callback, args)
        self._incoming.put((due, sequence))
        return sequence

    def after_cancel(self, sequence):
        """Cancel a callback immediately, reclaiming stale timer heap nodes.

        QTimer restarts and closing dialogs can cancel many long-running timers.
        Opportunistic compaction avoids retaining those deadline tokens until
        their original due time. The incoming MPSC queue is filtered on pump.
        """
        if sequence is None:
            return False
        with self._scheduled_lock:
            removed = self._scheduled_callbacks.pop(sequence, None) is not None
            if removed and len(self._queue) > max(64, len(self._scheduled_callbacks) * 2 + 32):
                self._queue[:] = [
                    item for item in self._queue
                    if item[1] in self._scheduled_callbacks
                ]
                heapq.heapify(self._queue)
            return removed

    def pump(self, max_callbacks=256, time_budget_ms=8.0):
        """Process one bounded standalone UI turn without starving rendering.

        The old unbounded intake loop could starve rendering when another
        thread flooded the callback queue, and due timer bursts executed in a
        single turn. Keep deadline order, retain the unprocessed tail, and
        continue on the next rendered frame without dropping input events.
        """
        for _ in range(2048):
            try:
                due, sequence = self._incoming.get_nowait()
            except Empty:
                break
            with self._scheduled_lock:
                live = sequence in self._scheduled_callbacks
            if live:
                heapq.heappush(self._queue, (due, sequence))
        start = time.monotonic()
        processed = 0
        limit = max(0, int(max_callbacks)) if max_callbacks is not None else None
        budget = (None if time_budget_ms is None else
                  max(0.0, float(time_budget_ms)) / 1000.0)
        while self._queue and self._queue[0][0] <= time.monotonic():
            if limit is not None and processed >= limit:
                break
            if budget is not None and processed and time.monotonic() - start >= budget:
                break
            _due, sequence = heapq.heappop(self._queue)
            with self._scheduled_lock:
                payload = self._scheduled_callbacks.pop(sequence, None)
            if payload is None:
                continue
            callback, args = payload
            try:
                callback(*args)
            except Exception:
                # One UI callback must not terminate a standalone feature loop.
                pass
            processed += 1
        return processed

    def winfo_exists(self):
        try:
            return bool(self.backend.is_dearpygui_running())
        except Exception:
            return True


class QGuiRuntime:
    """Own one renderer context/viewport lifecycle for a desktop application.

    QApplication intentionally remains a backend-neutral event dispatcher.
    QGuiRuntime is the small renderer-facing host boundary that creates the
    native context, viewport and render frames.  Keeping this lifecycle here
    prevents consuming applications from scattering backend startup/shutdown
    calls through their main-window implementation.
    """

    def __init__(self, backend=None):
        if backend is None:
            from .backends import get_backend
            backend = get_backend()
        self.backend = backend
        self._context_created = False
        self._setup = False
        self._viewport_created = False
        self._visible = False

    def createContext(self, *, manual_callbacks=True):
        if self._context_created:
            return False
        self.backend.create_context()
        self._context_created = True
        if manual_callbacks and hasattr(self.backend, "configure_app"):
            self.backend.configure_app(manual_callback_management=True)
        return True

    def configureApplication(self, **options):
        """Configure renderer application options through the runtime boundary."""
        configure = getattr(self.backend, "configure_app", None)
        if not callable(configure):
            return False
        try:
            configure(**options)
            return True
        except Exception:
            return False

    def enableNativeWindows(self):
        """Enable the custom in-process native-window backend before show().

        Explicitly fails with stock Dear PyGui rather than spawning a helper
        process or pretending a viewport-bound ImGui window is an OS window.
        """
        if not self._context_created:
            raise RuntimeError("createContext() must be called before enableNativeWindows()")
        from .backends.native_windows import NativeWindowBackend
        return NativeWindowBackend(self.backend).enable()

    def supportsNativeWindows(self):
        from .backends.native_windows import NativeWindowBackend
        return NativeWindowBackend(self.backend).available()

    def createViewport(self, **options):
        if not self._context_created:
            raise RuntimeError("createContext() must be called before createViewport()")
        self.backend.create_viewport(**options)
        self._viewport_created = True
        return True

    def configureViewport(self, **options):
        """Reconfigure the active top-level viewport.

        Dear PyGui currently identifies the primary viewport with ``0``.  That
        renderer detail stays inside DearUIQt so applications can use a
        QGuiApplication-like lifecycle without importing backend symbols.
        """
        if not self._viewport_created:
            raise RuntimeError("createViewport() must be called before configureViewport()")
        configure = getattr(self.backend, "configure_viewport", None)
        if not callable(configure):
            return False
        configure(0, **options)
        return True

    def viewportSize(self, *, client=False):
        """Return the current viewport size as ``QSize``."""
        prefix = "get_viewport_client_" if client else "get_viewport_"
        width = getattr(self.backend, prefix + "width", None)
        height = getattr(self.backend, prefix + "height", None)
        try:
            w = int(width()) if callable(width) else 0
        except Exception:
            w = 0
        try:
            h = int(height()) if callable(height) else 0
        except Exception:
            h = 0
        return QSize(max(0, w), max(0, h))

    def resizeViewport(self, width, height=None):
        size = width if isinstance(width, QSize) and height is None else QSize(width, height)
        if not self._viewport_created:
            return False
        setter = getattr(self.backend, "set_viewport_width", None)
        if callable(setter):
            setter(int(size.width()))
        setter = getattr(self.backend, "set_viewport_height", None)
        if callable(setter):
            setter(int(size.height()))
        if not callable(getattr(self.backend, "set_viewport_width", None)) or not callable(getattr(self.backend, "set_viewport_height", None)):
            return self.configureViewport(width=int(size.width()), height=int(size.height()))
        return True

    def setViewportHeight(self, height):
        if not self._viewport_created:
            return False
        setter = getattr(self.backend, "set_viewport_height", None)
        if callable(setter):
            setter(int(height))
            return True
        return self.configureViewport(height=int(height))

    def setup(self):
        if not self._context_created:
            raise RuntimeError("createContext() must be called before setup()")
        self.backend.setup_dearpygui()
        self._setup = True
        return True

    def setPrimaryWindow(self, item, primary=True):
        self.backend.set_primary_window(getattr(item, "tag", item), bool(primary))

    def setApplicationTheme(self, theme):
        """Bind one application-wide renderer theme through the runtime boundary."""
        native = theme.nativeId() if hasattr(theme, "nativeId") else theme
        binder = getattr(self.backend, "bind_theme", None)
        if not callable(binder):
            return False
        binder(native)
        self._application_theme = theme
        return True

    def applicationTheme(self):
        return getattr(self, "_application_theme", None)

    def setApplicationFont(self, font):
        """Bind one application-wide font without exposing backend font APIs.

        ``font`` may be a :class:`QFont` or a native id during migration.  The
        runtime deliberately retains the object reference so QObject-owned font
        databases stay alive for as long as the application font is active.
        """
        native = font.nativeId() if hasattr(font, "nativeId") else font
        binder = getattr(self.backend, "bind_font", None)
        if not callable(binder):
            return False
        try:
            binder(native)
        except Exception:
            return False
        self._application_font = font
        return True

    def applicationFont(self):
        return getattr(self, "_application_font", None)

    def setExitCallback(self, callback):
        self.backend.set_exit_callback(callback)

    def setViewportResizeCallback(self, callback):
        self.backend.set_viewport_resize_callback(callback)

    def show(self):
        self.backend.show_viewport()
        self._visible = True
        return True

    def isRunning(self):
        if not self._context_created:
            return False
        try:
            return bool(self.backend.is_dearpygui_running())
        except Exception:
            return False

    def renderFrame(self):
        if not self.isRunning():
            return False
        self.backend.render_dearpygui_frame()
        return True

    def stop(self):
        if not self._context_created:
            return False
        try:
            self.backend.stop_dearpygui()
            return True
        except Exception:
            return False

    def invokeAfterFrames(self, callback, frames=1):
        """Schedule ``callback`` after ``frames`` rendered frames.

        Frame scheduling is a renderer/runtime concern, not an application
        widget concern.  ``frames=1`` is the ordinary next-frame case while a
        small larger offset is useful when visibility/layout settles over more
        than one retained frame (for example focus after showing a toolbar row).
        """
        if not callable(callback):
            raise TypeError("callback must be callable")
        try:
            frames = max(1, int(frames))
        except (TypeError, ValueError, OverflowError):
            frames = 1
        setter = getattr(self.backend, "set_frame_callback", None)
        counter = getattr(self.backend, "get_frame_count", None)
        if not callable(setter):
            return False
        try:
            frame = int(counter()) + frames if callable(counter) else frames
            setter(frame, callback=callback)
            return True
        except TypeError:
            try:
                setter(frame, callback)
                return True
            except Exception:
                return False
        except Exception:
            return False

    def invokeNextFrame(self, callback):
        """Schedule ``callback`` for the next renderer frame."""
        return self.invokeAfterFrames(callback, 1)

    def hasActivePopupSurface(self, *, exclude=None, include_modals=True):
        """Return whether another renderer popup/modal top-level is visible.

        Qt-native DearUIQt popups are tracked by ``QApplication``.  This helper
        additionally covers backend-owned combo/dropdown/modal surfaces during
        migration without leaking renderer window enumeration into applications.
        ``exclude`` is the owning modal widget/tag, so a file selector does
        not classify *itself* as a popup blocking its own mouse events.
        With ``include_modals=False``, only actual popup overlays count:
        an owner/parent modal behind a nested file dialog must not block it.
        """
        getter = getattr(self.backend, "get_windows", None)
        config_getter = getattr(self.backend, "get_item_configuration", None)
        shown = getattr(self.backend, "is_item_shown", None)
        if not (callable(getter) and callable(config_getter) and callable(shown)):
            return False
        try:
            windows = tuple(getter() or ())
        except Exception:
            return False
        excluded = getattr(exclude, "tag", exclude)
        for window in windows:
            if excluded is not None and window == excluded:
                continue
            try:
                config = dict(config_getter(window) or {})
                if shown(window) and (config.get("popup") or
                                      (include_modals and config.get("modal"))):
                    return True
            except Exception:
                continue
        return False

    def itemSnapshot(self):
        """Return an immutable snapshot of native item ids owned by the context.

        Reusable dialog hosts use this to distinguish persistent graphics
        resources from resources allocated by a single lease.  Enumeration is
        intentionally kept inside the GUI runtime boundary.
        """
        getter = getattr(self.backend, "get_all_items", None)
        if not callable(getter):
            return frozenset()
        try:
            return frozenset(getter() or ())
        except Exception:
            return frozenset()

    def itemCount(self):
        return len(self.itemSnapshot())

    def releaseTopLevelItemsSince(self, snapshot, *, item_type=None):
        """Delete top-level native items allocated after ``snapshot``.

        ``item_type`` may be supplied for resource cleanup such as per-dialog
        themes.  This lifecycle operation belongs to the renderer host and
        avoids leaking native enumeration/deletion into application code.
        """
        before = set(snapshot or ())
        released = 0
        for item in set(self.itemSnapshot()) - before:
            try:
                if not self.backend.does_item_exist(item):
                    continue
                info = dict(self.backend.get_item_info(item) or {})
                if info.get("parent"):
                    continue
                if item_type is not None and info.get("type") != item_type:
                    continue
                self.backend.delete_item(item)
                released += 1
            except Exception:
                continue
        return released

    def callbackQueue(self):
        getter = getattr(self.backend, "get_callback_queue", None)
        if not callable(getter):
            return ()
        try:
            return tuple(getter() or ())
        except Exception:
            return ()

    def destroy(self):
        if not self._context_created:
            return False
        try:
            if self.isRunning():
                self.stop()
            self.backend.destroy_context()
        finally:
            self._context_created = False
            self._setup = False
            self._viewport_created = False
            self._visible = False
        return True

    def contextCreated(self):
        return bool(self._context_created)

    def viewportCreated(self):
        return bool(self._viewport_created)


__all__ = ["StandaloneUiHost", "QGuiRuntime"]
