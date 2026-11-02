from __future__ import annotations

import ctypes
import os
import time
import sys
from ctypes import wintypes

from DearUIQt.core import Qt
from DearUIQt.gui import QCursor
from DearUIQt.widgets import QApplication, QRetainedItem

from DearUIQt.splitter import clamp_ratio, split_extent
from DearUIQt.input_gate import (
    acquire_pointer_input, pointer_input_is_blocked, release_pointer_input,
)


class SplitterLayoutBehaviorMixin:
    """WinUx-specific splitter/docking interaction behavior.

    This integration layer intentionally lives outside :mod:`DearUIQt`.
    Generic splitter geometry/state belongs to ``DearUIQt.splitter``; this
    mixin binds that primitive to WinUx File/Job/Console/Plot layout semantics.
    """
    def _set_splitter_content_interactive(self, active):
        """Keep native visibility/resize callbacks on the same cheap path."""
        for panel in getattr(self, "panels", ()):
            listview = getattr(panel, "listview", None)
            if listview is not None:
                listview._owner_resize_interactive = bool(active)
        jobs = getattr(getattr(self, "jobs_view", None), "listview", None)
        if jobs is not None:
            jobs._owner_resize_interactive = bool(active)

    def _splitter_item(self, tag):
        """Return one cached DearUIQt facade for a retained splitter surface.

        The lazy import keeps this mixin independently AST-testable. Legacy tests
        may inject a fake ``dpg`` backend into the execution namespace; normal
        runtime resolves the active DearUIQt backend automatically.
        """
        if tag is None:
            return None
        from DearUIQt.widgets import QRetainedItem as _QRetainedItem
        cache = getattr(self, "_splitter_item_cache", None)
        if cache is None:
            cache = self._splitter_item_cache = {}
        item = cache.get(tag)
        if item is None:
            backend = globals().get("dpg")
            item = cache[tag] = _QRetainedItem(tag, backend=backend)
        try:
            item.setImmediateUpdates(bool(
                getattr(self, "_splitter_live_native_updates", False)))
        except Exception:
            pass
        return item

    def _on_viewport_resize(self, sender=None, app_data=None):
        """Record native viewport geometry for frame-throttled live relayout.

        Older revisions waited for the resize stream to become completely quiet
        before applying any layout.  That avoided work, but made the window feel
        sticky and then jump after the mouse stopped.  Keep the newest native
        size here; ``_apply_split_layout`` consumes it at a bounded frame rate
        using its lightweight interactive path and performs one full commit when
        the resize settles.
        """
        if getattr(self, "_compact_job_monitor_active", False):
            # Compact mode owns only its small job surface. Do not wake the full
            # File/Job/Console/Plot layout while the reused native HWND is the
            # bottom-right monitor window.
            try:
                layout = getattr(self, "_layout_compact_job_monitor", None)
                if callable(layout):
                    layout()
            except Exception:
                pass
            return
        # DPG reports (outer_width, outer_height, client_width, client_height).
        # Neither outer size nor a hard-coded caption/menu subtraction is the
        # workspace size: the retained layout root also excludes app padding,
        # menu height and spacing. Re-measure that root during each live layout
        # pass, including the final settled pass, instead of retaining a stale
        # oversized event value that clips the right/bottom panes.
        self._pending_viewport_size = None
        self._resize_last_event = time.monotonic()
        self._layout_dirty = True

    def _show_horizontal_splitter_cursor(
            self, sender=None, app_data=None, user_data=None):
        if QCursor.setShape(QCursor.SizeVerCursor):
            self._splitter_cursor_active = True
        self._set_native_windows_cursor(
            32645, "_native_resize_ns_cursor")  # IDC_SIZENS
        self._splitter_cursor_active = True

    def _set_native_windows_cursor(self, resource_id, cache_attribute):
        """Apply a Windows cursor after GLFW has rendered the current frame."""
        if os.name != "nt":
            return
        try:
            user32 = ctypes.windll.user32
            handle = getattr(self, cache_attribute, None)
            if not handle:
                user32.LoadCursorW.argtypes = [
                    wintypes.HINSTANCE, ctypes.c_void_p]
                user32.LoadCursorW.restype = wintypes.HANDLE
                handle = user32.LoadCursorW(
                    None, ctypes.c_void_p(int(resource_id)))
                setattr(self, cache_attribute, handle)
            if handle:
                user32.SetCursor.argtypes = [wintypes.HANDLE]
                user32.SetCursor.restype = wintypes.HANDLE
                user32.SetCursor(handle)
        except Exception:
            pass

    def _stable_splitter_cursor_hover(self, key, hovered, dragging=False):
        """Debounce one-frame hover loss from Dear ImGui/DPG hit testing.

        Splitter geometry/theme changes can make ``underMouse()`` briefly report
        False for a single rendered frame.  Without hysteresis the cursor flips
        resize -> arrow -> resize and visibly flickers.  Keep the current
        splitter cursor alive for a very short grace period; a real pointer exit
        still clears quickly, while an active drag remains authoritative.
        """
        now = time.monotonic()
        states = getattr(self, "_splitter_cursor_hover_until", None)
        if states is None:
            states = self._splitter_cursor_hover_until = {}
        key = str(key)
        if bool(hovered) or bool(dragging):
            states[key] = now + 0.09
            return True
        return now < float(states.get(key, 0.0) or 0.0)

    def _clear_splitter_cursor_hover(self, key=None):
        states = getattr(self, "_splitter_cursor_hover_until", None)
        if not states:
            return
        if key is None:
            states.clear()
        else:
            states.pop(str(key), None)

    def _horizontal_splitter_native_cursor_provider(self):
        """Return IDC_SIZENS while the horizontal splitter owns input."""
        if (
            getattr(self, "_splitter_cursor_active", False)
            or getattr(self, "_horizontal_splitter_dragging", False)
        ):
            return getattr(self, "_native_resize_ns_cursor", None)
        return None

    def _splitter_native_cursor_provider(self):
        """Return the native resize cursor for the active resize interaction."""
        floating = self._floating_plot_resize_cursor_handle()
        if floating:
            return floating
        if (
            getattr(self, "_file_panel_splitter_cursor_active", False)
            or getattr(self, "_file_panel_splitter_dragging", False)
        ):
            return getattr(self, "_native_resize_ew_cursor", None)
        if (
            getattr(self, "_console_splitter_cursor_active", False)
            or getattr(self, "_console_splitter_dragging", False)
        ):
            area = self._normalize_console_dock_area(
                getattr(self, "_console_dock_area", "bottom"))
            if area in ("left", "right"):
                return getattr(self, "_native_resize_ew_cursor", None)
            return getattr(self, "_native_resize_ns_cursor", None)
        if (
            getattr(self, "_plot_splitter_cursor_active", False)
            or getattr(self, "_plot_splitter_dragging", False)
        ):
            if self._plot_dock_is_vertical_split():
                return getattr(self, "_native_resize_ew_cursor", None)
            return getattr(self, "_native_resize_ns_cursor", None)
        return self._horizontal_splitter_native_cursor_provider()

    def _floating_plot_resize_cursor_kind(self):
        """Return cursor kind for the top-most hovered/active floating dock."""
        console = getattr(self, "_console_float_resizer", None)
        if console is not None and console.cursor_kind:
            return console.cursor_kind
        for key in reversed(tuple(self.job_plot_float_windows)):
            controller = self._plot_float_resizers.get(str(key))
            if controller is not None and controller.cursor_kind:
                return controller.cursor_kind
        return None

    def _floating_plot_resize_cursor_handle(self):
        kind = self._floating_plot_resize_cursor_kind()
        resource = {
            "nwse": (32642, "_native_resize_nwse_cursor"),  # IDC_SIZENWSE
            "nesw": (32643, "_native_resize_nesw_cursor"),  # IDC_SIZENESW
            "ew": (32644, "_native_resize_ew_cursor"),      # IDC_SIZEWE
            "ns": (32645, "_native_resize_ns_cursor"),      # IDC_SIZENS
        }.get(kind)
        if resource is None or os.name != "nt":
            return None
        resource_id, cache_attr = resource
        handle = getattr(self, cache_attr, None)
        if handle:
            return handle
        try:
            user32 = ctypes.windll.user32
            user32.LoadCursorW.argtypes = [
                wintypes.HINSTANCE, ctypes.c_void_p]
            user32.LoadCursorW.restype = wintypes.HANDLE
            handle = user32.LoadCursorW(
                None, ctypes.c_void_p(int(resource_id)))
            setattr(self, cache_attr, handle)
            return handle
        except Exception:
            return None

    def _apply_floating_plot_resize_cursor(self):
        """Keep a floating dock resize cursor stable after GLFW rendering."""
        kind = self._floating_plot_resize_cursor_kind()
        if not kind:
            return False
        console = getattr(self, "_console_float_resizer", None)
        if console is not None and console.cursor_kind == kind:
            console.apply_dpg_cursor()
        else:
            for controller in self._plot_float_resizers.values():
                if controller is not None and controller.cursor_kind == kind:
                    controller.apply_dpg_cursor()
                    break
        resource = {
            "nwse": (32642, "_native_resize_nwse_cursor"),
            "nesw": (32643, "_native_resize_nesw_cursor"),
            "ew": (32644, "_native_resize_ew_cursor"),
            "ns": (32645, "_native_resize_ns_cursor"),
        }.get(kind)
        if resource is not None:
            self._set_native_windows_cursor(*resource)
        return True

    @staticmethod
    def _native_cursor_screen_x():
        """Return physical screen X on Windows for stable one-to-one dragging."""
        if os.name != "nt":
            return None
        try:
            point = wintypes.POINT()
            user32 = ctypes.windll.user32
            user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
            user32.GetCursorPos.restype = wintypes.BOOL
            if user32.GetCursorPos(ctypes.byref(point)):
                return float(point.x)
        except Exception:
            pass
        return None

    @staticmethod
    def _native_cursor_screen_y():
        """Return physical screen Y on Windows for stable one-to-one dragging."""
        if os.name != "nt":
            return None
        try:
            point = wintypes.POINT()
            user32 = ctypes.windll.user32
            user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
            user32.GetCursorPos.restype = wintypes.BOOL
            if user32.GetCursorPos(ctypes.byref(point)):
                return float(point.y)
        except Exception:
            pass
        return None

    @staticmethod
    def _left_mouse_button_down():
        """Trust physical release, including mouse-up delivered to a dialog."""
        if os.name == "nt":
            try:
                return bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
            except Exception:
                pass
        try:
            app = QApplication.instance()
            return bool(app is not None and (app.mouseButtons() & Qt.LeftButton))
        except Exception:
            return False

    def _horizontal_splitter_hit_point(self):
        """Legacy coordinate diagnostic; never used to acquire pointer input."""
        try:
            hitbox = getattr(self, "horizontal_splitter_hitbox", None)
            hit = self._splitter_item(hitbox)
            if hit is None or not hit.exists():
                return None
            raw_x, raw_y = map(float, QCursor.pos().toTuple())
            rect = hit.globalGeometry()
            split_x, split_y = float(rect.x()), float(rect.y())
            split_width = max(1.0, float(rect.width()))
            split_height = max(1.0, float(rect.height()))

            # Dear PyGui can report the mouse in desktop-screen coordinates
            # while item rectangles remain viewport-relative. Include every
            # coordinate form exposed by supported DPG builds and retain the
            # matching adjustment for the complete drag gesture.
            candidates = [(raw_x, raw_y)]
            try:
                local_x, local_y = map(float, QCursor.localPos().toTuple())
                candidates.append((local_x, local_y))
            except Exception:
                pass
            try:
                viewport_x, viewport_y = map(float, (QApplication.instance().primaryScreen().geometry().topLeft().toTuple() if QApplication.instance() is not None else (0, 0)))
                candidates.extend((
                    (raw_x - viewport_x, raw_y - viewport_y),
                    (raw_x + viewport_x, raw_y + viewport_y),
                ))
            except Exception:
                pass

            for mouse_x, mouse_y in candidates:
                if (
                    split_x <= mouse_x <= split_x + split_width
                    and split_y <= mouse_y <= split_y + split_height
                ):
                    return mouse_x, mouse_y, mouse_y - raw_y
        except Exception:
            pass
        return None

    def _horizontal_splitter_hit_test(self):
        """Return True anywhere inside the dedicated File/Job gutter."""
        return self._horizontal_splitter_hit_point() is not None

    def _native_owner_accepts_input(self):
        """Host hook for native owner enabled/modal state.

        Reusable splitter code cannot assume a specific top-level windowing
        implementation. Applications may override this method when they need an
        OS-level owner check; the portable default accepts input.
        """
        return True

    def _splitter_modal_window_visible(self):
        """Host hook returning True while another modal surface owns input."""
        return False

    def _report_splitter_exception(self, message, exc_info):
        """Host hook for diagnostics; deliberately silent in the framework."""
        return None

    def _splitter_input_blocked(self, owner=None):
        """Return True when another foreground gesture owns pointer input.

        ``owner`` is the splitter-specific capture token.  Passing it through
        the application interaction gate gives splitters the same mouse-grab
        semantics as Qt: the splitter that accepted the press keeps receiving
        movement/release, while Explorer rows and every other splitter are
        blocked until that gesture ends.
        """
        return (not self._native_owner_accepts_input()
                or self._splitter_modal_window_visible()
                or pointer_input_is_blocked(owner))

    def _cancel_splitter_interactions(self):
        """A dialog taking input cancels, rather than pauses, workspace resize."""
        down = self._left_mouse_button_down()
        for prefix, end in (
                ("file_panel", self._end_file_panel_splitter_drag),
                ("horizontal", self._end_horizontal_splitter_drag),
                ("plot", self._end_job_plot_splitter_drag),
                ("console", self._end_console_splitter_drag)):
            if getattr(self, "_" + prefix + "_splitter_dragging", False):
                end()
            setattr(self, "_" + prefix + "_splitter_mouse_was_down", down)
        self._splitter_press_was_down = down
        self._splitter_active_hitboxes = set()
        self._clear_splitter_cursor_hover()
        # Do not set the OS cursor here: the foreground dialog owns it.
        for name in ("_splitter_cursor_active", "_file_panel_splitter_cursor_active",
                     "_plot_splitter_cursor_active", "_console_splitter_cursor_active"):
            setattr(self, name, False)

    def _mouse_position_variants(self):
        """Return the mouse in every coordinate space used by supported DPG builds."""
        points = []
        try:
            raw_x, raw_y = map(float, QCursor.pos().toTuple())
            points.append((raw_x, raw_y))
            try:
                points.append(tuple(map(float, QCursor.localPos().toTuple())))
            except Exception:
                pass
            try:
                viewport_x, viewport_y = map(float, (QApplication.instance().primaryScreen().geometry().topLeft().toTuple() if QApplication.instance() is not None else (0, 0)))
                points.extend(((raw_x - viewport_x, raw_y - viewport_y),
                               (raw_x + viewport_x, raw_y + viewport_y)))
            except Exception:
                pass
        except Exception:
            return []

        unique = []
        for point in points:
            if not any(abs(point[0] - old[0]) < 0.5 and
                       abs(point[1] - old[1]) < 0.5 for old in unique):
                unique.append(point)
        return unique

    def _cancel_explorer_gestures_for_splitter(self):
        """Make a splitter press exclusive before queued row callbacks run.

        Cancel pending click/drag/rubber state so grabbing a divider beside a
        selected item never starts a file drag from that item.
        """
        for panel in getattr(self, "panels", ()):
            listview = getattr(panel, "listview", None)
            cancel = getattr(listview, "cancel_pointer_gesture", None)
            if callable(cancel):
                try:
                    cancel(suppress_release=True)
                except Exception:
                    pass

    def _clear_splitter_selections(self):
        """Deselect files and jobs once a splitter has accepted the press."""
        for panel in getattr(self, "panels", ()):
            panel.clear_selection()
        self.clear_job_selection()

    def _mouse_over_item_rect(self, item):
        """Legacy geometry diagnostic, not permission to begin a gesture."""
        try:
            retained = self._splitter_item(item)
            if retained is None or not retained.exists():
                return False
            rect = retained.globalGeometry()
            x0, y0 = float(rect.x()), float(rect.y())
            width, height = float(rect.width()), float(rect.height())
            if width <= 0.0 or height <= 0.0:
                return False
            x1, y1 = x0 + width, y0 + height
            return any(
                x0 <= mx < x1 and y0 <= my < y1
                for mx, my in self._mouse_position_variants()
            )
        except Exception:
            return False

    def _file_panel_splitter_hit_test(self, ignore_pointer_capture=False):
        """Hit-test the dedicated Local/Server QSplitter-style gutter."""
        if (not ignore_pointer_capture
                and self._splitter_input_blocked(self._file_panel_splitter_owner)):
            return False
        hitbox = getattr(self, "file_panel_separator_hitbox", None)
        return self._splitter_hit_hovered(hitbox)

    def _splitter_hit_hovered(self, hitbox):
        """Resize affordance only for idle hover or this handle's own press."""
        try:
            item = self._splitter_item(hitbox)
            return bool(item is not None and item.exists() and item.isVisible()
                        and (item.isActive() or
                             (not self._left_mouse_button_down() and item.underMouse())))
        except Exception:
            return False

    def _splitter_hit_activated(self, hitbox):
        """Only the actual press recipient may begin a resize."""
        try:
            item = self._splitter_item(hitbox)
            return bool(item is not None and item.exists()
                        and item.isVisible() and item.isActive())
        except Exception:
            return False

    def _begin_file_panel_splitter_drag(self, force_new_press=False):
        if self._file_panel_splitter_dragging or self._rename_is_active():
            return False
        owner = self._file_panel_splitter_owner
        if not self._file_panel_splitter_hit_test(
                ignore_pointer_capture=force_new_press):
            return False
        if self._splitter_input_blocked(owner):
            return False
        if not self._splitter_hit_activated(getattr(self, "file_panel_separator_hitbox", None)):
            return False
        if not acquire_pointer_input(owner):
            return False
        try:
            self._file_panel_splitter_drag_start_divider = float(
                self._last_panel_divider)
            self._file_panel_splitter_drag_start_screen_x = (
                self._native_cursor_screen_x())
            drag_delta = QCursor.dragDelta().toTuple()
            self._file_panel_splitter_drag_start_delta_x = (
                float(drag_delta[0])
                if self._file_panel_splitter_drag_start_screen_x is None
                else 0.0)
            cached_file_size = getattr(self, "_file_panel_live_size", None)
            if (not cached_file_size or int(cached_file_size[0]) <= 1
                    or int(cached_file_size[1]) <= 1):
                try:
                    rect = self._splitter_item(self.top_region).globalGeometry()
                    cached_file_size = (int(rect.width()), int(rect.height()))
                except Exception:
                    cached_file_size = self._interactive_content_size()
            self._file_panel_splitter_drag_content_size = cached_file_size
            self._file_panel_splitter_last_live_width = int(round(
                float(self._last_panel_divider)))
            self._file_panel_splitter_dragging = True
            self._set_splitter_content_interactive(True)
        except Exception:
            self._file_panel_splitter_dragging = False
            release_pointer_input(owner)
            return False
        self._cancel_explorer_gestures_for_splitter()
        self._clear_splitter_selections()
        return True

    def _end_file_panel_splitter_drag(self):
        was_dragging = bool(self._file_panel_splitter_dragging)
        self._file_panel_splitter_dragging = False
        self._file_panel_splitter_drag_start_divider = 0.0
        self._file_panel_splitter_drag_start_screen_x = None
        self._file_panel_splitter_drag_start_delta_x = 0.0
        self._file_panel_splitter_drag_content_size = None
        self._file_panel_splitter_last_live_width = None
        if was_dragging:
            release_pointer_input(self._file_panel_splitter_owner)
            # One authoritative full commit after release updates Explorer
            # columns/rows and every dependent child.  Keeping this work out of
            # the mouse-move path is the key to smooth File/Server splitting.
            self._layout_dirty = True
            self._apply_split_layout(force=True, interactive=False)

    def _apply_file_panel_split_live(self, left_width, safe_width, file_height):
        """Update only File Explorer pane geometry during divider motion.

        Calling the application-wide split layout for every mouse pixel walks
        Console/Plot/Job layout state and is disproportionately expensive for
        this simple two-pane gesture.  This fast path performs six immediate
        retained-item updates and deliberately leaves ListView column/row
        reflow for the release commit.
        """
        safe_width = max(1, int(safe_width))
        file_height = max(1, int(file_height))
        gutter = int(self.FILE_PANEL_SPLITTER_GUTTER_SIZE)
        left_width = max(1, int(round(left_width)))
        right_x = left_width + gutter
        right_width = max(1, safe_width - right_x)
        line_x = left_width + (gutter - int(self.SPLITTER_SIZE)) // 2

        last = getattr(self, "_file_panel_splitter_last_live_width", None)
        if last is not None and int(last) == left_width:
            return False
        self._file_panel_splitter_last_live_width = left_width

        tags = (
            self.left_parent, self.right_parent,
            self.file_panel_separator, self.file_panel_separator_hitbox,
            self.left_status_window, self.right_status_window,
        )
        items = []
        self._splitter_live_native_updates = True
        try:
            for tag in tags:
                item = self._splitter_item(tag)
                if item is not None:
                    item.setImmediateUpdates(True)
                    items.append(item)
            self._splitter_item(self.left_parent).configure(
                pos=(0, 0), width=left_width, height=file_height, show=True)
            self._splitter_item(self.right_parent).configure(
                pos=(right_x, 0), width=right_width, height=file_height, show=True)
            self._splitter_item(self.file_panel_separator).configure(
                pos=(line_x, 0), width=self.SPLITTER_SIZE,
                height=file_height, show=True)
            self._splitter_item(self.file_panel_separator_hitbox).configure(
                pos=(left_width, 0), width=gutter,
                height=file_height, show=True)
            self._splitter_item(self.left_status_window).configure(
                pos=(0, 0), width=left_width, height=self.FILE_STATUS_HEIGHT)
            self._splitter_item(self.right_status_window).configure(
                pos=(right_x, 0), width=right_width, height=self.FILE_STATUS_HEIGHT)
            return True
        finally:
            self._splitter_live_native_updates = False
            for item in items:
                try:
                    item.setImmediateUpdates(False)
                except Exception:
                    pass

    def _drag_file_panel_splitter(self):
        if (self._splitter_input_blocked(self._file_panel_splitter_owner)
                or not self._file_panel_splitter_dragging):
            if self._file_panel_splitter_dragging:
                self._end_file_panel_splitter_drag()
            return
        try:
            current = self._native_cursor_screen_x()
            start = self._file_panel_splitter_drag_start_screen_x
            if current is not None and start is not None:
                delta = current - start
            else:
                drag_delta = QCursor.dragDelta().toTuple()
                delta = (float(drag_delta[0])
                         - self._file_panel_splitter_drag_start_delta_x)
            desired = self._file_panel_splitter_drag_start_divider + delta
            if abs(float(delta)) >= 1.0:
                self._file_panel_splitter_user_adjusted = True
            cached_size = getattr(
                self, "_file_panel_splitter_drag_content_size", None)
            if cached_size is None:
                cached_size = getattr(self, "_file_panel_live_size", None)
            if cached_size is None:
                width, height = self._interactive_content_size()
                safe_width, file_height = max(1, int(width) - 1), max(1, int(height))
            else:
                safe_width = max(1, int(cached_size[0]))
                file_height = max(1, int(cached_size[1]))
            gutter = self.FILE_PANEL_SPLITTER_GUTTER_SIZE
            if safe_width >= 2 * self.MIN_PANEL_WIDTH + gutter:
                minimum = float(self.MIN_PANEL_WIDTH)
                maximum = float(safe_width - gutter - self.MIN_PANEL_WIDTH)
            else:
                minimum = max(1.0, safe_width * 0.25)
                maximum = max(minimum, safe_width - gutter - minimum)
            new_divider = float(min(max(desired, minimum), maximum))
            if abs(new_divider - float(self._last_panel_divider)) < 0.5:
                return
            self._last_panel_divider = new_divider
            # File-panel drag has its own ultra-light live path.  Do not walk
            # the entire application docking/split layout on every mouse move.
            self._apply_file_panel_split_live(
                new_divider, safe_width, file_height)
            self._layout_dirty = True
        except Exception:
            self._end_file_panel_splitter_drag()

    def _update_file_panel_splitter_input(self):
        down = self._left_mouse_button_down()
        # With no press and no capture there is no input to arbitrate. Avoid
        # walking every protected popup/dialog for each idle splitter.
        if not down and not self._file_panel_splitter_dragging:
            self._file_panel_splitter_mouse_was_down = False
            return
        was_down = bool(self._file_panel_splitter_mouse_was_down)
        if self._splitter_input_blocked(self._file_panel_splitter_owner):
            if self._file_panel_splitter_dragging:
                self._end_file_panel_splitter_drag()
            self._file_panel_splitter_mouse_was_down = down
            return
        if (down and not was_down and not self._file_panel_splitter_dragging
                and not self._rename_is_active()
                and self._file_panel_splitter_hit_test()):
            self._begin_file_panel_splitter_drag()
        if self._file_panel_splitter_dragging:
            if down and not self._rename_is_active():
                self._drag_file_panel_splitter()
            else:
                self._end_file_panel_splitter_drag()
        self._file_panel_splitter_mouse_was_down = down

    def _update_file_panel_splitter_cursor(self):
        dragging = bool(self._file_panel_splitter_dragging)
        raw_hovered = bool(dragging or self._file_panel_splitter_hit_test(
            ignore_pointer_capture=True))
        active = bool(getattr(self, "_file_panel_splitter_cursor_active", False))
        if not raw_hovered and not active:
            return
        blocked = self._splitter_input_blocked(self._file_panel_splitter_owner)
        raw_hovered = raw_hovered and not blocked
        hovered = (False if blocked else self._stable_splitter_cursor_hover(
            "file_panel", raw_hovered, dragging))
        if hovered:
            if not active:
                try:
                    self._splitter_item(self.file_panel_separator).setTheme(
                        self._plot_splitter_hover_theme)
                except Exception:
                    pass
                QCursor.setShape(QCursor.SizeHorCursor)
                self._file_panel_splitter_cursor_active = True
            # GLFW/ImGui can restore Arrow during render. Re-assert only the
            # native cursor every frame; avoid repeatedly resetting QCursor.
            self._set_native_windows_cursor(32644, "_native_resize_ew_cursor")
        elif active:
            self._clear_splitter_cursor_hover("file_panel")
            try:
                self._splitter_item(self.file_panel_separator).setTheme(
                    self._splitter_theme)
            except Exception:
                pass
            self._file_panel_splitter_cursor_active = False
            QCursor.setShape(QCursor.ArrowCursor)
            self._set_native_windows_cursor(32512, "_native_arrow_cursor")

    def _job_view_header_owns_pointer(self, separator_only=False):
        """Return True when Job Viewer header input must beat splitters.

        The header keeps its own sort/column-resize presses. Cached header
        geometry cannot override a real ImGui activation of a gutter widget.
        """
        try:
            jobs_view = getattr(self, "jobs_view", None)
            listview = getattr(jobs_view, "listview", None)
            hit_test = getattr(listview, "header_pointer_hit_test", None)
            return bool(hit_test(separator_only=separator_only)) if callable(hit_test) else False
        except Exception:
            return False

    def _pre_dispatch_splitter_input(self):
        """Claim splitter presses before global Explorer mouse callbacks run.

        DPG callbacks are drained one frame after Dear ImGui has resolved its
        native table/splitter hit-tests.  Acquiring here reproduces Qt's mouse
        grab ordering: the divider that received the press owns the complete
        gesture before a neighbouring file row can see it.
        """
        down = self._left_mouse_button_down()
        new_press = down and not self._splitter_press_was_down
        self._splitter_press_was_down = down
        active = {item for item in (
            getattr(self, "console_separator_hitbox", None),
            getattr(self, "horizontal_splitter_hitbox", None),
            getattr(self, "job_plot_separator_hitbox", None),
            getattr(self, "file_panel_separator_hitbox", None),
        ) if self._splitter_hit_activated(item)}
        activated = active - getattr(self, "_splitter_active_hitboxes", set())
        self._splitter_active_hitboxes = active
        # Hardware state can arrive before ImGui resolves the click. Observe
        # the later activation edge instead of guessing from last-frame hover.
        if not down or not (new_press or activated) or self._rename_is_active():
            return
        # Early arbitration is not permission to steal an existing list grab
        # or interact through a dialog/popup above the divider.
        if self._splitter_input_blocked():
            return

        # Child header presses take precedence over speculative divider hits.
        # A real active gutter wins over cached header geometry after relayout.
        if self._job_view_header_owns_pointer() and not active:
            return

        # Custom splitters are authoritative DPG hitbox items.  Give them
        # priority at the one-pixel intersection with the Local/Server divider.
        if self._console_splitter_native_hovered(ignore_pointer_capture=True):
            self._begin_console_splitter_drag(force_new_press=True)
            if self._console_splitter_dragging:
                return
        if self._horizontal_splitter_native_hovered(ignore_pointer_capture=True):
            self._begin_horizontal_splitter_drag(force_new_press=True)
            if self._horizontal_splitter_dragging:
                return
        if self._job_plot_splitter_native_hovered(ignore_pointer_capture=True):
            self._begin_job_plot_splitter_drag(force_new_press=True)
            if self._plot_splitter_dragging:
                return
        self._begin_file_panel_splitter_drag(force_new_press=True)

    def _horizontal_splitter_native_hovered(
            self, ignore_pointer_capture=False):
        """Use the transparent grab item as the authoritative hit-test."""
        if (not ignore_pointer_capture
                and self._splitter_input_blocked(self._horizontal_splitter_owner)):
            return False
        hitbox = getattr(
            self, "horizontal_splitter_hitbox",
            getattr(self, "horizontal_splitter", None),
        )
        try:
            hovered = self._splitter_hit_hovered(hitbox)
            if hovered:
                return True
        except Exception:
            pass
        # A real hit on the dedicated gutter beats cached native header
        # geometry, which can still describe the header's previous position.
        if (not getattr(self, "_horizontal_splitter_dragging", False)
                and self._job_view_header_owns_pointer()):
            return False
        # Never reinterpret desktop/local coordinates until something matches:
        # that can alias a row elsewhere in the viewport onto this gutter.
        return False

    def _on_horizontal_splitter_pressed(self, sender=None, app_data=None, user_data=None):
        """Acquire the actual gutter click even if global polling missed it."""
        if self._rename_is_active() or not self._left_mouse_button_down():
            return
        self._begin_horizontal_splitter_drag(hitbox_pressed=True)

    def _begin_horizontal_splitter_drag(
            self, sender=None, app_data=None, user_data=None,
            force_new_press=False, hitbox_pressed=False):
        """Capture only the active gutter or its bound item-click callback."""
        owner = self._horizontal_splitter_owner
        if self._splitter_input_blocked(owner):
            return
        if not hitbox_pressed and not self._splitter_hit_activated(
                getattr(self, "horizontal_splitter_hitbox", None)):
            return
        if getattr(self, "_horizontal_splitter_dragging", False):
            return
        # Start only from the real transparent DPG hitbox.  The older
        # screen/local-coordinate fallback could alias another control (notably
        # the Job Viewer header) onto the splitter on mixed-DPI layouts and
        # steal its drag.  Once a drag has started we still use native cursor
        # coordinates for smooth movement, but acquisition itself is strict.
        if not hitbox_pressed and not self._horizontal_splitter_native_hovered(
                ignore_pointer_capture=force_new_press):
            return
        if not acquire_pointer_input(owner):
            return
        try:
            # Anchor the gesture to the *actual split extent*, not the hitbox
            # Y position.  The hitbox is positioned in root coordinates and can
            # therefore include an outer top Console/Plot offset; ``_top_ratio``
            # is relative to the remaining File/Job workspace.  Mixing those two
            # coordinate systems makes the divider jump on the first drag frame.
            #
            # The live values are written by ``_apply_split_layout`` after all
            # min-size clamping has been applied, so they also prevent a small
            # first-frame snap when the stored ratio does not exactly equal the
            # rendered integer top height.
            live_top = getattr(
                self, "_horizontal_splitter_live_top_height", None)
            live_size = getattr(
                self, "_horizontal_splitter_live_workspace_size", None)
            if live_top is not None and live_size is not None:
                self._horizontal_splitter_drag_start_top = float(live_top)
                self._horizontal_splitter_drag_content_size = (
                    max(1, int(live_size[0])),
                    max(1, int(live_size[1])),
                )
            else:
                # Cold-start fallback before the first complete layout.  This
                # path is normally unreachable for an interactive splitter, but
                # retaining it keeps startup/error recovery defensive.
                self._horizontal_splitter_drag_start_top = float(
                    self._splitter_item(
                        self.horizontal_splitter_hitbox).pos().toTuple()[1])
                self._horizontal_splitter_drag_content_size = (
                    self._interactive_content_size())
            self._horizontal_splitter_drag_start_screen_y = (
                self._native_cursor_screen_y())
            if self._horizontal_splitter_drag_start_screen_y is None:
                drag_delta = QCursor.dragDelta().toTuple()
                self._horizontal_splitter_drag_start_delta_y = float(
                    drag_delta[1])
            else:
                self._horizontal_splitter_drag_start_delta_y = 0.0
            self._horizontal_splitter_dragging = True
        except Exception:
            self._horizontal_splitter_dragging = False
            self._horizontal_splitter_drag_offset = 0.0
            self._horizontal_splitter_mouse_adjustment = 0.0
            release_pointer_input(owner)
            return
        self._cancel_explorer_gestures_for_splitter()
        self._clear_splitter_selections()

    def _end_horizontal_splitter_drag(
            self, sender=None, app_data=None, user_data=None):
        was_dragging = bool(getattr(
            self, "_horizontal_splitter_dragging", False))
        self._horizontal_splitter_dragging = False
        self._horizontal_splitter_drag_offset = 0.0
        self._horizontal_splitter_mouse_adjustment = 0.0
        self._horizontal_splitter_drag_start_top = 0.0
        self._horizontal_splitter_drag_start_delta_y = 0.0
        self._horizontal_splitter_drag_start_screen_y = None
        self._horizontal_splitter_drag_content_size = None
        if was_dragging:
            release_pointer_input(self._horizontal_splitter_owner)
            # Run the expensive ListView/column layout only once after the
            # lightweight interactive resize has finished.
            self._layout_dirty = True

    def _update_horizontal_splitter_cursor(self):
        """Keep ResizeNS visible only while the splitter really owns input."""
        dragging = bool(self._horizontal_splitter_dragging)
        raw_hovered = bool(dragging or self._horizontal_splitter_native_hovered(
            ignore_pointer_capture=True))
        if not raw_hovered and not getattr(self, '_splitter_cursor_active', False):
            return
        blocked = self._splitter_input_blocked(
            self._horizontal_splitter_owner)
        raw_hovered = raw_hovered and not blocked
        hovered = (False if blocked else self._stable_splitter_cursor_hover(
            "horizontal", raw_hovered, dragging))
        if hovered and not getattr(self, "_splitter_cursor_active", False):
            try:
                self._splitter_item(self.horizontal_splitter).setTheme(
                    self._plot_splitter_hover_theme)
            except Exception:
                pass
            self._show_horizontal_splitter_cursor()
        if hovered:
            self._set_native_windows_cursor(32645, "_native_resize_ns_cursor")
        elif not hovered and getattr(
                self, "_splitter_cursor_active", False):
            try:
                self._splitter_item(self.horizontal_splitter).setTheme(
                    self._splitter_theme)
            except Exception:
                pass
            plot_owns_cursor = (
                not self._splitter_input_blocked(self._plot_splitter_owner)
                and (getattr(self, "_plot_splitter_dragging", False)
                     or self._job_plot_splitter_native_hovered())
            )
            if not plot_owns_cursor:
                QCursor.setShape(QCursor.ArrowCursor)
                self._set_native_windows_cursor(
                    32512, "_native_arrow_cursor")  # IDC_ARROW
            self._splitter_cursor_active = False
            self._clear_splitter_cursor_hover("horizontal")

    def _update_horizontal_splitter_input(self):
        """Poll mouse state so splitter dragging survives missed callbacks."""
        down = self._left_mouse_button_down()
        if not down and not self._horizontal_splitter_dragging:
            self._horizontal_splitter_mouse_was_down = False
            return
        if self._splitter_input_blocked(self._horizontal_splitter_owner):
            if getattr(self, "_horizontal_splitter_dragging", False):
                self._end_horizontal_splitter_drag()
            self._horizontal_splitter_mouse_was_down = down
            return
        was_down = bool(getattr(
            self, "_horizontal_splitter_mouse_was_down", False))
        dragging = bool(getattr(
            self, "_horizontal_splitter_dragging", False))
        # Capture only a newly pressed button while the *real* splitter hitbox
        # owns the pointer. Never infer a new splitter gesture from transformed
        # screen/local coordinates after another widget already accepted it.
        if (down and not was_down and not dragging and
                not self._rename_is_active() and
                self._horizontal_splitter_native_hovered()):
            self._begin_horizontal_splitter_drag()
            dragging = bool(getattr(
                self, "_horizontal_splitter_dragging", False))
        if dragging:
            if down and not self._rename_is_active():
                self._drag_horizontal_splitter()
            else:
                self._end_horizontal_splitter_drag()
        self._horizontal_splitter_mouse_was_down = down

    def _rename_is_active(self):
        """Return whether either file panel currently owns rename input."""
        return any(
            bool(getattr(panel.listview, "_rename_active", False))
            for panel in getattr(self, "panels", ())
            if getattr(panel, "listview", None) is not None
        )

    @classmethod
    def _normalize_plot_dock_area(cls, area):
        value = str(area or "right").strip().lower()
        return value if value in cls.PLOT_DOCK_AREAS else "right"

    def _plot_dock_is_vertical_split(self, area=None):
        """Return True when the dock divides the workspace left/right."""
        area = self._normalize_plot_dock_area(
            self._plot_dock_area if area is None else area)
        return area in ("left", "right")

    def _plot_ratio_for_area(self, area=None):
        area = self._normalize_plot_dock_area(
            self._plot_dock_area if area is None else area)
        ratio = float(self._plot_split_ratios.get(
            area, self.PLOT_DOCK_DEFAULT_RATIO))
        return clamp_ratio(ratio, 0.0, 1.0)

    def _set_plot_ratio_for_area(self, ratio, area=None):
        area = self._normalize_plot_dock_area(
            self._plot_dock_area if area is None else area)
        ratio = clamp_ratio(ratio, 0.0, 1.0)
        self._plot_split_ratios[area] = ratio
        self._plot_split_ratio = ratio

    def _plot_split_widths(self, total_width, area=None):
        """Return clamped Job Viewer / Plots widths for Left/Right docking."""
        area = self._normalize_plot_dock_area(
            self._plot_dock_area if area is None else area)
        available = max(2, int(total_width) - self.PLOT_DOCK_SEPARATOR_SIZE)
        # Preserve the historical policy while delegating its bounds to the
        # generic core: desired = int(round(available * self._plot_ratio_for_area(area))).
        job_width = split_extent(
            total_width,
            self._plot_ratio_for_area(area),
            separator_size=self.PLOT_DOCK_SEPARATOR_SIZE,
            min_first=self.MIN_JOB_VIEWER_WIDTH,
            min_second=self.MIN_PLOT_DOCK_WIDTH,
            min_ratio=0.0, max_ratio=1.0,
        ).first
        plot_width = max(1, available - job_width)
        return job_width, plot_width

    def _plot_split_heights(self, total_height, area=None):
        """Return clamped Job Viewer / Plots heights for Top/Bottom docking."""
        area = self._normalize_plot_dock_area(
            self._plot_dock_area if area is None else area)
        available = max(2, int(total_height) - self.PLOT_DOCK_SEPARATOR_SIZE)
        # Same ratio contract as width splitting; only host minimums differ.
        job_height = split_extent(
            total_height,
            self._plot_ratio_for_area(area),
            separator_size=self.PLOT_DOCK_SEPARATOR_SIZE,
            min_first=self.MIN_JOB_VIEWER_DOCK_HEIGHT,
            min_second=self.MIN_PLOT_DOCK_HEIGHT,
            min_ratio=0.0, max_ratio=1.0,
        ).first
        plot_height = max(1, available - job_height)
        return job_height, plot_height

    def _console_splitter_native_hovered(
            self, ignore_pointer_capture=False):
        if not self._console_dock_visible:
            return False
        if (not ignore_pointer_capture
                and self._splitter_input_blocked(self._console_splitter_owner)):
            return False
        hitbox = getattr(self, "console_separator_hitbox", None)
        try:
            hovered = self._splitter_hit_hovered(hitbox)
            if hovered:
                return True
        except Exception:
            pass
        return False

    def _begin_console_splitter_drag(self, force_new_press=False):
        owner = self._console_splitter_owner
        if not self._console_dock_visible or self._console_splitter_dragging:
            return
        if self._splitter_input_blocked(owner):
            return
        if not self._splitter_hit_activated(getattr(self, "console_separator_hitbox", None)):
            return
        if not self._console_splitter_native_hovered(
                ignore_pointer_capture=force_new_press):
            return
        if not acquire_pointer_input(owner):
            return
        try:
            area = self._normalize_console_dock_area(
                getattr(self, "_console_dock_area", "bottom"))
            rect = self._splitter_item(self.console_region).globalGeometry()
            if area in ("left", "right"):
                self._console_splitter_drag_start_extent = float(rect.width())
                self._console_splitter_drag_start_screen = self._native_cursor_screen_x()
                drag_delta = QCursor.dragDelta().toTuple()
                self._console_splitter_drag_start_delta = (
                    float(drag_delta[0])
                    if self._console_splitter_drag_start_screen is None else 0.0)
            else:
                self._console_splitter_drag_start_extent = float(rect.height())
                self._console_splitter_drag_start_screen = self._native_cursor_screen_y()
                drag_delta = QCursor.dragDelta().toTuple()
                self._console_splitter_drag_start_delta = (
                    float(drag_delta[1])
                    if self._console_splitter_drag_start_screen is None else 0.0)
            self._console_splitter_drag_content_size = self._interactive_content_size()
            self._console_splitter_drag_horizontal_split_y = None
            if (area in ("top", "bottom")
                    and str(getattr(self, "_console_dock_scope", "inner") or "inner").strip().lower() != "outer"):
                try:
                    self._console_splitter_drag_horizontal_split_y = float(
                        self._splitter_item(
                            self.horizontal_splitter_hitbox).pos().toTuple()[1])
                except Exception:
                    self._console_splitter_drag_horizontal_split_y = None
            self._console_splitter_dragging = True
        except Exception:
            self._console_splitter_dragging = False
            release_pointer_input(owner)
            return
        self._cancel_explorer_gestures_for_splitter()
        self._clear_splitter_selections()

    def _end_console_splitter_drag(self):
        was_dragging = bool(self._console_splitter_dragging)
        self._console_splitter_dragging = False
        self._console_splitter_drag_start_extent = 0.0
        self._console_splitter_drag_start_screen = None
        self._console_splitter_drag_content_size = None
        self._console_splitter_drag_horizontal_split_y = None
        self._console_splitter_drag_start_delta = 0.0
        if was_dragging:
            release_pointer_input(self._console_splitter_owner)
            self._layout_dirty = True
            persist_dock = getattr(self, "_persist_dock_state", None)
            if callable(persist_dock):
                persist_dock()

    def _drag_console_splitter(self):
        if (self._splitter_input_blocked(self._console_splitter_owner)
                or not self._console_splitter_dragging
                or not self._console_dock_visible):
            if self._console_splitter_dragging:
                self._end_console_splitter_drag()
            return
        try:
            area = self._normalize_console_dock_area(
                getattr(self, "_console_dock_area", "bottom"))
            horizontal = area in ("left", "right")
            current = (self._native_cursor_screen_x() if horizontal
                       else self._native_cursor_screen_y())
            start = self._console_splitter_drag_start_screen
            if current is not None and start is not None:
                delta = current - start
            else:
                drag_delta = QCursor.dragDelta().toTuple()
                axis_delta = float(drag_delta[0] if horizontal else drag_delta[1])
                delta = axis_delta - self._console_splitter_drag_start_delta
            sign = 1.0 if area in ("left", "top") else -1.0
            desired = self._console_splitter_drag_start_extent + sign * delta
            cached_size = getattr(
                self, "_console_splitter_drag_content_size", None)
            width, height = cached_size or self._interactive_content_size()
            if horizontal:
                minimum_workspace = self.MIN_JOB_VIEWER_WIDTH
                if str(getattr(self, "_console_dock_scope", "inner")).lower() == "outer":
                    minimum_workspace = max(minimum_workspace,
                                            self.MIN_PANEL_WIDTH * 2 + self.FILE_PANEL_SPLITTER_GUTTER_SIZE)
                if (self._job_plot_dock_visible()
                        and self._plot_dock_is_vertical_split(self._plot_dock_area)):
                    minimum_workspace = max(
                        minimum_workspace,
                        self.MIN_JOB_VIEWER_WIDTH + self.MIN_PLOT_DOCK_WIDTH
                        + self.PLOT_DOCK_SEPARATOR_SIZE)
                maximum = max(
                    1.0, float(width) - minimum_workspace
                    - self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE)
                minimum = (float(self.MIN_CONSOLE_DOCK_WIDTH)
                           if maximum >= self.MIN_CONSOLE_DOCK_WIDTH
                           else max(1.0, maximum * 0.35))
                new_extent = int(min(max(desired, minimum), maximum))
                if new_extent == int(getattr(self, "_console_dock_width", 0)):
                    return
                self._console_dock_width = new_extent
            else:
                outer_scope = str(
                    getattr(self, "_console_dock_scope", "inner") or "inner"
                ).strip().lower() == "outer"
                if outer_scope:
                    lower_total = float(height)
                    minimum_workspace = (self.MIN_TOP_HEIGHT + self.MIN_BOTTOM_HEIGHT
                                         + self.FILE_JOB_SPLITTER_GUTTER_SIZE + 1)
                else:
                    split_y = getattr(
                        self, "_console_splitter_drag_horizontal_split_y", None)
                    if split_y is None:
                        split_y = float(self._splitter_item(
                            self.horizontal_splitter_hitbox).pos().toTuple()[1])
                    lower_total = max(
                        2.0, float(height) - split_y
                        - self.FILE_JOB_SPLITTER_GUTTER_SIZE - 1.0)
                    minimum_workspace = self.MIN_BOTTOM_HEIGHT
                    if (self._job_plot_dock_visible()
                            and not self._plot_dock_is_vertical_split(
                                self._plot_dock_area)):
                        minimum_workspace = max(
                            minimum_workspace,
                            self.MIN_JOB_VIEWER_DOCK_HEIGHT
                            + self.MIN_PLOT_DOCK_HEIGHT
                            + self.PLOT_DOCK_SEPARATOR_SIZE)
                maximum = max(
                    1.0, lower_total - minimum_workspace
                    - self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE)
                minimum = (float(self.MIN_CONSOLE_DOCK_HEIGHT)
                           if maximum >= self.MIN_CONSOLE_DOCK_HEIGHT
                           else max(1.0, maximum * 0.35))
                new_extent = int(min(max(desired, minimum), maximum))
                if new_extent == int(self._console_dock_height):
                    return
                self._console_dock_height = new_extent
            self._layout_dirty = True
            self._apply_split_layout(force=True, interactive=True)
        except Exception:
            self._end_console_splitter_drag()

    def _update_console_splitter_input(self):
        down = self._left_mouse_button_down()
        if not down and not self._console_splitter_dragging:
            self._console_splitter_mouse_was_down = False
            return
        if not self._console_dock_visible:
            if self._console_splitter_dragging:
                self._end_console_splitter_drag()
            self._console_splitter_mouse_was_down = down
            return
        if self._splitter_input_blocked(self._console_splitter_owner):
            if self._console_splitter_dragging:
                self._end_console_splitter_drag()
            self._console_splitter_mouse_was_down = down
            return
        was_down = bool(self._console_splitter_mouse_was_down)
        if (down and not was_down and not self._console_splitter_dragging
                and not self._rename_is_active()
                and self._console_splitter_native_hovered()):
            self._begin_console_splitter_drag()
        if self._console_splitter_dragging:
            if down and not self._rename_is_active():
                self._drag_console_splitter()
            else:
                self._end_console_splitter_drag()
        self._console_splitter_mouse_was_down = down

    def _update_console_splitter_cursor(self):
        dragging = bool(self._console_splitter_dragging)
        raw_hovered = bool(self._console_dock_visible and (
            dragging or self._console_splitter_native_hovered(
                ignore_pointer_capture=True)))
        active = bool(getattr(self, '_console_splitter_cursor_active', False))
        if not raw_hovered and not active:
            return
        blocked = self._splitter_input_blocked(self._console_splitter_owner)
        raw_hovered = raw_hovered and not blocked
        hovered = (False if blocked else self._stable_splitter_cursor_hover(
            "console", raw_hovered, dragging))
        area = self._normalize_console_dock_area(
            getattr(self, "_console_dock_area", "bottom"))
        horizontal = area in ("left", "right")
        if hovered:
            if not active:
                try:
                    self._splitter_item(self.console_separator).setTheme(
                        self._plot_splitter_hover_theme)
                except Exception:
                    pass
                self._console_splitter_cursor_active = True
            # Keep ImGui, post-render Win32 updates and WM_SETCURSOR on the
            # same orientation, including a dock-area change while hovered.
            QCursor.setShape(
                QCursor.SizeHorCursor if horizontal else QCursor.SizeVerCursor)
            self._set_native_windows_cursor(
                32644 if horizontal else 32645,
                "_native_resize_ew_cursor" if horizontal
                else "_native_resize_ns_cursor")
        elif active:
            try:
                self._splitter_item(self.console_separator).setTheme(
                    self._splitter_theme)
            except Exception:
                pass
            other_owns_cursor = (
                (not self._splitter_input_blocked(
                    self._horizontal_splitter_owner)
                 and (self._horizontal_splitter_dragging
                      or self._horizontal_splitter_native_hovered()))
                or
                (not self._splitter_input_blocked(self._plot_splitter_owner)
                 and (self._plot_splitter_dragging
                      or self._job_plot_splitter_native_hovered())))
            if not other_owns_cursor:
                QCursor.setShape(QCursor.ArrowCursor)
                self._set_native_windows_cursor(
                    32512, "_native_arrow_cursor")  # IDC_ARROW
            self._console_splitter_cursor_active = False
            self._clear_splitter_cursor_hover("console")

    def _job_plot_dock_visible(self):
        manager = getattr(self, "plot_dock_manager", None)
        if manager is not None:
            try:
                if manager.has_docked():
                    return True
            except Exception:
                pass
            # A manager can survive after the last Plot is closed. Do not let
            # that stale, empty manager suppress the explicit View -> Plots
            # request for an empty Plot workspace. Conversely, when a live Plot
            # exists but is hidden/floating, manager.has_docked() == False and
            # the embedded region must stay closed.
            live = False
            for window in getattr(self, "job_plot_windows", {}).values():
                try:
                    if window is not None and window.exists():
                        live = True
                        break
                except Exception:
                    continue
            if live:
                return False
        return bool(getattr(self, "_plot_dock_open", False))

    def _job_plot_splitter_native_hovered(
            self, ignore_pointer_capture=False):
        if (not ignore_pointer_capture
                and self._splitter_input_blocked(self._plot_splitter_owner)):
            return False
        hitbox = getattr(self, "job_plot_separator_hitbox", None)
        try:
            hovered = bool(self._job_plot_dock_visible() and self._splitter_hit_hovered(hitbox))
            if hovered:
                return True
        except Exception:
            pass
        return False

    def _show_job_plot_splitter_cursor(self):
        vertical_split = self._plot_dock_is_vertical_split()
        QCursor.setShape(
            QCursor.SizeHorCursor if vertical_split else QCursor.SizeVerCursor)
        if vertical_split:
            self._set_native_windows_cursor(
                32644, "_native_resize_ew_cursor")  # IDC_SIZEWE
        else:
            self._set_native_windows_cursor(
                32645, "_native_resize_ns_cursor")  # IDC_SIZENS
        self._plot_splitter_cursor_active = True

    def _begin_job_plot_splitter_drag(self, force_new_press=False):
        owner = self._plot_splitter_owner
        if (not self._job_plot_dock_visible()
                or self._plot_splitter_dragging):
            return
        if self._splitter_input_blocked(owner):
            return
        if not self._splitter_hit_activated(getattr(self, "job_plot_separator_hitbox", None)):
            return
        if not self._job_plot_splitter_native_hovered(
                ignore_pointer_capture=force_new_press):
            return
        if not acquire_pointer_input(owner):
            return
        try:
            job_rect = self._splitter_item(self.bottom_region).globalGeometry()
            plot_rect = self._splitter_item(self.plot_region).globalGeometry()
            job_w, job_h = float(job_rect.width()), float(job_rect.height())
            plot_w, plot_h = float(plot_rect.width()), float(plot_rect.height())
            self._plot_splitter_drag_start_width = job_w
            self._plot_splitter_drag_start_height = job_h
            self._plot_splitter_drag_available_width = max(2.0, job_w + plot_w)
            self._plot_splitter_drag_available_height = max(2.0, job_h + plot_h)
            drag_delta = QCursor.dragDelta().toTuple()
            if self._plot_dock_is_vertical_split():
                self._plot_splitter_drag_start_screen_x = (
                    self._native_cursor_screen_x())
                self._plot_splitter_drag_start_screen_y = None
                self._plot_splitter_drag_start_delta_x = (
                    float(drag_delta[0])
                    if self._plot_splitter_drag_start_screen_x is None else 0.0)
                self._plot_splitter_drag_start_delta_y = 0.0
            else:
                self._plot_splitter_drag_start_screen_y = (
                    self._native_cursor_screen_y())
                self._plot_splitter_drag_start_screen_x = None
                self._plot_splitter_drag_start_delta_y = (
                    float(drag_delta[1])
                    if self._plot_splitter_drag_start_screen_y is None else 0.0)
                self._plot_splitter_drag_start_delta_x = 0.0
            self._plot_splitter_dragging = True
        except Exception:
            self._plot_splitter_dragging = False
            release_pointer_input(owner)
            return
        self._cancel_explorer_gestures_for_splitter()
        self._clear_splitter_selections()

    def _end_job_plot_splitter_drag(self):
        was_dragging = bool(self._plot_splitter_dragging)
        self._plot_splitter_dragging = False
        self._plot_splitter_drag_start_width = 0.0
        self._plot_splitter_drag_start_height = 0.0
        self._plot_splitter_drag_available_width = 0.0
        self._plot_splitter_drag_available_height = 0.0
        self._plot_splitter_drag_start_delta_x = 0.0
        self._plot_splitter_drag_start_delta_y = 0.0
        self._plot_splitter_drag_start_screen_x = None
        self._plot_splitter_drag_start_screen_y = None
        if was_dragging:
            release_pointer_input(self._plot_splitter_owner)
            self._layout_dirty = True
            persist_dock = getattr(self, "_persist_dock_state", None)
            if callable(persist_dock):
                persist_dock()

    def _drag_job_plot_splitter(self):
        blocked = self._splitter_input_blocked(self._plot_splitter_owner)
        if (blocked
                or not self._plot_splitter_dragging
                or not self._job_plot_dock_visible()):
            if blocked:
                self._end_job_plot_splitter_drag()
            return
        try:
            area = self._normalize_plot_dock_area(self._plot_dock_area)
            drag_delta = QCursor.dragDelta().toTuple()
            if self._plot_dock_is_vertical_split(area):
                current = self._native_cursor_screen_x()
                start = self._plot_splitter_drag_start_screen_x
                delta = (current - start if current is not None and start is not None
                         else float(drag_delta[0])
                         - self._plot_splitter_drag_start_delta_x)
                # Right: moving separator right grows Job Viewer. Left: moving
                # separator right grows the Plot dock and shrinks Job Viewer.
                sign = 1.0 if area == "right" else -1.0
                desired = self._plot_splitter_drag_start_width + sign * delta
                available = max(2, int(self._plot_splitter_drag_available_width))
                if available >= self.MIN_JOB_VIEWER_WIDTH + self.MIN_PLOT_DOCK_WIDTH:
                    minimum = self.MIN_JOB_VIEWER_WIDTH
                    maximum = available - self.MIN_PLOT_DOCK_WIDTH
                else:
                    minimum = max(1, int(round(available * 0.30)))
                    maximum = max(minimum, int(round(available * 0.70)))
                job_size = min(max(desired, minimum), maximum)
            else:
                current = self._native_cursor_screen_y()
                start = self._plot_splitter_drag_start_screen_y
                delta = (current - start if current is not None and start is not None
                         else float(drag_delta[1])
                         - self._plot_splitter_drag_start_delta_y)
                # Bottom: moving down grows Job Viewer. Top: moving down grows
                # the Plot dock and therefore shrinks Job Viewer.
                sign = 1.0 if area == "bottom" else -1.0
                desired = self._plot_splitter_drag_start_height + sign * delta
                available = max(2, int(self._plot_splitter_drag_available_height))
                if (available >= self.MIN_JOB_VIEWER_DOCK_HEIGHT
                        + self.MIN_PLOT_DOCK_HEIGHT):
                    minimum = self.MIN_JOB_VIEWER_DOCK_HEIGHT
                    maximum = available - self.MIN_PLOT_DOCK_HEIGHT
                else:
                    minimum = max(1, int(round(available * 0.30)))
                    maximum = max(minimum, int(round(available * 0.70)))
                job_size = min(max(desired, minimum), maximum)
            ratio = float(job_size) / float(available)
            if abs(ratio - float(self._plot_ratio_for_area(area))) < (0.5 / float(available)):
                return
            self._set_plot_ratio_for_area(ratio, area)
            self._layout_dirty = True
            self._apply_split_layout(force=True, interactive=True)
        except Exception:
            self._end_job_plot_splitter_drag()

    def _update_job_plot_splitter_input(self):
        down = self._left_mouse_button_down()
        if not down and not self._plot_splitter_dragging:
            self._plot_splitter_mouse_was_down = False
            return
        if not self._job_plot_dock_visible():
            if self._plot_splitter_dragging:
                self._end_job_plot_splitter_drag()
            self._plot_splitter_mouse_was_down = down
            return
        if self._splitter_input_blocked(self._plot_splitter_owner):
            if self._plot_splitter_dragging:
                self._end_job_plot_splitter_drag()
            self._plot_splitter_mouse_was_down = down
            return
        was_down = bool(self._plot_splitter_mouse_was_down)
        if (down and not was_down and not self._plot_splitter_dragging
                and not self._rename_is_active()
                and self._job_plot_splitter_native_hovered()):
            self._begin_job_plot_splitter_drag()
        if self._plot_splitter_dragging:
            if down and not self._rename_is_active():
                self._drag_job_plot_splitter()
            else:
                self._end_job_plot_splitter_drag()
        self._plot_splitter_mouse_was_down = down

    def _update_job_plot_splitter_cursor(self):
        dragging = bool(self._plot_splitter_dragging)
        raw_hovered = bool(dragging or self._job_plot_splitter_native_hovered(
            ignore_pointer_capture=True))
        if not raw_hovered and not getattr(self, '_plot_splitter_cursor_active', False):
            return
        blocked = self._splitter_input_blocked(self._plot_splitter_owner)
        raw_hovered = raw_hovered and not blocked
        hovered = (False if blocked else self._stable_splitter_cursor_hover(
            "plot", raw_hovered, dragging))
        if hovered and not self._plot_splitter_cursor_active:
            self._show_job_plot_splitter_cursor()
            try:
                self._splitter_item(self.job_plot_separator).setTheme(
                    self._plot_splitter_hover_theme)
            except Exception:
                pass
        if hovered:
            vertical_split = self._plot_dock_is_vertical_split()
            self._set_native_windows_cursor(
                32644 if vertical_split else 32645,
                "_native_resize_ew_cursor" if vertical_split
                else "_native_resize_ns_cursor")
        elif not hovered and self._plot_splitter_cursor_active:
            try:
                self._splitter_item(self.job_plot_separator).setTheme(
                    self._splitter_theme)
            except Exception:
                pass
            horizontal_owns_cursor = (
                not self._splitter_input_blocked(
                    self._horizontal_splitter_owner)
                and (getattr(self, "_horizontal_splitter_dragging", False)
                     or self._horizontal_splitter_native_hovered())
            )
            if not horizontal_owns_cursor:
                QCursor.setShape(QCursor.ArrowCursor)
                self._set_native_windows_cursor(
                    32512, "_native_arrow_cursor")  # IDC_ARROW
            self._plot_splitter_cursor_active = False
            self._clear_splitter_cursor_hover("plot")

    def _drag_horizontal_splitter(self, sender=None, app_data=None):
        blocked = self._splitter_input_blocked(
            self._horizontal_splitter_owner)
        if (blocked or
                not getattr(self, "_horizontal_splitter_dragging", False)):
            if blocked:
                self._end_horizontal_splitter_drag()
            return
        try:
            current_screen_y = self._native_cursor_screen_y()
            start_screen_y = self._horizontal_splitter_drag_start_screen_y
            if current_screen_y is not None and start_screen_y is not None:
                delta_y = current_screen_y - start_screen_y
            else:
                drag_delta = QCursor.dragDelta().toTuple()
                delta_y = (
                    float(drag_delta[1])
                    - self._horizontal_splitter_drag_start_delta_y)
            mouse_y = self._horizontal_splitter_drag_start_top + delta_y
            cached_size = getattr(
                self, "_horizontal_splitter_drag_content_size", None)
            _width, height = cached_size or self._interactive_content_size()
            minimum = self.MIN_TOP_HEIGHT
            minimum_bottom = self.MIN_BOTTOM_HEIGHT

            # Match the exact lower-workspace constraints used by
            # ``_apply_split_layout``.  Outer/floating docks are outside this
            # File/Job split and must never shrink its drag range; counting them
            # here made the divider snap upward as soon as mouse-down began.
            plot_visible = bool(self._job_plot_dock_visible())
            plot_outer = bool(
                plot_visible
                and str(getattr(self, "_plot_dock_scope", "inner") or "inner")
                .strip().lower() == "outer")
            if (plot_visible and not plot_outer
                    and not self._plot_dock_is_vertical_split(
                        self._plot_dock_area)):
                minimum_bottom = max(
                    minimum_bottom,
                    self.MIN_JOB_VIEWER_DOCK_HEIGHT
                    + self.MIN_PLOT_DOCK_HEIGHT
                    + self.PLOT_DOCK_SEPARATOR_SIZE)

            console_visible = bool(
                getattr(self, "_console_dock_visible", False)
                and getattr(self, "_console_dock_mode", "docked") == "docked")
            console_outer = bool(
                console_visible
                and str(getattr(self, "_console_dock_scope", "inner") or "inner")
                .strip().lower() == "outer")
            console_area = self._normalize_console_dock_area(
                getattr(self, "_console_dock_area", "bottom"))
            if (console_visible and not console_outer
                    and console_area in ("top", "bottom")):
                minimum_bottom += (
                    self.MIN_CONSOLE_DOCK_HEIGHT
                    + self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE)
            maximum = max(
                minimum,
                height - minimum_bottom
                - self.FILE_JOB_SPLITTER_GUTTER_SIZE - 1,
            )
            top = min(max(mouse_y, minimum), maximum)
            # Compare against the rendered divider position, not a ratio-derived
            # approximation.  Integer layout/clamping can make ``ratio * height``
            # differ from the current handle by a few pixels even before the
            # mouse moves; treating that difference as a drag causes the visible
            # press-time jump reported on the File/Job splitter.
            live_top = getattr(
                self, "_horizontal_splitter_live_top_height", None)
            if live_top is None:
                current_top = int(round(
                    float(self._top_ratio) * max(1.0, height)))
            else:
                current_top = int(round(float(live_top)))
            if int(round(top)) == current_top:
                return
            self._top_ratio = top / max(1.0, height)
            self._layout_dirty = True
            self._apply_split_layout(force=True, interactive=True)
        except Exception:
            self._end_horizontal_splitter_drag()

    def _drag_vertical_splitter(self, sender=None, app_data=None):
        return self._drag_horizontal_splitter(sender, app_data)

    def _interactive_content_size(self):
        """Return cached layout size without a renderer geometry round-trip.

        Splitter drags run once per rendered frame.  Querying global native
        geometry in every drag sample is unnecessary because the workspace size
        is stable for the gesture (or is already supplied by the viewport resize
        callback).  Fall back to the real geometry only before the first layout.
        """
        pending = getattr(self, "_pending_viewport_size", None)
        if pending is not None:
            return max(1, int(pending[0])), max(1, int(pending[1]))
        cached = getattr(self, "_last_content_size", (0, 0))
        if cached and int(cached[0]) > 1 and int(cached[1]) > 1:
            return int(cached[0]), int(cached[1])
        return self._content_size()

    def _content_size(self):
        """Return the real drawable size of the dedicated layout root."""
        try:
            root = getattr(self, "_layout_root_frame", None)
            rect = root.globalGeometry() if root is not None else None
            width = int(rect.width()) if rect is not None else 0
            height = int(rect.height()) if rect is not None else 0
            if width > 1 and height > 1:
                return width, height
        except Exception:
            pass

        # During the first frame the retained root may not have geometry yet.
        # QScreen keeps the renderer viewport query inside DearUIQt.
        try:
            app = QApplication.instance()
            rect = app.primaryScreen().availableGeometry() if app is not None else None
            width = int(rect.width()) if rect is not None else self.WIDTH
            height = int(rect.height()) if rect is not None else self.HEIGHT
        except Exception:
            width, height = self.WIDTH, self.HEIGHT
        return max(1, width), max(1, height)

    def _layout_items_exist(self):
        return all(self._splitter_item(item).exists() for item in (
            self.top_region,
            self.file_panels_table,
            self.left_parent,
            self.right_parent,
            self.file_panel_separator,
            self.file_panel_separator_hitbox,
            self.file_status_region,
            self.bottom_region,
            self.plot_region,
            self.console_region,
            self.console_separator,
            self.console_separator_hitbox,
            self.job_plot_separator,
            self.job_plot_separator_hitbox,
            self.horizontal_splitter,
            self.horizontal_splitter_hitbox,
        ))

    def _apply_split_layout(self, force=False, interactive=False):
        """Resize the split workspace with a cheap live-interaction path.

        Geometry of the retained pane roots is inexpensive; reflowing Explorer
        ListViews, Job Viewer columns, console widgets and plots is not.  During
        splitter drags and native viewport resizing we therefore move/resize only
        the pane roots.  Child content is clipped/fill-sized by its parent and is
        fully reflowed once the gesture settles, closely matching Qt's deferred
        expensive-layout behaviour.
        """
        if self._layout_updating or not self._alive or not self._layout_items_exist():
            return

        now = time.monotonic()
        live_viewport_resize = bool(
            self._resize_last_event
            and now - self._resize_last_event < self._resize_settle_delay
        )
        file_dragging = bool(getattr(self, "_file_panel_splitter_dragging", False))
        other_dragging = any(bool(getattr(self, name, False)) for name in (
            "_horizontal_splitter_dragging", "_console_splitter_dragging", "_plot_splitter_dragging"))
        if file_dragging and not other_dragging and not force and not live_viewport_resize:
            # The file splitter already applied its six-item live geometry
            # update before this frame's dirty-layout pass. Do not immediately
            # undo that fast path with a full application/content reflow.
            # Keep dirty until _end_file_panel_splitter_drag commits once.
            return
        if file_dragging or other_dragging:
            interactive = True
        if not force and live_viewport_resize:
            last_live = float(getattr(self, "_last_live_resize_layout", 0.0) or 0.0)
            interval = float(getattr(self, "_resize_live_interval", 1.0 / 60.0))
            if now - last_live < interval:
                return
            self._last_live_resize_layout = now
            interactive = True

        pending = getattr(self, "_pending_viewport_size", None)
        if pending is not None and (live_viewport_resize or self._resize_last_event):
            width, height = pending
        else:
            width, height = self._content_size()
        width, height = max(1, int(width)), max(1, int(height))
        if not force and not self._layout_dirty and self._last_content_size == (width, height):
            return

        self._layout_updating = True
        self._splitter_live_native_updates = bool(interactive)
        self._set_splitter_content_interactive(interactive)
        try:
            self._last_content_size = (width, height)
            # A live native resize must remain dirty until one non-interactive
            # pass commits child layouts after the WM_SIZE stream goes quiet.
            self._layout_dirty = bool(live_viewport_resize)
            if not live_viewport_resize:
                self._pending_viewport_size = None
                self._resize_last_event = 0.0

            plot_visible = self._job_plot_dock_visible()
            console_visible = bool(
                self._console_dock_visible
                and self._console_dock_mode == "docked")
            console_scope = str(
                getattr(self, "_console_dock_scope", "inner") or "inner"
            ).strip().lower()
            console_outer = bool(console_visible and console_scope == "outer")

            # Outer docking is a root-level split: the Console consumes one
            # edge of the entire WinUx content area, and the ordinary file/job
            # workspace is laid out in the remaining rectangle.  Inner docking
            # keeps the historical lower-workspace behavior.
            root_width, root_height = width, height
            content_x = 0
            content_y = 0
            content_width = root_width
            content_height = root_height
            outer_console_size = None
            if console_outer:
                console_area = self._normalize_console_dock_area(
                    getattr(self, "_console_dock_area", "bottom"))
                try:
                    self.console_dock.set_dock_area(console_area)
                except Exception:
                    pass
                if console_area in ("left", "right"):
                    minimum_content = self.MIN_PANEL_WIDTH * 2 + self.FILE_PANEL_SPLITTER_GUTTER_SIZE
                    available = max(
                        1, root_width - minimum_content
                        - self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE)
                    console_width = min(
                        max(self.MIN_CONSOLE_DOCK_WIDTH,
                            int(getattr(self, "_console_dock_width",
                                        self.CONSOLE_DOCK_DEFAULT_WIDTH))),
                        available)
                    content_width = max(
                        1, root_width - console_width
                        - self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE)
                    if console_area == "left":
                        console_x = content_x
                        gutter_x = console_width
                        content_x = gutter_x + self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE
                    else:
                        content_x = 0
                        gutter_x = content_width
                        console_x = gutter_x + self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE
                    line_x = (gutter_x
                        + (self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE
                           - self.CONSOLE_DOCK_SEPARATOR_SIZE) // 2)
                    try:
                        self._console_splitter_handle.setOrientation(Qt.Horizontal)
                    except Exception:
                        pass
                    self._splitter_item(self.console_separator).configure(
                        pos=(line_x, 0), width=self.CONSOLE_DOCK_SEPARATOR_SIZE,
                        height=root_height, show=True)
                    self._splitter_item(self.console_separator_hitbox).configure(
                        pos=(gutter_x, 0),
                        width=self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE,
                        height=root_height, show=True)
                    self._splitter_item(self.console_region).configure(
                        pos=(console_x, 0), width=console_width,
                        height=root_height, show=True)
                    outer_console_size = (console_width, root_height)
                else:
                    minimum_content = (self.MIN_TOP_HEIGHT + self.MIN_BOTTOM_HEIGHT
                                       + self.FILE_JOB_SPLITTER_GUTTER_SIZE + 1)
                    available = max(
                        1, root_height - minimum_content
                        - self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE)
                    console_height = min(
                        max(self.MIN_CONSOLE_DOCK_HEIGHT,
                            int(self._console_dock_height)),
                        available)
                    content_height = max(
                        1, root_height - console_height
                        - self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE)
                    if console_area == "top":
                        console_y = 0
                        gutter_y = console_height
                        content_y = gutter_y + self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE
                    else:
                        content_y = 0
                        gutter_y = content_height
                        console_y = gutter_y + self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE
                    line_y = (gutter_y
                        + (self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE
                           - self.CONSOLE_DOCK_SEPARATOR_SIZE) // 2)
                    try:
                        self._console_splitter_handle.setOrientation(Qt.Vertical)
                    except Exception:
                        pass
                    self._splitter_item(self.console_separator).configure(
                        pos=(0, line_y), width=root_width,
                        height=self.CONSOLE_DOCK_SEPARATOR_SIZE, show=True)
                    self._splitter_item(self.console_separator_hitbox).configure(
                        pos=(0, gutter_y), width=root_width,
                        height=self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE, show=True)
                    self._splitter_item(self.console_region).configure(
                        pos=(0, console_y), width=root_width,
                        height=console_height, show=True)
                    outer_console_size = (root_width, console_height)
                if not interactive and outer_console_size is not None:
                    self.console_dock.sync_layout(
                        outer_console_size[0], outer_console_size[1], force=force)

            plot_scope = str(
                getattr(self, "_plot_dock_scope", "inner") or "inner"
            ).strip().lower()
            plot_outer = bool(plot_visible and plot_scope == "outer")
            outer_plot_size = None
            if plot_outer:
                area = self._normalize_plot_dock_area(self._plot_dock_area)
                self._plot_split_ratio = self._plot_ratio_for_area(area)
                if self._plot_dock_is_vertical_split(area):
                    job_width, plot_width = self._plot_split_widths(
                        content_width, area)
                    remaining_width = max(
                        1, content_width - plot_width
                        - self.PLOT_DOCK_SEPARATOR_SIZE)
                    if area == "left":
                        plot_x = content_x
                        split_x = plot_x + plot_width
                        content_x = split_x + self.PLOT_DOCK_SEPARATOR_SIZE
                    else:
                        split_x = content_x + remaining_width
                        plot_x = split_x + self.PLOT_DOCK_SEPARATOR_SIZE
                    self._splitter_item(self.plot_region).configure(
                        pos=(plot_x, content_y), width=plot_width,
                        height=content_height, show=True)
                    self._splitter_item(self.job_plot_separator).configure(
                        pos=(split_x + (self.PLOT_DOCK_SEPARATOR_SIZE
                             - self.SPLITTER_SIZE) // 2, content_y),
                        width=self.SPLITTER_SIZE,
                        height=content_height, show=True)
                    self._splitter_item(self.job_plot_separator_hitbox).configure(
                        pos=(split_x, content_y),
                        width=self.PLOT_DOCK_SEPARATOR_SIZE,
                        height=content_height, show=True)
                    content_width = remaining_width
                    outer_plot_size = (plot_width, content_height)
                else:
                    job_height, plot_height = self._plot_split_heights(
                        content_height, area)
                    remaining_height = max(
                        1, content_height - plot_height
                        - self.PLOT_DOCK_SEPARATOR_SIZE)
                    if area == "top":
                        plot_y = content_y
                        split_y = plot_y + plot_height
                        content_y = split_y + self.PLOT_DOCK_SEPARATOR_SIZE
                    else:
                        split_y = content_y + remaining_height
                        plot_y = split_y + self.PLOT_DOCK_SEPARATOR_SIZE
                    self._splitter_item(self.plot_region).configure(
                        pos=(content_x, plot_y), width=content_width,
                        height=plot_height, show=True)
                    self._splitter_item(self.job_plot_separator).configure(
                        pos=(content_x, split_y + (self.PLOT_DOCK_SEPARATOR_SIZE
                             - self.SPLITTER_SIZE) // 2),
                        width=content_width,
                        height=self.SPLITTER_SIZE, show=True)
                    self._splitter_item(self.job_plot_separator_hitbox).configure(
                        pos=(content_x, split_y), width=content_width,
                        height=self.PLOT_DOCK_SEPARATOR_SIZE, show=True)
                    content_height = remaining_height
                    outer_plot_size = (content_width, plot_height)
                if not interactive and outer_plot_size is not None:
                    manager = getattr(self, "plot_dock_manager", None)
                    if manager is not None:
                        manager.layout(*outer_plot_size, force=force)
                    else:
                        for plot_window in self.job_plot_windows.values():
                            if getattr(plot_window, "dock_mode", "docked") == "docked":
                                plot_window.resize(*outer_plot_size)

            # From this point onward width/height describe the remaining main
            # application workspace. Root-level positions add content_x/y.
            width, height = content_width, content_height
            inner_plot_visible = bool(plot_visible and not plot_outer)

            # Job Viewer and Plots occupy one shared lower workspace. Left/Right
            # consume width; Top/Bottom consume height and request a taller lower
            # workspace so both panes retain useful minimum sizes.
            usable_height = max(
                2, height - self.FILE_JOB_SPLITTER_GUTTER_SIZE - 1)
            min_top = min(self.MIN_TOP_HEIGHT, max(1, usable_height - 1))
            inner_console_visible = bool(console_visible and not console_outer)
            requested_workspace_min = self.MIN_BOTTOM_HEIGHT
            if (inner_plot_visible
                    and not self._plot_dock_is_vertical_split(
                        self._plot_dock_area)):
                requested_workspace_min = max(
                    requested_workspace_min,
                    self.MIN_JOB_VIEWER_DOCK_HEIGHT
                    + self.MIN_PLOT_DOCK_HEIGHT
                    + self.PLOT_DOCK_SEPARATOR_SIZE)
            requested_min_bottom = requested_workspace_min
            # A side-docked inner Console consumes width, not height.  Only a
            # top/bottom inner Console participates in the vertical File/Job
            # minimum, matching the drag constraint above.
            inner_console_area = self._normalize_console_dock_area(
                getattr(self, "_console_dock_area", "bottom"))
            if (inner_console_visible
                    and inner_console_area in ("top", "bottom")):
                requested_min_bottom += (
                    self.MIN_CONSOLE_DOCK_HEIGHT
                    + self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE)
            min_bottom = min(
                requested_min_bottom, max(1, usable_height - min_top))
            max_top = max(min_top, usable_height - min_bottom)
            top_height = min(
                max(int(height * self._top_ratio), min_top), max_top)
            top_height = min(top_height, usable_height - 1)
            bottom_height = max(1, usable_height - top_height)
            # At compact extents, hide the status strip before shrinking the
            # actual file viewport below the configured pane minimum.
            status_height = min(self.FILE_STATUS_HEIGHT, max(0, top_height - self.MIN_TOP_HEIGHT))
            file_height = max(1, top_height - status_height)

            # Cache the rendered File/Job split in its own coordinate system.
            # Splitter drag math must stay relative to this remaining workspace
            # even when an outer Console/Plot shifts ``content_y`` away from 0.
            # These values intentionally reflect the clamped integer geometry
            # that is on screen, not merely the requested ratio.
            self._horizontal_splitter_live_top_height = float(top_height)
            self._horizontal_splitter_live_workspace_size = (
                int(width), int(height))

            # Regions are absolutely positioned inside layout_root. They are
            # therefore not part of a vertical flow and cannot make the parent
            # content taller than its visible area.
            safe_width = max(1, width - 1)
            # Cache the *actual* File Explorer workspace.  Root content width is
            # not necessarily the same value when Console/Plot owns an outer
            # dock edge, so splitter drags must not derive file widths from the
            # whole viewport.
            self._file_panel_live_size = (int(safe_width), int(file_height))
            self._splitter_item(self.layout_root).configure( width=-1, height=-1)
            self._splitter_item(self.top_region).configure(
                pos=(content_x, content_y), width=safe_width, height=file_height,
            )
            self._splitter_item(self.file_status_region).configure(
                pos=(content_x, content_y + file_height),
                width=safe_width, height=max(1, status_height), show=status_height > 0,
            )
            splitter_line_y = (
                top_height
                + (self.FILE_JOB_SPLITTER_GUTTER_SIZE - self.SPLITTER_SIZE) // 2
            )
            self._splitter_item(self.horizontal_splitter).configure(
                pos=(content_x, content_y + splitter_line_y),
                width=safe_width, height=self.SPLITTER_SIZE,
            )
            self._splitter_item(self.horizontal_splitter_hitbox).configure(
                pos=(content_x, content_y + top_height), width=safe_width,
                height=self.FILE_JOB_SPLITTER_GUTTER_SIZE,
            )
            file_gutter = self.FILE_PANEL_SPLITTER_GUTTER_SIZE
            if safe_width >= 2 * self.MIN_PANEL_WIDTH + file_gutter:
                min_left = self.MIN_PANEL_WIDTH
                max_left = safe_width - file_gutter - self.MIN_PANEL_WIDTH
            else:
                min_left = max(1, int(safe_width * 0.25))
                max_left = max(min_left, safe_width - file_gutter - min_left)
            if not self._file_panel_splitter_user_adjusted:
                desired_left = (safe_width - file_gutter) * 0.5
            else:
                desired_left = self._last_panel_divider
            left_width = int(min(max(desired_left, min_left), max_left))
            right_x = left_width + file_gutter
            right_width = max(1, safe_width - right_x)
            line_x = left_width + (file_gutter - self.SPLITTER_SIZE) // 2
            self._last_panel_divider = float(left_width)
            self._splitter_item(self.left_parent).configure( pos=(0, 0), width=left_width,
                height=file_height, show=True)
            self._splitter_item(self.right_parent).configure( pos=(right_x, 0), width=right_width,
                height=file_height, show=True)
            self._splitter_item(self.file_panel_separator).configure( pos=(line_x, 0),
                width=self.SPLITTER_SIZE, height=file_height, show=True)
            self._splitter_item(self.file_panel_separator_hitbox).configure( pos=(left_width, 0),
                width=file_gutter, height=file_height, show=True)
            bottom_y = content_y + top_height + self.FILE_JOB_SPLITTER_GUTTER_SIZE
            workspace_x = content_x
            workspace_y = bottom_y
            workspace_width = safe_width
            workspace_height = bottom_height
            if inner_console_visible:
                console_area = self._normalize_console_dock_area(
                    getattr(self, "_console_dock_area", "bottom"))
                try:
                    self.console_dock.set_dock_area(console_area)
                except Exception:
                    pass
                if console_area in ("left", "right"):
                    # Side docking owns a real vertical gutter.  Keep enough
                    # width for Job Viewer (and a visible Plot split, if any).
                    minimum_workspace_width = self.MIN_JOB_VIEWER_WIDTH
                    if (inner_plot_visible
                            and self._plot_dock_is_vertical_split(
                                self._plot_dock_area)):
                        minimum_workspace_width = max(
                            minimum_workspace_width,
                            self.MIN_JOB_VIEWER_WIDTH
                            + self.MIN_PLOT_DOCK_WIDTH
                            + self.PLOT_DOCK_SEPARATOR_SIZE)
                    available_console = max(
                        1, safe_width - minimum_workspace_width
                        - self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE)
                    console_width = min(
                        max(self.MIN_CONSOLE_DOCK_WIDTH,
                            int(getattr(self, "_console_dock_width",
                                        self.CONSOLE_DOCK_DEFAULT_WIDTH))),
                        available_console)
                    workspace_width = max(
                        1, safe_width - console_width
                        - self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE)
                    if console_area == "left":
                        console_x = content_x
                        gutter_x = content_x + console_width
                        workspace_x = (gutter_x
                            + self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE)
                    else:
                        workspace_x = content_x
                        gutter_x = content_x + workspace_width
                        console_x = (gutter_x
                            + self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE)
                    line_x = (gutter_x
                        + (self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE
                           - self.CONSOLE_DOCK_SEPARATOR_SIZE) // 2)
                    try:
                        self._console_splitter_handle.setOrientation(Qt.Horizontal)
                    except Exception:
                        pass
                    self._splitter_item(self.console_separator).configure(
                        pos=(line_x, bottom_y),
                        width=self.CONSOLE_DOCK_SEPARATOR_SIZE,
                        height=bottom_height, show=True)
                    self._splitter_item(self.console_separator_hitbox).configure(
                        pos=(gutter_x, bottom_y),
                        width=self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE,
                        height=bottom_height, show=True)
                    self._splitter_item(self.console_region).configure(
                        pos=(console_x, bottom_y), width=console_width,
                        height=bottom_height, show=True)
                    if not interactive:
                        self.console_dock.sync_layout(
                            console_width, bottom_height, force=force)
                else:
                    available_console = max(
                        1, bottom_height - requested_workspace_min
                        - self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE)
                    console_height = min(
                        max(self.MIN_CONSOLE_DOCK_HEIGHT,
                            int(self._console_dock_height)),
                        available_console)
                    workspace_height = max(
                        1, bottom_height - console_height
                        - self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE)
                    if console_area == "top":
                        console_y = bottom_y
                        console_gutter_y = bottom_y + console_height
                        workspace_y = (console_gutter_y
                            + self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE)
                    else:
                        workspace_y = bottom_y
                        console_gutter_y = bottom_y + workspace_height
                        console_y = (console_gutter_y
                            + self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE)
                    console_line_y = (
                        console_gutter_y
                        + (self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE
                           - self.CONSOLE_DOCK_SEPARATOR_SIZE) // 2)
                    try:
                        self._console_splitter_handle.setOrientation(Qt.Vertical)
                    except Exception:
                        pass
                    self._splitter_item(self.console_separator).configure(
                        pos=(content_x, console_line_y), width=safe_width,
                        height=self.CONSOLE_DOCK_SEPARATOR_SIZE, show=True)
                    self._splitter_item(self.console_separator_hitbox).configure(
                        pos=(content_x, console_gutter_y), width=safe_width,
                        height=self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE, show=True)
                    self._splitter_item(self.console_region).configure(
                        pos=(content_x, console_y), width=safe_width,
                        height=console_height, show=True)
                    if not interactive:
                        self.console_dock.sync_layout(
                            safe_width, console_height, force=force)
            elif not console_outer:
                self._splitter_item(self.console_separator).configure(show=False)
                self._splitter_item(self.console_separator_hitbox).configure(show=False)
                self._splitter_item(self.console_region).configure(show=False)

            job_view_width = workspace_width
            job_view_height = workspace_height
            if inner_plot_visible:
                area = self._normalize_plot_dock_area(self._plot_dock_area)
                self._plot_split_ratio = self._plot_ratio_for_area(area)
                if self._plot_dock_is_vertical_split(area):
                    job_width, plot_width = self._plot_split_widths(
                        workspace_width, area)
                    job_view_width = job_width
                    job_view_height = workspace_height
                    if area == "left":
                        plot_x = workspace_x
                        split_x = plot_x + plot_width
                        job_x = split_x + self.PLOT_DOCK_SEPARATOR_SIZE
                    else:
                        job_x = workspace_x
                        split_x = job_x + job_width
                        plot_x = split_x + self.PLOT_DOCK_SEPARATOR_SIZE
                    self._splitter_item(self.bottom_region).configure(
                        pos=(job_x, workspace_y), width=job_width,
                        height=workspace_height)
                    self._splitter_item(self.plot_region).configure(
                        pos=(plot_x, workspace_y), width=plot_width,
                        height=workspace_height, show=True)
                    self._splitter_item(self.job_plot_separator).configure(
                        pos=(split_x + (self.PLOT_DOCK_SEPARATOR_SIZE
                             - self.SPLITTER_SIZE) // 2, workspace_y),
                        width=self.SPLITTER_SIZE,
                        height=workspace_height, show=True)
                    self._splitter_item(self.job_plot_separator_hitbox).configure(
                        pos=(split_x, workspace_y),
                        width=self.PLOT_DOCK_SEPARATOR_SIZE,
                        height=workspace_height, show=True)
                    plot_layout_size = (plot_width, workspace_height)
                else:
                    job_height, plot_height = self._plot_split_heights(
                        workspace_height, area)
                    job_view_width = workspace_width
                    job_view_height = job_height
                    if area == "top":
                        plot_y = workspace_y
                        split_y = plot_y + plot_height
                        job_y = split_y + self.PLOT_DOCK_SEPARATOR_SIZE
                    else:
                        job_y = workspace_y
                        split_y = job_y + job_height
                        plot_y = split_y + self.PLOT_DOCK_SEPARATOR_SIZE
                    self._splitter_item(self.bottom_region).configure(
                        pos=(workspace_x, job_y), width=workspace_width,
                        height=job_height)
                    self._splitter_item(self.plot_region).configure(
                        pos=(workspace_x, plot_y), width=workspace_width,
                        height=plot_height, show=True)
                    self._splitter_item(self.job_plot_separator).configure(
                        pos=(workspace_x, split_y + (self.PLOT_DOCK_SEPARATOR_SIZE
                             - self.SPLITTER_SIZE) // 2),
                        width=workspace_width,
                        height=self.SPLITTER_SIZE, show=True)
                    self._splitter_item(self.job_plot_separator_hitbox).configure(
                        pos=(workspace_x, split_y), width=workspace_width,
                        height=self.PLOT_DOCK_SEPARATOR_SIZE, show=True)
                    plot_layout_size = (workspace_width, plot_height)
                if not interactive:
                    manager = getattr(self, "plot_dock_manager", None)
                    if manager is not None:
                        manager.layout(*plot_layout_size, force=force)
                    else:
                        for plot_window in self.job_plot_windows.values():
                            if getattr(plot_window, "dock_mode", "docked") == "docked":
                                plot_window.resize(*plot_layout_size)
            else:
                self._splitter_item(self.bottom_region).configure(
                    pos=(workspace_x, workspace_y),
                    width=workspace_width, height=workspace_height)
                if not plot_outer:
                    self._splitter_item(self.job_plot_separator).configure(show=False)
                    self._splitter_item(self.job_plot_separator_hitbox).configure(show=False)
                    self._splitter_item(self.plot_region).configure(show=False)
            jobs_view = getattr(self, "jobs_view", None)
            if jobs_view is not None:
                if interactive:
                    # Both lower panes already own fill-sized children. During a
                    # live divider drag update only their parent rectangles; defer
                    # expensive Job Viewer column/text relayout until release.
                    if self._splitter_item(jobs_view.container).exists():
                        self._splitter_item(jobs_view.container).configure( width=-1, height=-1)
                else:
                    jobs_view.resize(job_view_width, job_view_height)

            # Custom pane geometry is authoritative; no table-cell readback is
            # required. The status strip leaves the same 9 px gutter empty.
            panel_height = file_height
            # Explorer resize marks ListView layout/column work pending.  Doing
            # that for every mouse pixel is the dominant splitter cost, so let
            # the parent clip/fill during the gesture and commit once on release.
            if not interactive:
                self.left.resize(left_width, panel_height)
                self.right.resize(right_width, panel_height)
            self._splitter_item(self.left_status_window).configure( pos=(0, 0),
                width=left_width, height=self.FILE_STATUS_HEIGHT,
            )
            self._splitter_item(self.right_status_window).configure( pos=(right_x, 0),
                width=right_width, height=self.FILE_STATUS_HEIGHT,
            )
            self._splitter_item(self.left_parent).show()
            self._splitter_item(self.right_parent).show()
        except Exception as exc:
            # Do not retry every rendered frame. A permanent invalid item or
            # unsupported configuration would otherwise create an endless
            # configure/redraw loop and visible flicker.
            self._layout_dirty = False
            self._pending_viewport_size = None
            self._resize_last_event = 0.0
            self._report_splitter_exception(
                "Split layout update failed", sys.exc_info())
        finally:
            self._splitter_live_native_updates = False
            # Return cached retained items to the normal event-turn batching path
            # immediately after the live geometry transaction.
            for item in getattr(self, "_splitter_item_cache", {}).values():
                try:
                    item.setImmediateUpdates(False)
                except Exception:
                    pass
            self._layout_updating = False

    def _sync_horizontal_panel_divider(self):
        """Compatibility no-op; the custom Local/Server gutter owns layout."""
        return


__all__ = ["SplitterLayoutBehaviorMixin"]
