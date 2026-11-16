"""Small host/runtime abstractions for standalone Dear PyGui UI surfaces."""
from __future__ import annotations

from .core.object import QSize
from .core.dispatcher import QEventDispatcher
from .core.performance_policy import QPerformancePolicy
import weakref
from collections import deque
import time
import json
import os
import tempfile


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
        self.dispatcher = QEventDispatcher()
        self._floating_focus_suppressed = True
        self._native_hwnd = 0
        self.use_native_file_selectors = False

    def _find_main_viewport_hwnd(self):
        return self._native_hwnd

    def show_error(self, title, message):
        callback = getattr(self, "on_error", None)
        if callable(callback):
            callback("{}: {}".format(title, message))

    def after(self, delay_ms, callback, *args, priority=0):
        return self.dispatcher.after(delay_ms, callback, *args, priority=priority)

    def post(self, callback, *args, priority=0):
        return self.dispatcher.post(callback, *args, priority=priority)

    def after_cancel(self, sequence):
        return self.dispatcher.after_cancel(sequence)

    def next_deadline_ms(self):
        return self.dispatcher.nextDeadlineMs()

    def scheduler_diagnostics(self):
        """Expose dispatcher diagnostics without leaking mutable internals."""
        return self.dispatcher.diagnosticsSnapshot()

    def set_wake_callback(self, callback):
        return self.dispatcher.setWakeCallback(callback)

    def close(self):
        self.dispatcher.close()

    def _callback_error(self, callback, error):
        handler = getattr(self, 'on_callback_error', None)
        if callable(handler):
            handler(callback, error)

    def pump(self, max_callbacks=256, time_budget_ms=8.0):
        """Deliver one bounded UI turn; report errors through an optional hook."""
        return self.dispatcher.processEvents(max_callbacks, time_budget_ms,
                                             on_error=self._callback_error)

    def winfo_exists(self):
        if self.dispatcher.isClosed():
            return False
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

    _before_render_callbacks = {}
    _window_hosts = weakref.WeakKeyDictionary()
    _window_hosts_fallback = {}

    def __init__(self, backend=None):
        if backend is None:
            from .backends import get_backend
            backend = get_backend()
        self.backend = backend
        self._context_created = False
        self._setup = False
        self._viewport_created = False
        self._visible = False
        self._window_host = self._resolve_window_host(self.backend)
        self._frame_stats = {
            "rendered_frames": 0,
            "skipped_frames": 0,
            "schedule_checks": 0,
            "last_skip_reason": None,
            "last_wait_ms": None,
            "dirty_triggered_frames": 0,
            "deadline_triggered_frames": 0,
            "presentation_triggered_frames": 0,
        }
        self._frame_history = deque(maxlen=240)


    @classmethod
    def _resolve_window_host(cls, backend):
        """Return one host per live backend identity without integer-id aliasing."""
        from .gui.window_host import QWindowHost
        try:
            host = cls._window_hosts.get(backend)
            if host is None or getattr(host, "_deleted", False):
                host = QWindowHost(geometry=(0, 0, 0, 0))
                cls._window_hosts[backend] = host
            return host
        except TypeError:
            # Some extension/module backends are not weak-referenceable. Keep a
            # strong identity pair in the fallback so a recycled Python id can
            # never attach a new backend to the previous backend's host.
            key = id(backend)
            pair = cls._window_hosts_fallback.get(key)
            if pair is not None and pair[0] is backend and not getattr(pair[1], "_deleted", False):
                return pair[1]
            host = QWindowHost(geometry=(0, 0, 0, 0))
            cls._window_hosts_fallback[key] = (backend, host)
            return host

    @classmethod
    def _take_window_host(cls, backend):
        try:
            return cls._window_hosts.pop(backend, None)
        except TypeError:
            key = id(backend)
            pair = cls._window_hosts_fallback.get(key)
            if pair is None or pair[0] is not backend:
                return None
            cls._window_hosts_fallback.pop(key, None)
            return pair[1]

    def addBeforeRenderCallback(self, callback, *, late=False):
        """Register short UI-thread work immediately before renderer submission.

        Registrations are shared by wrappers for the same backend/context.
        Bound methods are weak and callbacks are removed at context teardown.
        This is for late cursor/overlay sampling, never I/O or full layouts.
        ``late`` samples pointer overlays after ordinary pre-render updates,
        regardless of registration order.
        """
        import weakref
        if not callable(callback):
            raise TypeError('before-render callback must be callable')
        token = object()
        weak = getattr(callback, '__self__', None) is not None
        try:
            entry = (weakref.WeakMethod(callback), True) if weak else (callback, False)
        except TypeError:
            entry = (callback, False)
        self._before_render_callbacks.setdefault(id(self.backend), {})[token] = (*entry, bool(late))
        return token

    def removeBeforeRenderCallback(self, token):
        callbacks = self._before_render_callbacks.get(id(self.backend))
        if callbacks is None:
            return False
        removed = callbacks.pop(token, None) is not None
        if not callbacks:
            self._before_render_callbacks.pop(id(self.backend), None)
        return removed

    def _run_before_render_callbacks(self):
        callbacks = self._before_render_callbacks.get(id(self.backend))
        if not callbacks:
            return
        # Snapshot both phases together: registrations made by a callback must
        # wait for the next frame, including late registrations.
        tokens = sorted(tuple(callbacks), key=lambda token: callbacks[token][2])
        for token in tokens:
            entry = callbacks.get(token)
            if entry is None:
                continue
            callback, weak, _late = entry
            callback = callback() if weak else callback
            if callback is None or getattr(getattr(callback, '__self__', None), '_deleted', False):
                self.removeBeforeRenderCallback(token)
                continue
            try:
                callback()
            except Exception:
                self.removeBeforeRenderCallback(token)
                import logging
                logging.getLogger(__name__).exception('Before-render callback removed after failure')

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

    def windowHost(self):
        """Return the one retained host shared by this backend/context.

        QGuiRuntime is intentionally cheap to wrap around an existing backend.
        All wrappers must therefore resolve the same QWindowHost instead of
        creating parallel ownership/coordinate state.
        """
        host = self._resolve_window_host(self.backend)
        self._window_host = host
        try:
            from .core.application import QCoreApplication
            application = QCoreApplication.instance()
            if application is not None and host.ownerObject() is None:
                host.setOwnerObject(application)
        except Exception:
            pass
        return host

    def setNativeHandle(self, handle):
        """Publish the platform handle without exposing it to feature widgets."""
        host = self.windowHost()
        host.setNativeHandle(handle)
        return host.nativeHandle()

    def _sync_window_host_geometry(self):
        try:
            width = int(self.backend.get_viewport_client_width())
            height = int(self.backend.get_viewport_client_height())
        except Exception:
            width = height = 0
        try:
            getter = getattr(self.backend, "get_viewport_pos", None)
            x, y = getter() if callable(getter) else (0, 0)
        except Exception:
            x = y = 0
        host = self.windowHost()
        host.setGeometry((x, y, width, height))
        return host.geometry()

    def createViewport(self, **options):
        if not self._context_created:
            raise RuntimeError("createContext() must be called before createViewport()")
        self.backend.create_viewport(**options)
        self._viewport_created = True
        self._sync_window_host_geometry()
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
        self._sync_window_host_geometry()
        return True

    def setViewportTitle(self, title):
        """Update the active viewport caption, including externally owned hosts."""
        setter = getattr(self.backend, "set_viewport_title", None)
        if not callable(setter):
            return False
        try:
            setter(str(title))
            return True
        except Exception:
            return False

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
        self._sync_window_host_geometry()
        return True

    def setViewportHeight(self, height):
        if not self._viewport_created:
            return False
        setter = getattr(self.backend, "set_viewport_height", None)
        if callable(setter):
            setter(int(height))
            self._sync_window_host_geometry()
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
        from .backends.native_windows import NativeWindowBackend
        NativeWindowBackend(self.backend).registerPrimary(item, primary)

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
        self._sync_window_host_geometry()
        return True

    def isRunning(self):
        if not self._context_created:
            return False
        try:
            return bool(self.backend.is_dearpygui_running())
        except Exception:
            return False

    def hasPendingPresentation(self):
        """Whether a native window transition needs the next render promptly."""
        from .backends.native_presentation import presentation_for
        presentation = presentation_for(self.backend)
        return bool(presentation is not None and presentation.needs_frame())

    def frameSchedulingSnapshot(self, dispatcher=None):
        """Return the public state a host needs to decide whether/when to paint.

        The runtime deliberately exposes no private queue/renderer internals.
        Hosts combine the earliest dispatcher deadline with QWindowHost dirty
        state and native presentation state, matching Qt's event-driven idle
        contract instead of polling feature-specific flags.
        """
        self._frame_stats["schedule_checks"] += 1
        deadline = None
        if dispatcher is not None:
            getter = getattr(dispatcher, "nextDeadlineMs", None)
            if not callable(getter):
                raise TypeError("dispatcher must implement QAbstractEventDispatcher.nextDeadlineMs()")
            deadline = getter()
        host = self.windowHost()
        dirty = host.dirtyRegion()
        dirty_tuple = None if dirty is None else (
            dirty.x(), dirty.y(), dirty.width(), dirty.height())
        presentation = self.hasPendingPresentation()
        return {
            "next_deadline_ms": deadline,
            "has_dirty_region": dirty is not None,
            "dirty_region": dirty_tuple,
            "presentation_pending": bool(presentation),
            "immediate_frame": bool(presentation or dirty is not None or
                                    (deadline is not None and deadline <= 0)),
        }

    def nextFrameDelayMs(self, dispatcher=None, default_ms=None):
        """Milliseconds until the runtime needs service; ``None`` means idle.

        Dirty/presentation work is immediate. Otherwise the dispatcher deadline
        is authoritative; ``default_ms`` is only an optional native-wait cap.
        """
        snap = self.frameSchedulingSnapshot(dispatcher)
        if snap["immediate_frame"]:
            return 0.0
        deadline = snap["next_deadline_ms"]
        if deadline is None:
            return None if default_ms is None else max(0.0, float(default_ms))
        if default_ms is None:
            return max(0.0, float(deadline))
        return min(max(0.0, float(deadline)), max(0.0, float(default_ms)))

    def _recordFrameHistory(self, kind, reason=None, wait_ms=None):
        self._frame_history.append((
            time.monotonic(), str(kind), None if reason is None else str(reason),
            None if wait_ms is None else max(0.0, float(wait_ms)),
        ))

    def noteFrameSkipped(self, reason="idle", wait_ms=None):
        """Record a host decision not to render; diagnostics only."""
        self._frame_stats["skipped_frames"] += 1
        self._frame_stats["last_skip_reason"] = str(reason or "idle")
        self._frame_stats["last_wait_ms"] = None if wait_ms is None else max(0.0, float(wait_ms))
        self._recordFrameHistory("skipped", reason, wait_ms)

    @staticmethod
    def _percentile(values, percentile):
        values = sorted(float(value) for value in values if value is not None)
        if not values:
            return None
        if len(values) == 1:
            return values[0]
        q = min(100.0, max(0.0, float(percentile))) / 100.0
        pos = q * (len(values) - 1)
        low = int(pos)
        high = min(len(values) - 1, low + 1)
        fraction = pos - low
        return values[low] + (values[high] - values[low]) * fraction

    def _rollingFrameDiagnostics(self, window_seconds=5.0):
        now = time.monotonic()
        cutoff = now - max(0.1, float(window_seconds))
        entries = [entry for entry in self._frame_history if entry[0] >= cutoff]
        rendered = sum(1 for _ts, kind, _reason, _wait in entries if kind == "rendered")
        skipped = sum(1 for _ts, kind, _reason, _wait in entries if kind == "skipped")
        waits = [wait for _ts, kind, _reason, wait in entries if kind == "skipped" and wait is not None]
        span = max(0.001, min(float(window_seconds), now - entries[0][0])) if entries else float(window_seconds)
        decisions = rendered + skipped
        return {
            "window_seconds": float(window_seconds),
            "rendered": rendered,
            "skipped": skipped,
            "decisions": decisions,
            "render_rate_hz": rendered / span if entries else 0.0,
            "skip_rate_hz": skipped / span if entries else 0.0,
            "render_fraction": (rendered / decisions) if decisions else 0.0,
            "idle_fraction": (skipped / decisions) if decisions else 0.0,
            "average_wait_ms": (sum(waits) / len(waits)) if waits else None,
            "wait_p50_ms": self._percentile(waits, 50.0),
            "wait_p95_ms": self._percentile(waits, 95.0),
            "sample_count": len(entries),
        }

    def frameDiagnosticsSnapshot(self):
        """Return render/idle counters without querying native window state."""
        snapshot = dict(self._frame_stats)
        snapshot["rolling_5s"] = self._rollingFrameDiagnostics(5.0)
        snapshot["rolling_30s"] = self._rollingFrameDiagnostics(30.0)
        host = self.windowHost()
        snapshot["host"] = host.diagnosticsSnapshot()
        return snapshot


    def idleRenderHealthSnapshot(self, *, window_seconds=5.0,
                                 max_idle_render_hz=2.0,
                                 min_idle_fraction=0.80):
        """Return quantitative idle-render health without touching native UI.

        The thresholds are intentionally conservative first-line regression
        guards, not a CPU percentage estimator.  A host that is otherwise idle
        should not continuously repaint merely because timers/polling exist.
        """
        rolling = self._rollingFrameDiagnostics(window_seconds)
        render_rate = float(rolling.get("render_rate_hz", 0.0) or 0.0)
        idle_fraction = float(rolling.get("idle_fraction", 0.0) or 0.0)
        decisions = int(rolling.get("decisions", 0) or 0)
        max_rate = max(0.0, float(max_idle_render_hz))
        min_idle = min(1.0, max(0.0, float(min_idle_fraction)))
        healthy = (decisions == 0 or
                   (render_rate <= max_rate and idle_fraction >= min_idle))
        return {
            "window_seconds": float(window_seconds),
            "decisions": decisions,
            "render_rate_hz": render_rate,
            "idle_fraction": idle_fraction,
            "max_idle_render_hz": max_rate,
            "min_idle_fraction": min_idle,
            "within_threshold": bool(healthy),
        }

    def framePerformanceBaselineSnapshot(self, *, window_seconds=30.0):
        """Return a read-only rolling baseline for idle/performance regression.

        This is deliberately a renderer-work baseline rather than a CPU-percent
        estimator.  It exposes stable rates and wait percentiles that can be
        compared across releases without sampling the process or waking the UI.
        """
        rolling = self._rollingFrameDiagnostics(window_seconds)
        return {
            "window_seconds": float(window_seconds),
            "sample_count": int(rolling.get("sample_count", 0) or 0),
            "decisions": int(rolling.get("decisions", 0) or 0),
            "render_rate_hz": float(rolling.get("render_rate_hz", 0.0) or 0.0),
            "skip_rate_hz": float(rolling.get("skip_rate_hz", 0.0) or 0.0),
            "render_fraction": float(rolling.get("render_fraction", 0.0) or 0.0),
            "idle_fraction": float(rolling.get("idle_fraction", 0.0) or 0.0),
            "average_wait_ms": rolling.get("average_wait_ms"),
            "wait_p50_ms": rolling.get("wait_p50_ms"),
            "wait_p95_ms": rolling.get("wait_p95_ms"),
        }


    def framePerformanceComparisonSnapshot(self, *, current_window_seconds=5.0,
                                           baseline_window_seconds=30.0,
                                           min_current_samples=5,
                                           min_baseline_samples=20):
        """Compare recent frame behavior with a longer retained baseline.

        Comparison is gated by minimum sample counts so startup/transient bursts
        cannot be promoted into performance warnings.  This method is strictly
        observational and never consumes dirty state or pumps the event loop.
        """
        current = self._rollingFrameDiagnostics(current_window_seconds)
        baseline = self.framePerformanceBaselineSnapshot(
            window_seconds=baseline_window_seconds)
        current_samples = int(current.get("sample_count", 0) or 0)
        baseline_samples = int(baseline.get("sample_count", 0) or 0)
        ready = (current_samples >= max(0, int(min_current_samples)) and
                 baseline_samples >= max(0, int(min_baseline_samples)))

        def _delta(name):
            a = current.get(name)
            b = baseline.get(name)
            if a is None or b is None:
                return None
            return float(a) - float(b)

        def _ratio(name):
            a = current.get(name)
            b = baseline.get(name)
            if a is None or b in (None, 0, 0.0):
                return None
            return float(a) / float(b)

        return {
            "ready": bool(ready),
            "min_current_samples": max(0, int(min_current_samples)),
            "min_baseline_samples": max(0, int(min_baseline_samples)),
            "current": current,
            "baseline": baseline,
            "render_rate_delta_hz": _delta("render_rate_hz"),
            "render_rate_ratio": _ratio("render_rate_hz"),
            "idle_fraction_delta": _delta("idle_fraction"),
            "wait_p50_delta_ms": _delta("wait_p50_ms"),
            "wait_p95_delta_ms": _delta("wait_p95_ms"),
        }

    def framePerformanceRegressionSnapshot(self, *, policy=None, current_window_seconds=None,
                                           baseline_window_seconds=None,
                                           min_current_samples=None,
                                           min_baseline_samples=None,
                                           max_render_rate_ratio=None,
                                           max_idle_fraction_drop=None,
                                           max_wait_p95_delta_ms=None):
        """Evaluate current-vs-baseline frame regression thresholds.

        The result is sample-gated and stateless.  Consecutive breach/recovery
        hysteresis belongs to UIHangWatchdog, keeping the renderer runtime free
        of a second warning state machine or polling loop.
        """
        policy = QPerformancePolicy.fromMapping(policy)
        current_window_seconds = policy.current_window_seconds if current_window_seconds is None else current_window_seconds
        baseline_window_seconds = policy.baseline_window_seconds if baseline_window_seconds is None else baseline_window_seconds
        min_current_samples = policy.min_current_samples if min_current_samples is None else min_current_samples
        min_baseline_samples = policy.min_baseline_samples if min_baseline_samples is None else min_baseline_samples
        max_render_rate_ratio = policy.max_render_rate_ratio if max_render_rate_ratio is None else max_render_rate_ratio
        max_idle_fraction_drop = policy.max_idle_fraction_drop if max_idle_fraction_drop is None else max_idle_fraction_drop
        max_wait_p95_delta_ms = policy.max_frame_wait_p95_delta_ms if max_wait_p95_delta_ms is None else max_wait_p95_delta_ms
        comparison = self.framePerformanceComparisonSnapshot(
            current_window_seconds=current_window_seconds,
            baseline_window_seconds=baseline_window_seconds,
            min_current_samples=min_current_samples,
            min_baseline_samples=min_baseline_samples)
        ready = bool(comparison.get('ready'))
        render_ratio = comparison.get('render_rate_ratio')
        idle_delta = comparison.get('idle_fraction_delta')
        wait_delta = comparison.get('wait_p95_delta_ms')
        checks = {
            'render_rate_ratio': bool(ready and render_ratio is not None and
                                      float(render_ratio) > float(max_render_rate_ratio)),
            'idle_fraction_drop': bool(ready and idle_delta is not None and
                                       float(idle_delta) < -abs(float(max_idle_fraction_drop))),
            'wait_p95_delta_ms': bool(ready and wait_delta is not None and
                                      float(wait_delta) > float(max_wait_p95_delta_ms)),
        }
        breached = bool(ready and any(checks.values()))
        return {
            'ready': ready,
            'threshold_breached': breached,
            'checks': checks,
            'thresholds': {
                'max_render_rate_ratio': float(max_render_rate_ratio),
                'max_idle_fraction_drop': abs(float(max_idle_fraction_drop)),
                'max_wait_p95_delta_ms': float(max_wait_p95_delta_ms),
            },
            'comparison': comparison,
        }

    def asyncRuntimeSnapshot(self):
        """Return read-only QObject/future/thread-pool counts for correlation.

        The global QThreadPool is observed only when it already exists; asking
        for diagnostics must never allocate a pool or worker thread.
        """
        from .core.object import QObject
        from .core.concurrent import QFuture, QFutureWatcher, QThreadPool
        live = QObject.liveObjects()
        roots = [obj for obj in live if getattr(obj, 'parent', None) is None]
        futures = [obj for obj in live if isinstance(obj, QFuture)]
        watchers = [obj for obj in live if isinstance(obj, QFutureWatcher)]
        return {
            'qobject_live_count': len(live),
            'qobject_root_count': len(roots),
            'future_live_count': len(futures),
            'future_running_count': sum(1 for obj in futures if obj.isRunning()),
            'future_finished_count': sum(1 for obj in futures if obj.isFinished()),
            'future_watcher_count': len(watchers),
            'global_thread_pool': QThreadPool.globalDiagnosticsSnapshot(),
            'thread_pools': QThreadPool.namedDiagnosticsSnapshot(),
        }

    def performanceAcceptanceSnapshot(self, dispatcher=None, *, policy=None,
                                      max_idle_render_rate_hz=None,
                                      min_idle_fraction=None,
                                      max_dispatcher_queue_wait_p95_ms=None,
                                      max_dispatcher_callback_p95_ms=None,
                                      min_dispatcher_samples=None):
        """Evaluate release-level, sample-gated runtime performance acceptance."""
        policy = QPerformancePolicy.fromMapping(policy)
        max_idle_render_rate_hz = policy.max_idle_render_rate_hz if max_idle_render_rate_hz is None else max_idle_render_rate_hz
        min_idle_fraction = policy.min_idle_fraction if min_idle_fraction is None else min_idle_fraction
        max_dispatcher_queue_wait_p95_ms = policy.max_dispatcher_queue_wait_p95_ms if max_dispatcher_queue_wait_p95_ms is None else max_dispatcher_queue_wait_p95_ms
        max_dispatcher_callback_p95_ms = policy.max_dispatcher_callback_p95_ms if max_dispatcher_callback_p95_ms is None else max_dispatcher_callback_p95_ms
        min_dispatcher_samples = policy.min_dispatcher_samples if min_dispatcher_samples is None else min_dispatcher_samples
        frame = self.framePerformanceSnapshot()
        dispatcher_recent = None
        if dispatcher is not None:
            recent_fn = getattr(dispatcher, 'recentDiagnosticsSnapshot', None)
            if callable(recent_fn):
                dispatcher_recent = recent_fn(policy.current_window_seconds)
        samples = int((dispatcher_recent or {}).get('callback_sample_count', 0) or 0)
        dispatcher_ready = samples >= max(0, int(min_dispatcher_samples))
        wait_p95 = (dispatcher_recent or {}).get('queue_wait_ms_p95')
        callback_p95 = (dispatcher_recent or {}).get('callback_duration_ms_p95')
        checks = {
            'idle_render_rate_hz': float(frame.get('render_rate_hz_5s', 0.0) or 0.0) <= float(max_idle_render_rate_hz),
            'idle_fraction': float(frame.get('idle_fraction_5s', 0.0) or 0.0) >= float(min_idle_fraction),
            'dispatcher_queue_wait_p95_ms': (not dispatcher_ready or wait_p95 is None or float(wait_p95) <= float(max_dispatcher_queue_wait_p95_ms)),
            'dispatcher_callback_p95_ms': (not dispatcher_ready or callback_p95 is None or float(callback_p95) <= float(max_dispatcher_callback_p95_ms)),
        }
        return {
            'ready': bool(dispatcher is None or dispatcher_ready),
            'accepted': bool(all(checks.values()) and (dispatcher is None or dispatcher_ready)),
            'checks': checks,
            'thresholds': {
                'max_idle_render_rate_hz': float(max_idle_render_rate_hz),
                'min_idle_fraction': float(min_idle_fraction),
                'max_dispatcher_queue_wait_p95_ms': float(max_dispatcher_queue_wait_p95_ms),
                'max_dispatcher_callback_p95_ms': float(max_dispatcher_callback_p95_ms),
                'min_dispatcher_samples': max(0, int(min_dispatcher_samples)),
            },
            'policy': policy.toDict(),
            'frame': frame,
            'dispatcher_recent': dispatcher_recent,
        }

    def performanceEnvelopeSnapshot(self, dispatcher=None, *, window_seconds=30.0, policy=None):
        """Return a versioned JSON-safe release performance envelope."""
        policy = QPerformancePolicy.fromMapping(policy)
        report = self.performanceReportSnapshot(dispatcher, recent_window_seconds=min(5.0, float(window_seconds)))
        dispatcher_recent = None
        if dispatcher is not None:
            recent_fn = getattr(dispatcher, 'recentDiagnosticsSnapshot', None)
            if callable(recent_fn):
                dispatcher_recent = recent_fn(float(window_seconds))
        frame = self.framePerformanceBaselineSnapshot(window_seconds=float(window_seconds))
        return {
            'schema': 2,
            'window_seconds': float(window_seconds),
            'policy': policy.toDict(),
            'frame': frame,
            'dispatcher': dispatcher_recent,
            'async_runtime': report.get('async_runtime'),
        }

    @staticmethod
    def savePerformanceEnvelope(path, envelope):
        """Atomically persist an explicitly requested performance envelope."""
        target = os.path.abspath(os.fspath(path))
        directory = os.path.dirname(target) or os.curdir
        os.makedirs(directory, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix='.perf-envelope-', suffix='.tmp', dir=directory)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(envelope, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.write('\n')
            os.replace(temp_path, target)
        except Exception:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise
        return target

    @staticmethod
    def migratePerformanceEnvelope(envelope):
        """Validate/migrate supported envelope schemas to the current schema."""
        if not isinstance(envelope, dict):
            raise ValueError('invalid performance envelope')
        schema = int(envelope.get('schema', 0) or 0)
        current_schema = 2
        if schema == current_schema:
            migrated = dict(envelope)
            migrated['policy'] = QPerformancePolicy.fromMapping(migrated.get('policy')).toDict()
            return migrated
        if schema == 1:
            migrated = dict(envelope)
            migrated['schema'] = current_schema
            migrated['policy'] = QPerformancePolicy.preset('release').toDict()
            return migrated
        if schema > current_schema:
            raise ValueError('future performance envelope schema {} cannot be downgraded to {}'.format(
                schema, current_schema))
        raise ValueError('unsupported legacy performance envelope schema {}; minimum supported schema is 1'.format(schema))

    @staticmethod
    def loadPerformanceEnvelope(path):
        with open(os.fspath(path), 'r', encoding='utf-8') as stream:
            data = json.load(stream)
        return QGuiRuntime.migratePerformanceEnvelope(data)

    def comparePerformanceEnvelope(self, envelope, dispatcher=None, *, window_seconds=30.0, policy=None):
        """Compare current retained percentiles to a versioned release envelope."""
        baseline = self.migratePerformanceEnvelope(envelope)
        effective_policy = QPerformancePolicy.fromMapping(policy or baseline.get('policy'))
        current = self.performanceEnvelopeSnapshot(dispatcher, window_seconds=window_seconds, policy=effective_policy)
        base_frame = baseline.get('frame') or {}
        cur_frame = current.get('frame') or {}
        base_disp = baseline.get('dispatcher') or {}
        cur_disp = current.get('dispatcher') or {}
        def delta(cur, base, key):
            a, b = cur.get(key), base.get(key)
            return None if a is None or b is None else float(a) - float(b)
        def ratio(cur, base, key):
            a, b = cur.get(key), base.get(key)
            if a is None or b is None or float(b) == 0.0:
                return None
            return float(a) / float(b)
        return {
            'schema': 2,
            'policy': effective_policy.toDict(),
            'frame': {
                'render_rate_hz_delta': delta(cur_frame, base_frame, 'render_rate_hz'),
                'render_rate_hz_ratio': ratio(cur_frame, base_frame, 'render_rate_hz'),
                'idle_fraction_delta': delta(cur_frame, base_frame, 'idle_fraction'),
                'wait_p95_ms_delta': delta(cur_frame, base_frame, 'wait_p95_ms'),
            },
            'dispatcher': {
                'queue_wait_p95_ms_delta': delta(cur_disp, base_disp, 'queue_wait_ms_p95'),
                'queue_wait_p95_ms_ratio': ratio(cur_disp, base_disp, 'queue_wait_ms_p95'),
                'callback_p95_ms_delta': delta(cur_disp, base_disp, 'callback_duration_ms_p95'),
                'turn_p95_ms_delta': delta(cur_disp, base_disp, 'turn_duration_ms_p95'),
            },
            'baseline': baseline,
            'current': current,
        }

    def performanceEnvelopeAcceptanceSnapshot(self, envelope, dispatcher=None, *,
                                              window_seconds=30.0, policy=None):
        """Deterministic CI/release acceptance against a persisted envelope."""
        comparison = self.comparePerformanceEnvelope(
            envelope, dispatcher, window_seconds=window_seconds, policy=policy)
        effective_policy = QPerformancePolicy.fromMapping(comparison.get('policy'))
        baseline = comparison.get('baseline') or {}
        current = comparison.get('current') or {}
        base_disp = baseline.get('dispatcher') or {}
        cur_disp = current.get('dispatcher') or {}
        base_samples = int(base_disp.get('callback_sample_count', 0) or 0)
        current_samples = int(cur_disp.get('callback_sample_count', 0) or 0)
        dispatcher_ready = (dispatcher is None or
                            (base_samples >= effective_policy.min_baseline_samples and
                             current_samples >= effective_policy.min_current_samples))
        frame_cmp = comparison.get('frame') or {}
        disp_cmp = comparison.get('dispatcher') or {}
        render_ratio = frame_cmp.get('render_rate_hz_ratio')
        idle_delta = frame_cmp.get('idle_fraction_delta')
        queue_ratio = disp_cmp.get('queue_wait_p95_ms_ratio')
        queue_delta = disp_cmp.get('queue_wait_p95_ms_delta')
        callback_delta = disp_cmp.get('callback_p95_ms_delta')
        checks = {
            'render_rate_ratio': (render_ratio is None or float(render_ratio) <= effective_policy.max_render_rate_ratio),
            'idle_fraction_drop': (idle_delta is None or float(idle_delta) >= -abs(effective_policy.max_idle_fraction_drop)),
            'dispatcher_queue_wait_ratio': (not dispatcher_ready or queue_ratio is None or float(queue_ratio) <= effective_policy.max_queue_wait_p95_ratio),
            'dispatcher_queue_wait_delta_ms': (not dispatcher_ready or queue_delta is None or float(queue_delta) <= effective_policy.max_queue_wait_p95_delta_ms),
            'dispatcher_callback_delta_ms': (not dispatcher_ready or callback_delta is None or float(callback_delta) <= effective_policy.max_category_callback_p95_delta_ms),
        }
        ready = bool(dispatcher is None or dispatcher_ready)
        return {
            'ready': ready,
            'accepted': bool(ready and all(checks.values())),
            'checks': checks,
            'policy': effective_policy.toDict(),
            'comparison': comparison,
        }

    @staticmethod
    def performancePolicySnapshot(policy=None):
        if isinstance(policy, str):
            return QPerformancePolicy.preset(policy).toDict()
        return QPerformancePolicy.fromMapping(policy).toDict()

    def performanceReportSnapshot(self, dispatcher=None, *, recent_window_seconds=5.0, policy=None):
        """Return one side-effect-free frame + dispatcher performance report.

        The report deliberately accepts the host dispatcher instead of probing
        private application state.  This keeps QGuiRuntime renderer-facing while
        still letting watchdog/crash tooling correlate frame pressure with queue
        wait, callback execution and whole-turn latency.
        """
        effective_policy = QPerformancePolicy.fromMapping(policy)
        dispatcher_snapshot = None
        recent = None
        queue_wait_regression = None
        priority_wait = None
        priority_regression = None
        long_queue_wait_callbacks = None
        category_regression = None
        category_sustained_regression = None
        if dispatcher is not None:
            compact = getattr(dispatcher, "compactDiagnosticsSnapshot", None)
            if callable(compact):
                dispatcher_snapshot = compact()
            else:
                snapshot = getattr(dispatcher, "diagnosticsSnapshot", None)
                if callable(snapshot):
                    dispatcher_snapshot = snapshot()
            recent_fn = getattr(dispatcher, "recentDiagnosticsSnapshot", None)
            if callable(recent_fn):
                recent = recent_fn(recent_window_seconds)
            regression_fn = getattr(dispatcher, "queueWaitRegressionSnapshot", None)
            if callable(regression_fn):
                queue_wait_regression = regression_fn(
                    current_window_seconds=recent_window_seconds)
            priority_fn = getattr(dispatcher, "priorityDiagnosticsSnapshot", None)
            if callable(priority_fn):
                priority_wait = priority_fn(window_seconds=30.0)
            priority_regression_fn = getattr(dispatcher, 'priorityRegressionSnapshot', None)
            if callable(priority_regression_fn):
                priority_regression = priority_regression_fn(
                    current_window_seconds=recent_window_seconds)
            long_wait_fn = getattr(dispatcher, 'longQueueWaitCallbacksSnapshot', None)
            if callable(long_wait_fn):
                long_queue_wait_callbacks = long_wait_fn(window_seconds=30.0)
            category_regression_fn = getattr(dispatcher, 'callbackCategoryRegressionSnapshot', None)
            if callable(category_regression_fn):
                category_regression = category_regression_fn(
                    current_window_seconds=recent_window_seconds)
            category_sustained_fn = getattr(dispatcher, 'callbackCategorySustainedRegressionSnapshot', None)
            if callable(category_sustained_fn):
                category_sustained_regression = category_sustained_fn(
                    current_window_seconds=effective_policy.category_sustained_current_window_seconds,
                    baseline_window_seconds=effective_policy.category_sustained_baseline_window_seconds,
                    min_current_samples=effective_policy.category_sustained_min_current_samples,
                    min_baseline_samples=effective_policy.category_sustained_min_baseline_samples,
                    max_p95_ratio=effective_policy.max_category_p95_ratio,
                    max_p95_delta_ms=effective_policy.max_category_p95_delta_ms,
                    max_callback_p95_delta_ms=effective_policy.max_category_callback_p95_delta_ms,
                    top_limit=effective_policy.category_sustained_top_limit)
        frame_regression_fn = self.framePerformanceRegressionSnapshot
        if getattr(frame_regression_fn, "__func__", None) is QGuiRuntime.framePerformanceRegressionSnapshot:
            frame_regression = frame_regression_fn(policy=effective_policy)
        else:
            # Preserve compatibility with lightweight test/embedding overrides
            # that predate the optional policy keyword.
            frame_regression = frame_regression_fn()
        return {
            "performance_policy": effective_policy.toDict(),
            "frame": self.framePerformanceSnapshot(),
            "frame_regression": frame_regression,
            "dispatcher": dispatcher_snapshot,
            "dispatcher_recent": recent,
            "dispatcher_queue_wait_regression": queue_wait_regression,
            "dispatcher_priority_wait": priority_wait,
            "dispatcher_priority_regression": priority_regression,
            "dispatcher_long_queue_wait_callbacks": long_queue_wait_callbacks,
            "dispatcher_category_regression": category_regression,
            "dispatcher_category_sustained_regression": category_sustained_regression,
            "dispatcher_sustained_starvation": (dispatcher.sustainedStarvationSnapshot()
                if dispatcher is not None and callable(getattr(dispatcher, 'sustainedStarvationSnapshot', None)) else None),
            "dispatcher_callback_categories": (dispatcher.callbackCategoryDiagnosticsSnapshot()
                if dispatcher is not None and callable(getattr(dispatcher, 'callbackCategoryDiagnosticsSnapshot', None)) else None),
            "async_runtime": self.asyncRuntimeSnapshot(),
        }

    def crashDiagnosticsSnapshot(self, dispatcher=None):
        """Compact retained runtime snapshot for watchdog/crash reports."""
        host = self.windowHost()
        host_snapshot = (host.compactDiagnosticsSnapshot()
                         if hasattr(host, "compactDiagnosticsSnapshot")
                         else host.diagnosticsSnapshot())
        report = self.performanceReportSnapshot(dispatcher)
        report["host"] = host_snapshot
        try:
            from .core.application import QCoreApplication
            application = QCoreApplication.instance()
            diagnostics = getattr(application, "guiThreadDiagnosticsSnapshot", None)
            acceptance = getattr(application, "guiThreadAcceptanceSnapshot", None)
            report["gui_thread"] = diagnostics() if callable(diagnostics) else None
            report["gui_thread_acceptance"] = acceptance() if callable(acceptance) else None
        except Exception:
            report["gui_thread"] = None
        return report

    def framePerformanceSnapshot(self):
        """Compact watchdog/performance view of the retained frame scheduler.

        This remains observational: it never consumes dirty damage or polls a
        native HWND. ``idle_candidate`` indicates that the retained runtime has
        no immediate Qt deadline, damage or presentation transaction.
        """
        schedule = self.frameSchedulingSnapshot()
        diagnostics = self.frameDiagnosticsSnapshot()
        rolling = diagnostics.get("rolling_5s", {})
        idle_health = self.idleRenderHealthSnapshot()
        baseline = self.framePerformanceBaselineSnapshot(window_seconds=30.0)
        comparison = self.framePerformanceComparisonSnapshot(
            current_window_seconds=5.0, baseline_window_seconds=30.0)
        regression = self.framePerformanceRegressionSnapshot(
            current_window_seconds=5.0, baseline_window_seconds=30.0)
        warning_eligible = bool(comparison.get("ready"))
        return {
            "idle_candidate": not bool(schedule.get("immediate_frame")),
            "next_deadline_ms": schedule.get("next_deadline_ms"),
            "has_dirty_region": bool(schedule.get("has_dirty_region")),
            "presentation_pending": bool(schedule.get("presentation_pending")),
            "render_rate_hz_5s": float(rolling.get("render_rate_hz", 0.0) or 0.0),
            "idle_fraction_5s": float(rolling.get("idle_fraction", 0.0) or 0.0),
            "average_wait_ms_5s": rolling.get("average_wait_ms"),
            "host_state": diagnostics.get("host", {}).get("state"),
            "idle_render_within_threshold": idle_health.get("within_threshold"),
            "idle_render_threshold_breached": bool(
                warning_eligible and (not schedule.get("immediate_frame")) and
                not idle_health.get("within_threshold", True)),
            "idle_render_warning_eligible": warning_eligible,
            "idle_render_threshold": idle_health,
            "baseline_30s": baseline,
            "comparison_5s_vs_30s": comparison,
            "baseline_regression": regression,
        }

    def renderFrame(self):
        if not self.isRunning():
            return False
        schedule = self.frameSchedulingSnapshot()
        self._frame_stats["rendered_frames"] += 1
        if schedule.get("has_dirty_region"):
            self._frame_stats["dirty_triggered_frames"] += 1
        if schedule.get("presentation_pending"):
            self._frame_stats["presentation_triggered_frames"] += 1
        deadline = schedule.get("next_deadline_ms")
        if deadline is not None and deadline <= 0:
            self._frame_stats["deadline_triggered_frames"] += 1
        self._frame_stats["last_skip_reason"] = None
        self._frame_stats["last_wait_ms"] = 0.0
        self._recordFrameHistory("rendered")
        # Per-monitor DPI is a renderer/window-system concern.  Poll once per
        # frame, but dispatch work only when the logical DPI value changed.
        from .gui.dpi import sync_backend_dpi
        sync_backend_dpi(self.backend)
        from .gui.popup_tracking import update_popup_positions
        update_popup_positions(self.backend)
        from .backends.shared_scrollers import update_shared_scrollers
        update_shared_scrollers(self.backend)
        from .backends.native_presentation import presentation_for
        presentation = presentation_for(self.backend)
        if presentation is not None:
            presentation.before_frame()
        try:
            self._run_before_render_callbacks()
            self.backend.render_dearpygui_frame()
            self._window_host.takeDirtyRegion()
        finally:
            if presentation is not None:
                presentation.after_frame()
        # Stretching controls publish their new geometry during this render.
        update_popup_positions(self.backend)
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
            from .backends.shared_scrollers import clear_shared_scrollers
            clear_shared_scrollers(self.backend)
            self.backend.destroy_context()
        finally:
            self._before_render_callbacks.pop(id(self.backend), None)
            from .backends.native_windows import NativeWindowBackend
            NativeWindowBackend(self.backend).registerPrimary(None, False)
            from .gui.popup_tracking import clear_popup_tracking
            clear_popup_tracking(self.backend)
            from .backends.native_presentation import release_presentation
            release_presentation(self.backend)
            from .gui.dpi import clear_backend_dpi_state
            clear_backend_dpi_state(self.backend)
            self._context_created = False
            self._setup = False
            self._viewport_created = False
            self._visible = False
            host = self._take_window_host(self.backend)
            if host is None:
                host = self._window_host
            try:
                host.delete()
            except Exception:
                pass
            self._window_host = host
        return True

    def contextCreated(self):
        return bool(self._context_created)

    def viewportCreated(self):
        return bool(self._viewport_created)


__all__ = ["StandaloneUiHost", "QGuiRuntime"]
