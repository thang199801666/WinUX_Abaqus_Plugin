"""Deferred main-window startup, persistent docking and native console host setup.

State remains owned by :class:`WinUXView`; this mixin only carries behavior.
"""
from __future__ import annotations

import ctypes as _ctypes_stdlib
import os
import sys
from ctypes import wintypes
from pathlib import Path

from DearUIQt.gui import QFontDatabase

from ..docking.plot import PlotDockingMixin
from ....diagnostics import log_event, log_exception
from ....runtime import UIHangWatchdog


def _view_ctypes():
    """Honor historical monkey-patches applied through ``WinUx.view.ctypes``."""
    module = sys.modules.get("WinUx.ui.main_window") or sys.modules.get("WinUx.view")
    return getattr(module, "ctypes", _ctypes_stdlib) if module is not None else _ctypes_stdlib


class StartupDockingMixin:
    def _finish_deferred_startup(self):
        """Build secondary UI/diagnostics after the first visible frame."""
        if not self._alive:
            return
        self._ensure_jobs_view()
        # Real dock tear-offs require a second native DPG viewport even though
        # ordinary dialogs now run in-process. Prepare exactly one reusable host
        # after the first frame so the first Console/Plot undock is warm without
        # adding work to cold startup. The pool is bounded and owned by the view.
        self.after(0, self._prewarm_native_dock_host)
        # Restore detached-vs-docked runtime state only after the native main
        # viewport has rendered. This avoids putting native host construction
        # back on the cold-start critical path.
        self.after(80, self._restore_persisted_dock_runtime)
        if self._watchdog is None:
            try:
                self._watchdog = UIHangWatchdog()
                self._watchdog.add_snapshot_provider(
                    "ui_dispatcher", self._dispatcher.snapshot)
            except Exception:
                self._watchdog = None
                log_exception(
                    "UI hang watchdog could not start",
                    sys.exc_info(), fatal=False)

    def _collect_dock_state(self):
        """Return the persistent QMainWindow-like dock state."""
        plot_mode = str(getattr(self, "_plot_default_mode", "docked") or "docked")
        plot_windows = list((getattr(self, "job_plot_windows", {}) or {}).values())
        placeholder = getattr(self, "_empty_job_plot_window", None)
        if placeholder is not None:
            plot_windows.append(placeholder)
        live_plot_windows = []
        for window in plot_windows:
            try:
                if window is not None and window.exists():
                    live_plot_windows.append(window)
            except Exception:
                continue
        if live_plot_windows:
            plot_mode = (
                "floating" if any(
                    str(getattr(window, "dock_mode", "docked")).lower() == "floating"
                    for window in live_plot_windows) else "docked")
        if plot_mode == "floating":
            remember_geometry = getattr(self, "_remember_plot_native_host_geometry", None)
            if callable(remember_geometry):
                try:
                    remember_geometry()
                except Exception:
                    pass
        plot_geometry = getattr(self, "_plot_saved_float_geometry", {}) or {}
        return {
            "version": 2,
            "console": {
                "visible": bool(getattr(self, "_console_dock_visible", False)),
                "mode": (
                    "floating" if str(getattr(self, "_console_dock_mode", "docked")).lower() == "floating"
                    else "docked"),
                "area": str(getattr(self, "_console_dock_area", "bottom") or "bottom"),
                "scope": str(getattr(self, "_console_dock_scope", "inner") or "inner"),
                "width": int(getattr(self, "_console_dock_width", self.CONSOLE_DOCK_DEFAULT_WIDTH)),
                "height": int(getattr(self, "_console_dock_height", self.CONSOLE_DOCK_DEFAULT_HEIGHT)),
            },
            "plot": {
                "visible": bool(getattr(self, "_plot_dock_visible", False)),
                "mode": plot_mode,
                "area": str(getattr(self, "_plot_dock_area", "right") or "right"),
                "scope": str(getattr(self, "_plot_dock_scope", "inner") or "inner"),
                "split_ratios": {
                    area: float(getattr(self, "_plot_split_ratios", {}).get(
                        area, self.PLOT_DOCK_DEFAULT_RATIO))
                    for area in self.PLOT_DOCK_AREAS
                },
                "float_geometry": dict(plot_geometry),
            },
        }

    def _persist_dock_state(self):
        """Persist dock placement immediately after a completed transition."""
        try:
            state = self._collect_dock_state()
            self._general_preferences.save_dock_state(state)
            self._persisted_dock_state = state
            return True
        except Exception:
            log_exception(
                "Failed to save WinUx dock state", sys.exc_info(), fatal=False)
            return False

    def _restore_persisted_dock_runtime(self):
        """Apply runtime-only parts of saved state after the first frame."""
        if not self._alive:
            return
        if self._qapplication is not None and self._qapplication.activeModalWidget() is not None:
            self.after(150, self._restore_persisted_dock_runtime)
            return
        if (getattr(self, "_console_dock_visible", False)
                and str(getattr(self, "_console_dock_mode", "docked")).lower() == "floating"):
            try:
                # set_console_visible knows how to create/show the detached host
                # while keeping persisted visibility unchanged.
                self.set_console_visible(
                    True, persist=False, request_login=False)
            except Exception:
                log_exception(
                    "Saved floating Console state could not be restored",
                    sys.exc_info(), fatal=False)
                self._console_dock_mode = "docked"
                self._layout_dirty = True
                self._apply_split_layout(force=True)

        # Restore Plot visibility/placement after the viewport is live.  When
        # the previous state was floating, _ensure_empty_job_plot_window()
        # prepares the native host and undocks it using the persisted geometry;
        # when docked, the saved area/scope/split ratio are already loaded.
        try:
            if bool(getattr(self, "_plot_dock_visible", False)):
                self.set_plots_visible(True, persist=False)
            else:
                self._sync_plots_view_action()
        except Exception:
            log_exception(
                "Saved Plot dock state could not be restored",
                sys.exc_info(), fatal=False)
            self._plot_dock_visible = False
            self._plot_default_mode = "docked"
            self._set_plot_dock_open(False)
            self._sync_plots_view_action()

    def _prewarm_native_dock_host(self):
        """Prepare one reusable external viewport for true dock tear-off."""
        if not self._alive or getattr(self, "_floating_focus_suppressed", False):
            return
        if self._qapplication is not None and self._qapplication.activeModalWidget() is not None:
            self.after(150, self._prewarm_native_dock_host)
            return
        try:
            from ...hosting.host import start_dialog_prewarm
            start_dialog_prewarm(self)
        except Exception:
            # A failed warm slot must never affect the main window. The normal
            # dock path can still reserve a cold host on demand.
            log_exception(
                "Native dock host prewarm failed", sys.exc_info(), fatal=False)

    def _ensure_jobs_view(self):
        """Return the Job Viewer, constructing it only when first required."""
        viewer = getattr(self, "jobs_view", None)
        if viewer is not None:
            return viewer
        from ...components.jobs_view import JobsView
        viewer = JobsView(self.bottom_region, self.callbacks)
        self.jobs_view = viewer
        try:
            self._layout_dirty = True
            self._apply_split_layout(force=True)
        except Exception:
            log_exception(
                "Deferred Job Viewer layout failed", sys.exc_info(), fatal=False)
        return viewer

    def _ensure_plot_dock_manager(self):
        """Create Job Plot docking infrastructure on first Plot use."""
        manager = getattr(self, "plot_dock_manager", None)
        if manager is not None:
            return manager
        from DearUIQt.widgets import DockManager
        manager = DockManager(
            self.plot_region,
            dock_area=self._plot_dock_area,
            tab_position="bottom",
            on_active_changed=self._job_plot_tab_activated,
            on_tab_tearoff=self._job_plot_tab_tearoff,
        )
        self.plot_dock_manager = manager
        return manager

    def _ensure_terminal_font(self):
        """Register the console font on first Console construction only."""
        if self.terminal_font is not None or self._font_database is not None:
            return self.terminal_font
        try:
            terminal_path = (
                Path(os.environ.get("WINDIR", "C:/Windows"))
                / "Fonts" / "consola.ttf")
            if terminal_path.is_file():
                self._font_database = QFontDatabase(parent=self._qapplication)
                self.terminal_font = self._font_database.addApplicationFont(
                    terminal_path, 14)
        except Exception:
            self.terminal_font = None
            self._font_database = None
        return self.terminal_font

    def _ensure_console_panel(self):
        """Create the expensive terminal widget only when Console is requested."""
        panel = getattr(self, "console_panel", None)
        if panel is not None:
            return panel
        self._ensure_terminal_font()
        from ....dialogs.console.console_form import ConsoleDockPanel
        panel = ConsoleDockPanel(
            self, self.console_dock.content,
            self.callbacks["console_output"],
            self.callbacks["console_command"],
            self.callbacks["console_interrupt"],
            lambda message: self.after(
                0, self.show_error, "SSH Console", message),
            completion_callback=self.callbacks.get("console_complete"),
            completion_list_callback=self.callbacks.get("console_completion_list"),
            raw_output_callback=self.callbacks.get("console_raw_output"),
            raw_input_callback=self.callbacks.get("console_input"),
            resize_callback=self.callbacks.get("console_resize"),
            refresh_callback=self.callbacks.get("console_refresh"),
        )
        self.console_panel = panel
        # Once the embedded Console is visible, prepare its detached native
        # mirror during idle time.  Building ConsoleDialog/native textures is
        # therefore removed from the later title-bar tear-off gesture.
        self.after(180, self._prepare_console_native_host)
        return panel

    def _prepare_native_reference_tools(self):
        from ....dialogs.reference.native_reference_tools import ReferenceChartDialog, PlotDigitizerDialog
        library = PlotDockingMixin._get_reference_chart_library(self)
        # Preconstruct only the bounded empty editor shell. Restoring a saved
        # dataset belongs to its menu session, never the main-window constructor.
        self._reference_chart_dialog = ReferenceChartDialog(self, [], lambda _result: None)
        self._reference_chart_dialog.hide()
        self._plot_digitizer_dialog = PlotDigitizerDialog(self, reference_library=library)
        self._plot_digitizer_dialog.hide()

    def _find_main_viewport_hwnd(self):
        """Resolve the Dear PyGui/GLFW main HWND without depending on a child view.

        The old implementation delegated to ``left.listview``.  That made the
        Console RMB/WM_CHAR hook disappear whenever the Explorer pane had not
        finished constructing (or its HWND helper temporarily returned 0).
        Resolve the process top-level window directly as a fallback and cache
        only handles that Windows still reports as valid.
        """
        if os.name != "nt":
            return None
        try:
            user32 = _view_ctypes().windll.user32
            cached = int(getattr(self, "_main_viewport_hwnd", 0) or 0)
            if cached and user32.IsWindow(wintypes.HWND(cached)):
                return cached
        except Exception:
            pass

        # Keep the existing component-specific finder as the first fast path.
        try:
            listview = getattr(getattr(self, "left", None), "listview", None)
            finder = getattr(listview, "_find_own_top_level_hwnd", None)
            if callable(finder):
                hwnd = int(finder() or 0)
                if hwnd:
                    self._main_viewport_hwnd = hwnd
                    return hwnd
        except Exception:
            pass

        # Independent fallback: enumerate visible top-level windows owned by
        # this process.  Prefer the exact WinUX viewport title, then any
        # ownerless process window.  This works even before FilePanel/ListView
        # has reached its first stable layout frame.
        try:
            user32 = _view_ctypes().windll.user32
            kernel32 = _view_ctypes().windll.kernel32
            user32.IsWindowVisible.argtypes = [wintypes.HWND]
            user32.IsWindowVisible.restype = wintypes.BOOL
            user32.GetWindowThreadProcessId.argtypes = [
                wintypes.HWND, _view_ctypes().POINTER(wintypes.DWORD)]
            user32.GetWindowThreadProcessId.restype = wintypes.DWORD
            user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
            user32.GetWindowTextLengthW.restype = _view_ctypes().c_int
            user32.GetWindowTextW.argtypes = [
                wintypes.HWND, wintypes.LPWSTR, _view_ctypes().c_int]
            user32.GetWindowTextW.restype = _view_ctypes().c_int
            user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetWindow.restype = wintypes.HWND
            process_id = int(kernel32.GetCurrentProcessId())
            candidates = []
            enum_type = _view_ctypes().WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            user32.EnumWindows.argtypes = [enum_type, wintypes.LPARAM]
            user32.EnumWindows.restype = wintypes.BOOL

            def visit(hwnd, _lparam):
                try:
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, _view_ctypes().byref(pid))
                    if int(pid.value) != process_id or not user32.IsWindowVisible(hwnd):
                        return True
                    length = int(user32.GetWindowTextLengthW(hwnd) or 0)
                    buffer = _view_ctypes().create_unicode_buffer(max(1, length + 1))
                    user32.GetWindowTextW(hwnd, buffer, len(buffer))
                    title = str(buffer.value or "")
                    owner = int(user32.GetWindow(hwnd, 4) or 0)  # GW_OWNER
                    score = 0
                    if title == "WinUX":
                        score += 100
                    elif title.lower().startswith("winux"):
                        score += 80
                    if owner == 0:
                        score += 20
                    candidates.append((score, int(hwnd), title))
                except Exception:
                    pass
                return True

            callback = enum_type(visit)
            user32.EnumWindows(callback, 0)
            if candidates:
                _score, hwnd, _title = max(candidates, key=lambda item: item[0])
                if hwnd:
                    self._main_viewport_hwnd = hwnd
                    return hwnd
        except Exception:
            pass
        return None

    def _install_console_character_hook(self):
        """Route WM_CHAR to the embedded console only while it owns focus.

        Dear PyGui exposes key-down handlers but no portable text-input callback
        for a custom drawn terminal.  The old floating console received WM_CHAR
        from its private viewport; the docked console now shares the main GLFW
        HWND, so subclass that window and consume characters only when the
        terminal explicitly owns keyboard input.  Pointer/context-menu input is
        deliberately left to Dear PyGui and all other messages continue through
        the previous WNDPROC unchanged.
        """
        if os.name != "nt" or self._console_native_wndproc_callback is not None:
            return bool(self._console_native_wndproc_callback)
        hwnd = self._find_main_viewport_hwnd()
        if not hwnd:
            return False
        try:
            user32 = _view_ctypes().windll.user32
            is_64 = _view_ctypes().sizeof(_view_ctypes().c_void_p) == 8
            setter = (
                user32.SetWindowLongPtrW if is_64
                else user32.SetWindowLongW)
            setter.argtypes = [wintypes.HWND, _view_ctypes().c_int, _view_ctypes().c_void_p]
            setter.restype = _view_ctypes().c_void_p
            user32.CallWindowProcW.argtypes = [
                _view_ctypes().c_void_p, wintypes.HWND, wintypes.UINT,
                wintypes.WPARAM, wintypes.LPARAM]
            user32.CallWindowProcW.restype = _view_ctypes().c_ssize_t
            wndproc_type = _view_ctypes().WINFUNCTYPE(
                _view_ctypes().c_ssize_t, wintypes.HWND, wintypes.UINT,
                wintypes.WPARAM, wintypes.LPARAM)
            WM_CHAR = 0x0102
            WM_CONTEXTMENU = 0x007B
            WM_RBUTTONUP = 0x0205
            GWL_WNDPROC = -4

            def dispatch(window, message, wparam, lparam):
                if message == WM_CHAR:
                    panel = getattr(self, "_console_keyboard_panel", None)
                    if (panel is not None
                            and getattr(panel, "keyboard_active", lambda: False)()):
                        self.after(0, panel.native_character, int(wparam))
                        return 0

                if message in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    # Windows may deliver either the raw RMB release or a
                    # WM_CONTEXTMENU notification depending on the embedded
                    # GLFW/DPG path.  Observe both without consuming either.
                    # All renderer/menu work stays deferred outside WNDPROC.
                    panel = getattr(self, "console_panel", None)
                    if (panel is not None
                            and getattr(self, "_console_dock_visible", False)
                            and getattr(self, "_console_dock_mode", "docked") == "docked"):
                        try:
                            point = wintypes.POINT()
                            user32.GetCursorPos.argtypes = [_view_ctypes().POINTER(wintypes.POINT)]
                            user32.GetCursorPos.restype = wintypes.BOOL
                            if user32.GetCursorPos(_view_ctypes().byref(point)):
                                position = (int(point.x), int(point.y))
                                # WM_CONTEXTMENU is already the semantic
                                # context-menu gesture, so dispatch promptly.
                                # RMBUP keeps a tiny delay to let the ordinary
                                # DPG path win first when it is available.
                                delay = 1 if message == WM_CONTEXTMENU else 25
                                self.after(delay, panel.native_context_release, position)
                        except Exception:
                            pass

                return user32.CallWindowProcW(
                    self._console_native_old_wndproc,
                    window, message, wparam, lparam)

            def safe_dispatch(window, message, wparam, lparam):
                try:
                    return dispatch(window, message, wparam, lparam)
                except BaseException:
                    log_exception(
                        "SSH Console native character hook failed",
                        sys.exc_info(), fatal=False)
                    try:
                        return user32.CallWindowProcW(
                            self._console_native_old_wndproc,
                            window, message, wparam, lparam)
                    except BaseException:
                        return 0

            callback = wndproc_type(safe_dispatch)
            _view_ctypes().set_last_error(0)
            old_proc = setter(
                wintypes.HWND(hwnd), GWL_WNDPROC,
                _view_ctypes().cast(callback, _view_ctypes().c_void_p))
            if not old_proc and _view_ctypes().get_last_error():
                return False
            self._console_native_hwnd = int(hwnd)
            self._console_native_old_wndproc = old_proc
            self._console_native_wndproc_callback = callback
            log_event(
                "SSH Console dock character hook installed on hwnd={}".format(
                    int(hwnd)))
            return True
        except Exception:
            log_exception(
                "Failed to install SSH Console character hook",
                sys.exc_info(), fatal=False)
            return False


__all__ = ["StartupDockingMixin"]
