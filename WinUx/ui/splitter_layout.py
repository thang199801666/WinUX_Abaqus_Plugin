from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes

import dearpygui.dearpygui as dpg

from ..components.explorer_list_view import _visible_modal_window_exists
from ..components.interaction_gate import (
    acquire_pointer_input, pointer_input_is_blocked, release_pointer_input,
)
from ..diagnostics import log_exception


class SplitterLayoutMixin:
    """Splitter input, resize cursors, and main-window split layout.

    WinUXView still owns widget creation/state. This mixin owns the interaction
    behavior so splitter work can evolve without growing the main view facade.
    """
    def _on_viewport_resize(self, sender=None, app_data=None):
        """Defer layout changes until native viewport resizing has stopped."""
        try:
            if app_data and len(app_data) >= 2:
                width = int(app_data[0])
                height = int(app_data[1])
            else:
                width = int(dpg.get_viewport_client_width())
                height = int(dpg.get_viewport_client_height())
        except Exception:
            return

        self._pending_viewport_size = (max(1, width), max(1, height - 48))
        self._resize_last_event = time.monotonic()
        self._layout_dirty = True

    def _show_horizontal_splitter_cursor(
            self, sender=None, app_data=None, user_data=None):
        cursor = getattr(dpg, "mvMouseCursor_ResizeNS", None)
        if cursor is not None:
            try:
                dpg.set_mouse_cursor(cursor)
                self._splitter_cursor_active = True
            except Exception:
                pass
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
        """Combine DPG and native button state to avoid dropped drag frames."""
        down = False
        try:
            down = bool(dpg.is_mouse_button_down(dpg.mvMouseButton_Left))
        except Exception:
            pass
        if os.name == "nt":
            try:
                down = down or bool(
                    ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
            except Exception:
                pass
        return down

    def _horizontal_splitter_hit_point(self):
        """Return a File/Job splitter-gutter mouse point and screen adjustment."""
        try:
            hitbox = getattr(self, "horizontal_splitter_hitbox", None)
            if hitbox is None or not dpg.does_item_exist(hitbox):
                return None
            raw_x, raw_y = map(float, dpg.get_mouse_pos(local=False))
            split_x, split_y = dpg.get_item_rect_min(hitbox)
            split_width, split_height = dpg.get_item_rect_size(hitbox)
            split_x, split_y = float(split_x), float(split_y)
            split_width = max(1.0, float(split_width))
            split_height = max(1.0, float(split_height))

            # Dear PyGui can report the mouse in desktop-screen coordinates
            # while item rectangles remain viewport-relative. Include every
            # coordinate form exposed by supported DPG builds and retain the
            # matching adjustment for the complete drag gesture.
            candidates = [(raw_x, raw_y)]
            try:
                local_x, local_y = map(float, dpg.get_mouse_pos(local=True))
                candidates.append((local_x, local_y))
            except Exception:
                pass
            try:
                viewport_x, viewport_y = map(float, dpg.get_viewport_pos())
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
        """Return False while Windows has disabled the WinUX top-level.

        Native modal dialogs use ``EnableWindow(owner, False)``.  Dear PyGui's
        custom splitter polls global mouse state and therefore needs to honor
        that OS state explicitly.  Querying ``IsWindowEnabled`` from the WinUX
        UI thread avoids any shared Tk/DPG modal lock or cross-thread counter.
        """
        if os.name != "nt":
            return True
        try:
            import ctypes
            from ctypes import wintypes
            from .platform import find_process_window
            hwnd = int(find_process_window("WinUX") or 0)
            if not hwnd:
                return True
            user32 = ctypes.windll.user32
            user32.IsWindowEnabled.argtypes = [wintypes.HWND]
            user32.IsWindowEnabled.restype = wintypes.BOOL
            return bool(user32.IsWindowEnabled(wintypes.HWND(hwnd)))
        except Exception:
            # Do not make the UI unusable if a best-effort native query fails.
            return True

    def _splitter_input_blocked(self, owner=None):
        """Return True when another foreground gesture owns pointer input.

        ``owner`` is the splitter-specific capture token.  Passing it through
        the application interaction gate gives splitters the same mouse-grab
        semantics as Qt: the splitter that accepted the press keeps receiving
        movement/release, while Explorer rows and every other splitter are
        blocked until that gesture ends.
        """
        return (not self._native_owner_accepts_input()
                or _visible_modal_window_exists()
                or pointer_input_is_blocked(owner))

    def _mouse_position_variants(self):
        """Return the mouse in every coordinate space used by supported DPG builds."""
        points = []
        try:
            raw_x, raw_y = map(float, dpg.get_mouse_pos(local=False))
            points.append((raw_x, raw_y))
            try:
                points.append(tuple(map(float, dpg.get_mouse_pos(local=True))))
            except Exception:
                pass
            try:
                viewport_x, viewport_y = map(float, dpg.get_viewport_pos())
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
        """Geometry-only hit-test used during initial splitter arbitration."""
        try:
            if item is None or not dpg.does_item_exist(item):
                return False
            x0, y0 = map(float, dpg.get_item_rect_min(item))
            width, height = map(float, dpg.get_item_rect_size(item))
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
        try:
            if (hitbox is not None and dpg.does_item_exist(hitbox)
                    and (dpg.is_item_hovered(hitbox)
                         or dpg.is_item_active(hitbox))):
                return True
        except Exception:
            pass
        return bool(ignore_pointer_capture and self._mouse_over_item_rect(hitbox))

    def _begin_file_panel_splitter_drag(self, force_new_press=False):
        if self._file_panel_splitter_dragging or self._rename_is_active():
            return False
        owner = self._file_panel_splitter_owner
        if not self._file_panel_splitter_hit_test(
                ignore_pointer_capture=force_new_press):
            return False
        if not force_new_press and self._splitter_input_blocked(owner):
            return False
        if force_new_press:
            self._cancel_explorer_gestures_for_splitter()
        if not acquire_pointer_input(owner):
            return False
        try:
            self._file_panel_splitter_drag_start_divider = float(
                self._last_panel_divider)
            self._file_panel_splitter_drag_start_screen_x = (
                self._native_cursor_screen_x())
            drag_delta = dpg.get_mouse_drag_delta()
            self._file_panel_splitter_drag_start_delta_x = (
                float(drag_delta[0])
                if self._file_panel_splitter_drag_start_screen_x is None
                else 0.0)
            self._file_panel_splitter_dragging = True
        except Exception:
            self._file_panel_splitter_dragging = False
            release_pointer_input(owner)
            return False
        if not force_new_press:
            self._cancel_explorer_gestures_for_splitter()
        self._clear_splitter_selections()
        return True

    def _end_file_panel_splitter_drag(self):
        was_dragging = bool(self._file_panel_splitter_dragging)
        self._file_panel_splitter_dragging = False
        self._file_panel_splitter_drag_start_divider = 0.0
        self._file_panel_splitter_drag_start_screen_x = None
        self._file_panel_splitter_drag_start_delta_x = 0.0
        if was_dragging:
            release_pointer_input(self._file_panel_splitter_owner)
            self._layout_dirty = True

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
                drag_delta = dpg.get_mouse_drag_delta()
                delta = (float(drag_delta[0])
                         - self._file_panel_splitter_drag_start_delta_x)
            desired = self._file_panel_splitter_drag_start_divider + delta
            if abs(float(delta)) >= 1.0:
                self._file_panel_splitter_user_adjusted = True
            width, _height = self._content_size()
            safe_width = max(1, int(width) - 1)
            gutter = self.FILE_PANEL_SPLITTER_GUTTER_SIZE
            if safe_width >= 2 * self.MIN_PANEL_WIDTH + gutter:
                minimum = float(self.MIN_PANEL_WIDTH)
                maximum = float(safe_width - gutter - self.MIN_PANEL_WIDTH)
            else:
                minimum = max(1.0, safe_width * 0.25)
                maximum = max(minimum, safe_width - gutter - minimum)
            self._last_panel_divider = float(
                min(max(desired, minimum), maximum))
            self._layout_dirty = True
            self._apply_split_layout(force=True, interactive=True)
        except Exception:
            self._end_file_panel_splitter_drag()

    def _update_file_panel_splitter_input(self):
        down = self._left_mouse_button_down()
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
        blocked = self._splitter_input_blocked(self._file_panel_splitter_owner)
        hovered = (not blocked and (
            self._file_panel_splitter_dragging
            or self._file_panel_splitter_hit_test()))
        if hovered:
            try:
                dpg.bind_item_theme(
                    self.file_panel_separator, self._plot_splitter_hover_theme)
            except Exception:
                pass
            cursor = getattr(dpg, "mvMouseCursor_ResizeEW", None)
            if cursor is not None:
                try:
                    dpg.set_mouse_cursor(cursor)
                except Exception:
                    pass
            self._set_native_windows_cursor(
                32644, "_native_resize_ew_cursor")
            self._file_panel_splitter_cursor_active = True
        elif self._file_panel_splitter_cursor_active:
            try:
                dpg.bind_item_theme(
                    self.file_panel_separator, self._splitter_theme)
            except Exception:
                pass
            self._file_panel_splitter_cursor_active = False
            cursor = getattr(dpg, "mvMouseCursor_Arrow", None)
            if cursor is not None:
                try:
                    dpg.set_mouse_cursor(cursor)
                except Exception:
                    pass
            self._set_native_windows_cursor(32512, "_native_arrow_cursor")

    def _job_view_header_owns_pointer(self, separator_only=False):
        """Return True when Job Viewer header input must beat splitters.

        Horizontal workspace splitters intentionally expose a tall invisible
        hit target.  Because the Job Viewer header begins directly below that
        divider, the two regions can overlap.  Qt resolves this by delivering
        the press to the child QHeaderView first; reproduce that ownership here
        before any global splitter capture occurs.
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
        if not new_press or self._rename_is_active():
            return

        # Child header interactions take precedence over the outer splitter.
        # The horizontal splitter has a large high-DPI grab halo that overlaps
        # the top portion of Job Viewer's QHeaderView-style header.  Never let
        # that enclosing splitter steal a sort or column-resize press.
        if self._job_view_header_owns_pointer():
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
        if (not getattr(self, "_horizontal_splitter_dragging", False)
                and self._job_view_header_owns_pointer()):
            return False
        if (not ignore_pointer_capture
                and self._splitter_input_blocked(self._horizontal_splitter_owner)):
            return False
        hitbox = getattr(
            self, "horizontal_splitter_hitbox",
            getattr(self, "horizontal_splitter", None),
        )
        try:
            hovered = bool(
                hitbox is not None
                and dpg.does_item_exist(hitbox)
                and (dpg.is_item_hovered(hitbox) or dpg.is_item_active(hitbox))
            )
            if hovered:
                return True
        except Exception:
            pass
        # During pre-dispatch a neighbouring ListView may still be Dear ImGui's
        # logical hovered item.  Geometry is authoritative for the original
        # press, so do not let that stale hover state turn a splitter grab into
        # an item drag.
        return bool(ignore_pointer_capture and self._mouse_over_item_rect(hitbox))

    def _begin_horizontal_splitter_drag(
            self, sender=None, app_data=None, user_data=None,
            force_new_press=False):
        """Capture a splitter drag without relying on item-active state."""
        owner = self._horizontal_splitter_owner
        if not force_new_press and self._splitter_input_blocked(owner):
            return
        if getattr(self, "_horizontal_splitter_dragging", False):
            return
        # Start only from the real transparent DPG hitbox.  The older
        # screen/local-coordinate fallback could alias another control (notably
        # the Job Viewer header) onto the splitter on mixed-DPI layouts and
        # steal its drag.  Once a drag has started we still use native cursor
        # coordinates for smooth movement, but acquisition itself is strict.
        if not self._horizontal_splitter_native_hovered(
                ignore_pointer_capture=force_new_press):
            return
        if force_new_press:
            self._cancel_explorer_gestures_for_splitter()
        if not acquire_pointer_input(owner):
            return
        try:
            self._horizontal_splitter_drag_start_top = float(
                dpg.get_item_pos(self.horizontal_splitter_hitbox)[1])
            self._horizontal_splitter_drag_start_screen_y = (
                self._native_cursor_screen_y())
            if self._horizontal_splitter_drag_start_screen_y is None:
                drag_delta = dpg.get_mouse_drag_delta()
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
        if not force_new_press:
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
        if was_dragging:
            release_pointer_input(self._horizontal_splitter_owner)
            # Run the expensive ListView/column layout only once after the
            # lightweight interactive resize has finished.
            self._layout_dirty = True

    def _update_horizontal_splitter_cursor(self):
        """Keep ResizeNS visible only while the splitter really owns input."""
        blocked = self._splitter_input_blocked(
            self._horizontal_splitter_owner)
        hovered = (not blocked and (
            self._horizontal_splitter_dragging
            or self._horizontal_splitter_native_hovered()
        ))
        if hovered and not getattr(self, "_splitter_cursor_active", False):
            try:
                dpg.bind_item_theme(
                    self.horizontal_splitter, self._plot_splitter_hover_theme)
            except Exception:
                pass
            self._show_horizontal_splitter_cursor()
        elif not hovered and getattr(
                self, "_splitter_cursor_active", False):
            try:
                dpg.bind_item_theme(
                    self.horizontal_splitter, self._splitter_theme)
            except Exception:
                pass
            plot_owns_cursor = (
                not self._splitter_input_blocked(self._plot_splitter_owner)
                and (getattr(self, "_plot_splitter_dragging", False)
                     or self._job_plot_splitter_native_hovered())
            )
            if not plot_owns_cursor:
                cursor = getattr(dpg, "mvMouseCursor_Arrow", None)
                if cursor is not None:
                    try:
                        dpg.set_mouse_cursor(cursor)
                    except Exception:
                        pass
                self._set_native_windows_cursor(
                    32512, "_native_arrow_cursor")  # IDC_ARROW
            self._splitter_cursor_active = False

    def _update_horizontal_splitter_input(self):
        """Poll mouse state so splitter dragging survives missed callbacks."""
        if self._splitter_input_blocked(self._horizontal_splitter_owner):
            if getattr(self, "_horizontal_splitter_dragging", False):
                self._end_horizontal_splitter_drag()
            self._horizontal_splitter_mouse_was_down = False
            return
        down = self._left_mouse_button_down()
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
        return min(max(ratio, 0.05), 0.95)

    def _set_plot_ratio_for_area(self, ratio, area=None):
        area = self._normalize_plot_dock_area(
            self._plot_dock_area if area is None else area)
        ratio = min(max(float(ratio), 0.05), 0.95)
        self._plot_split_ratios[area] = ratio
        self._plot_split_ratio = ratio

    def _plot_split_widths(self, total_width, area=None):
        """Return clamped Job Viewer / Plots widths for Left/Right docking."""
        area = self._normalize_plot_dock_area(
            self._plot_dock_area if area is None else area)
        available = max(2, int(total_width) - self.PLOT_DOCK_SEPARATOR_SIZE)
        desired = int(round(available * self._plot_ratio_for_area(area)))
        if available >= self.MIN_JOB_VIEWER_WIDTH + self.MIN_PLOT_DOCK_WIDTH:
            minimum = self.MIN_JOB_VIEWER_WIDTH
            maximum = available - self.MIN_PLOT_DOCK_WIDTH
        else:
            minimum = max(1, int(round(available * 0.30)))
            maximum = max(minimum, int(round(available * 0.70)))
        job_width = min(max(desired, minimum), maximum)
        plot_width = max(1, available - job_width)
        return job_width, plot_width

    def _plot_split_heights(self, total_height, area=None):
        """Return clamped Job Viewer / Plots heights for Top/Bottom docking."""
        area = self._normalize_plot_dock_area(
            self._plot_dock_area if area is None else area)
        available = max(2, int(total_height) - self.PLOT_DOCK_SEPARATOR_SIZE)
        desired = int(round(available * self._plot_ratio_for_area(area)))
        if (available >= self.MIN_JOB_VIEWER_DOCK_HEIGHT
                + self.MIN_PLOT_DOCK_HEIGHT):
            minimum = self.MIN_JOB_VIEWER_DOCK_HEIGHT
            maximum = available - self.MIN_PLOT_DOCK_HEIGHT
        else:
            minimum = max(1, int(round(available * 0.30)))
            maximum = max(minimum, int(round(available * 0.70)))
        job_height = min(max(desired, minimum), maximum)
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
            hovered = bool(
                hitbox is not None
                and dpg.does_item_exist(hitbox)
                and (dpg.is_item_hovered(hitbox) or dpg.is_item_active(hitbox)))
            if hovered:
                return True
        except Exception:
            pass
        return bool(
            ignore_pointer_capture
            and self._mouse_over_item_rect(hitbox))

    def _begin_console_splitter_drag(self, force_new_press=False):
        owner = self._console_splitter_owner
        if not self._console_dock_visible or self._console_splitter_dragging:
            return
        if not force_new_press and self._splitter_input_blocked(owner):
            return
        if not self._console_splitter_native_hovered(
                ignore_pointer_capture=force_new_press):
            return
        if force_new_press:
            self._cancel_explorer_gestures_for_splitter()
        if not acquire_pointer_input(owner):
            return
        try:
            self._console_splitter_drag_start_height = float(
                dpg.get_item_rect_size(self.console_region)[1])
            self._console_splitter_drag_start_screen_y = (
                self._native_cursor_screen_y())
            drag_delta = dpg.get_mouse_drag_delta()
            self._console_splitter_drag_start_delta_y = (
                float(drag_delta[1])
                if self._console_splitter_drag_start_screen_y is None
                else 0.0)
            self._console_splitter_dragging = True
        except Exception:
            self._console_splitter_dragging = False
            release_pointer_input(owner)
            return
        if not force_new_press:
            self._cancel_explorer_gestures_for_splitter()
        self._clear_splitter_selections()

    def _end_console_splitter_drag(self):
        was_dragging = bool(self._console_splitter_dragging)
        self._console_splitter_dragging = False
        self._console_splitter_drag_start_height = 0.0
        self._console_splitter_drag_start_screen_y = None
        self._console_splitter_drag_start_delta_y = 0.0
        if was_dragging:
            release_pointer_input(self._console_splitter_owner)
            self._layout_dirty = True

    def _drag_console_splitter(self):
        if (self._splitter_input_blocked(self._console_splitter_owner)
                or not self._console_splitter_dragging
                or not self._console_dock_visible):
            if self._console_splitter_dragging:
                self._end_console_splitter_drag()
            return
        try:
            current = self._native_cursor_screen_y()
            start = self._console_splitter_drag_start_screen_y
            if current is not None and start is not None:
                delta = current - start
            else:
                drag_delta = dpg.get_mouse_drag_delta()
                delta = (float(drag_delta[1])
                         - self._console_splitter_drag_start_delta_y)
            desired = self._console_splitter_drag_start_height - delta
            _width, height = self._content_size()
            split_y = float(dpg.get_item_pos(self.horizontal_splitter_hitbox)[1])
            lower_total = max(
                2.0,
                float(height) - split_y
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
                1.0,
                lower_total - minimum_workspace
                - self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE)
            if maximum >= self.MIN_CONSOLE_DOCK_HEIGHT:
                minimum = float(self.MIN_CONSOLE_DOCK_HEIGHT)
            else:
                minimum = max(1.0, maximum * 0.35)
            self._console_dock_height = int(
                min(max(desired, minimum), maximum))
            self._layout_dirty = True
            self._apply_split_layout(force=True, interactive=True)
        except Exception:
            self._end_console_splitter_drag()

    def _update_console_splitter_input(self):
        if not self._console_dock_visible:
            if self._console_splitter_dragging:
                self._end_console_splitter_drag()
            self._console_splitter_mouse_was_down = False
            return
        if self._splitter_input_blocked(self._console_splitter_owner):
            if self._console_splitter_dragging:
                self._end_console_splitter_drag()
            self._console_splitter_mouse_was_down = False
            return
        down = self._left_mouse_button_down()
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
        blocked = self._splitter_input_blocked(self._console_splitter_owner)
        hovered = (not blocked and self._console_dock_visible and (
            self._console_splitter_dragging
            or self._console_splitter_native_hovered()))
        if hovered:
            try:
                dpg.bind_item_theme(
                    self.console_separator, self._plot_splitter_hover_theme)
            except Exception:
                pass
            cursor = getattr(dpg, "mvMouseCursor_ResizeNS", None)
            if cursor is not None:
                try:
                    dpg.set_mouse_cursor(cursor)
                except Exception:
                    pass
            self._set_native_windows_cursor(
                32645, "_native_resize_ns_cursor")  # IDC_SIZENS
            self._console_splitter_cursor_active = True
        elif self._console_splitter_cursor_active:
            try:
                dpg.bind_item_theme(
                    self.console_separator, self._splitter_theme)
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
                cursor = getattr(dpg, "mvMouseCursor_Arrow", None)
                if cursor is not None:
                    try:
                        dpg.set_mouse_cursor(cursor)
                    except Exception:
                        pass
                self._set_native_windows_cursor(
                    32512, "_native_arrow_cursor")  # IDC_ARROW
            self._console_splitter_cursor_active = False

    def _job_plot_dock_visible(self):
        manager = getattr(self, "plot_dock_manager", None)
        if manager is not None:
            try:
                return bool(manager.has_docked())
            except Exception:
                pass
        return bool(getattr(self, "_plot_dock_open", False))

    def _job_plot_splitter_native_hovered(
            self, ignore_pointer_capture=False):
        if (not ignore_pointer_capture
                and self._splitter_input_blocked(self._plot_splitter_owner)):
            return False
        hitbox = getattr(self, "job_plot_separator_hitbox", None)
        try:
            hovered = bool(
                self._job_plot_dock_visible()
                and hitbox is not None
                and dpg.does_item_exist(hitbox)
                and (dpg.is_item_hovered(hitbox) or dpg.is_item_active(hitbox))
            )
            if hovered:
                return True
        except Exception:
            pass
        return bool(
            ignore_pointer_capture
            and self._job_plot_dock_visible()
            and self._mouse_over_item_rect(hitbox)
        )

    def _show_job_plot_splitter_cursor(self):
        vertical_split = self._plot_dock_is_vertical_split()
        cursor_name = ("mvMouseCursor_ResizeEW" if vertical_split
                       else "mvMouseCursor_ResizeNS")
        cursor = getattr(dpg, cursor_name, None)
        if cursor is not None:
            try:
                dpg.set_mouse_cursor(cursor)
            except Exception:
                pass
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
        if not force_new_press and self._splitter_input_blocked(owner):
            return
        if not self._job_plot_splitter_native_hovered(
                ignore_pointer_capture=force_new_press):
            return
        if force_new_press:
            self._cancel_explorer_gestures_for_splitter()
        if not acquire_pointer_input(owner):
            return
        try:
            job_w, job_h = map(float, dpg.get_item_rect_size(self.bottom_region))
            self._plot_splitter_drag_start_width = job_w
            self._plot_splitter_drag_start_height = job_h
            drag_delta = dpg.get_mouse_drag_delta()
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
        if not force_new_press:
            self._cancel_explorer_gestures_for_splitter()
        self._clear_splitter_selections()

    def _end_job_plot_splitter_drag(self):
        was_dragging = bool(self._plot_splitter_dragging)
        self._plot_splitter_dragging = False
        self._plot_splitter_drag_start_width = 0.0
        self._plot_splitter_drag_start_height = 0.0
        self._plot_splitter_drag_start_delta_x = 0.0
        self._plot_splitter_drag_start_delta_y = 0.0
        self._plot_splitter_drag_start_screen_x = None
        self._plot_splitter_drag_start_screen_y = None
        if was_dragging:
            release_pointer_input(self._plot_splitter_owner)
            self._layout_dirty = True

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
            job_rect = dpg.get_item_rect_size(self.bottom_region)
            plot_rect = dpg.get_item_rect_size(self.plot_region)
            drag_delta = dpg.get_mouse_drag_delta()
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
                available = max(2, int(job_rect[0]) + int(plot_rect[0]))
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
                available = max(2, int(job_rect[1]) + int(plot_rect[1]))
                if (available >= self.MIN_JOB_VIEWER_DOCK_HEIGHT
                        + self.MIN_PLOT_DOCK_HEIGHT):
                    minimum = self.MIN_JOB_VIEWER_DOCK_HEIGHT
                    maximum = available - self.MIN_PLOT_DOCK_HEIGHT
                else:
                    minimum = max(1, int(round(available * 0.30)))
                    maximum = max(minimum, int(round(available * 0.70)))
                job_size = min(max(desired, minimum), maximum)
            self._set_plot_ratio_for_area(float(job_size) / float(available), area)
            self._layout_dirty = True
            self._apply_split_layout(force=True, interactive=True)
        except Exception:
            self._end_job_plot_splitter_drag()

    def _update_job_plot_splitter_input(self):
        if not self._job_plot_dock_visible():
            if self._plot_splitter_dragging:
                self._end_job_plot_splitter_drag()
            self._plot_splitter_mouse_was_down = False
            return
        if self._splitter_input_blocked(self._plot_splitter_owner):
            if self._plot_splitter_dragging:
                self._end_job_plot_splitter_drag()
            self._plot_splitter_mouse_was_down = False
            return
        down = self._left_mouse_button_down()
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
        blocked = self._splitter_input_blocked(self._plot_splitter_owner)
        hovered = (not blocked and (self._plot_splitter_dragging
                   or self._job_plot_splitter_native_hovered()))
        if hovered and not self._plot_splitter_cursor_active:
            self._show_job_plot_splitter_cursor()
            try:
                dpg.bind_item_theme(
                    self.job_plot_separator, self._plot_splitter_hover_theme)
            except Exception:
                pass
        elif not hovered and self._plot_splitter_cursor_active:
            try:
                dpg.bind_item_theme(
                    self.job_plot_separator, self._splitter_theme)
            except Exception:
                pass
            horizontal_owns_cursor = (
                not self._splitter_input_blocked(
                    self._horizontal_splitter_owner)
                and (getattr(self, "_horizontal_splitter_dragging", False)
                     or self._horizontal_splitter_native_hovered())
            )
            if not horizontal_owns_cursor:
                cursor = getattr(dpg, "mvMouseCursor_Arrow", None)
                if cursor is not None:
                    try:
                        dpg.set_mouse_cursor(cursor)
                    except Exception:
                        pass
                self._set_native_windows_cursor(
                    32512, "_native_arrow_cursor")  # IDC_ARROW
            self._plot_splitter_cursor_active = False

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
                drag_delta = dpg.get_mouse_drag_delta()
                delta_y = (
                    float(drag_delta[1])
                    - self._horizontal_splitter_drag_start_delta_y)
            mouse_y = self._horizontal_splitter_drag_start_top + delta_y
            _width, height = self._content_size()
            minimum = self.MIN_TOP_HEIGHT
            minimum_bottom = self.MIN_BOTTOM_HEIGHT
            if (self._job_plot_dock_visible()
                    and not self._plot_dock_is_vertical_split(
                        self._plot_dock_area)):
                minimum_bottom = max(
                    minimum_bottom,
                    self.MIN_JOB_VIEWER_DOCK_HEIGHT
                    + self.MIN_PLOT_DOCK_HEIGHT
                    + self.PLOT_DOCK_SEPARATOR_SIZE)
            if self._console_dock_visible:
                minimum_bottom += (
                    self.MIN_CONSOLE_DOCK_HEIGHT
                    + self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE)
            maximum = max(
                minimum,
                height - minimum_bottom
                - self.FILE_JOB_SPLITTER_GUTTER_SIZE - 1,
            )
            top = min(max(mouse_y, minimum), maximum)
            self._top_ratio = top / max(
                1.0, height - self.FILE_JOB_SPLITTER_GUTTER_SIZE)
            self._layout_dirty = True
            self._apply_split_layout(force=True, interactive=True)
        except Exception:
            self._end_horizontal_splitter_drag()

    def _drag_vertical_splitter(self, sender=None, app_data=None):
        return self._drag_horizontal_splitter(sender, app_data)

    def _content_size(self):
        """Return the real drawable size of the dedicated layout root."""
        try:
            width, height = dpg.get_item_rect_size(self.layout_root)
            width, height = int(width), int(height)
            if width > 1 and height > 1:
                return width, height
        except Exception:
            pass

        # During the first frame rect_size may still be unavailable. The root
        # itself uses width/height=-1, so the viewport client size is a safe
        # temporary fallback. Do not subtract guessed menu/padding constants.
        try:
            width = int(dpg.get_viewport_client_width())
            height = int(dpg.get_viewport_client_height())
        except Exception:
            width, height = self.WIDTH, self.HEIGHT
        return max(1, width), max(1, height)

    def _layout_items_exist(self):
        return all(dpg.does_item_exist(item) for item in (
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
        """Resize the fixed Local/Server layout and lower Job Viewer."""
        if self._layout_updating or not self._alive or not self._layout_items_exist():
            return

        if not force and self._resize_last_event:
            if time.monotonic() - self._resize_last_event < self._resize_settle_delay:
                return

        width, height = self._content_size()
        if not force and not self._layout_dirty and self._last_content_size == (width, height):
            return

        self._layout_updating = True
        try:
            self._last_content_size = (width, height)
            self._layout_dirty = False
            self._pending_viewport_size = None
            self._resize_last_event = 0.0

            plot_visible = self._job_plot_dock_visible()

            # Job Viewer and Plots occupy one shared lower workspace. Left/Right
            # consume width; Top/Bottom consume height and request a taller lower
            # workspace so both panes retain useful minimum sizes.
            usable_height = max(
                2, height - self.FILE_JOB_SPLITTER_GUTTER_SIZE - 1)
            min_top = min(self.MIN_TOP_HEIGHT, max(1, usable_height - 1))
            console_visible = bool(
                self._console_dock_visible
                and self._console_dock_mode == "docked")
            requested_workspace_min = self.MIN_BOTTOM_HEIGHT
            if (plot_visible
                    and not self._plot_dock_is_vertical_split(
                        self._plot_dock_area)):
                requested_workspace_min = max(
                    requested_workspace_min,
                    self.MIN_JOB_VIEWER_DOCK_HEIGHT
                    + self.MIN_PLOT_DOCK_HEIGHT
                    + self.PLOT_DOCK_SEPARATOR_SIZE)
            requested_min_bottom = requested_workspace_min
            if console_visible:
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
            file_height = max(1, top_height - self.FILE_STATUS_HEIGHT)

            # Regions are absolutely positioned inside layout_root. They are
            # therefore not part of a vertical flow and cannot make the parent
            # content taller than its visible area.
            safe_width = max(1, width - 1)
            dpg.configure_item(self.layout_root, width=-1, height=-1)
            dpg.configure_item(
                self.top_region,
                pos=(0, 0), width=safe_width, height=file_height,
            )
            dpg.configure_item(
                self.file_status_region, pos=(0, file_height),
                width=safe_width, height=self.FILE_STATUS_HEIGHT,
            )
            splitter_line_y = (
                top_height
                + (self.FILE_JOB_SPLITTER_GUTTER_SIZE - self.SPLITTER_SIZE) // 2
            )
            dpg.configure_item(
                self.horizontal_splitter, pos=(0, splitter_line_y),
                width=safe_width, height=self.SPLITTER_SIZE,
            )
            dpg.configure_item(
                self.horizontal_splitter_hitbox,
                pos=(0, top_height), width=safe_width,
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
            dpg.configure_item(
                self.left_parent, pos=(0, 0), width=left_width,
                height=file_height, show=True)
            dpg.configure_item(
                self.right_parent, pos=(right_x, 0), width=right_width,
                height=file_height, show=True)
            dpg.configure_item(
                self.file_panel_separator, pos=(line_x, 0),
                width=self.SPLITTER_SIZE, height=file_height, show=True)
            dpg.configure_item(
                self.file_panel_separator_hitbox, pos=(left_width, 0),
                width=file_gutter, height=file_height, show=True)
            bottom_y = top_height + self.FILE_JOB_SPLITTER_GUTTER_SIZE
            workspace_height = bottom_height
            if console_visible:
                available_console = max(
                    1,
                    bottom_height - requested_workspace_min
                    - self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE,
                )
                console_height = min(
                    max(self.MIN_CONSOLE_DOCK_HEIGHT,
                        int(self._console_dock_height)),
                    available_console)
                workspace_height = max(
                    1,
                    bottom_height - console_height
                    - self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE,
                )
                console_gutter_y = bottom_y + workspace_height
                console_line_y = (
                    console_gutter_y
                    + (self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE
                       - self.CONSOLE_DOCK_SEPARATOR_SIZE) // 2)
                console_y = (
                    console_gutter_y
                    + self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE)
                dpg.configure_item(
                    self.console_separator,
                    pos=(0, console_line_y),
                    width=safe_width,
                    height=self.CONSOLE_DOCK_SEPARATOR_SIZE,
                    show=True,
                )
                dpg.configure_item(
                    self.console_separator_hitbox,
                    pos=(0, console_gutter_y),
                    width=safe_width,
                    height=self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE,
                    show=True,
                )
                dpg.configure_item(
                    self.console_region,
                    pos=(0, console_y), width=safe_width,
                    height=console_height, show=True,
                )
                self.console_dock.sync_layout(
                    safe_width, console_height,
                    force=force or interactive)
            else:
                dpg.configure_item(self.console_separator, show=False)
                dpg.configure_item(self.console_separator_hitbox, show=False)
                dpg.configure_item(self.console_region, show=False)

            job_view_width = safe_width
            job_view_height = workspace_height
            if plot_visible:
                area = self._normalize_plot_dock_area(self._plot_dock_area)
                self._plot_split_ratio = self._plot_ratio_for_area(area)
                if self._plot_dock_is_vertical_split(area):
                    job_width, plot_width = self._plot_split_widths(
                        safe_width, area)
                    job_view_width = job_width
                    job_view_height = workspace_height
                    if area == "left":
                        plot_x = 0
                        split_x = plot_width
                        job_x = split_x + self.PLOT_DOCK_SEPARATOR_SIZE
                    else:
                        job_x = 0
                        split_x = job_width
                        plot_x = split_x + self.PLOT_DOCK_SEPARATOR_SIZE
                    dpg.configure_item(
                        self.bottom_region, pos=(job_x, bottom_y),
                        width=job_width, height=workspace_height)
                    dpg.configure_item(
                        self.plot_region, pos=(plot_x, bottom_y),
                        width=plot_width, height=workspace_height, show=True)
                    dpg.configure_item(
                        self.job_plot_separator, pos=(split_x, bottom_y),
                        width=self.PLOT_DOCK_SEPARATOR_SIZE,
                        height=workspace_height, show=True)
                    dpg.configure_item(
                        self.job_plot_separator_hitbox,
                        pos=(split_x - self.SPLITTER_HIT_PADDING, bottom_y),
                        width=(self.PLOT_DOCK_SEPARATOR_SIZE
                               + 2 * self.SPLITTER_HIT_PADDING),
                        height=workspace_height, show=True)
                    plot_layout_size = (plot_width, workspace_height)
                else:
                    job_height, plot_height = self._plot_split_heights(
                        workspace_height, area)
                    job_view_width = safe_width
                    job_view_height = job_height
                    if area == "top":
                        plot_y = bottom_y
                        split_y = bottom_y + plot_height
                        job_y = split_y + self.PLOT_DOCK_SEPARATOR_SIZE
                    else:
                        job_y = bottom_y
                        split_y = bottom_y + job_height
                        plot_y = split_y + self.PLOT_DOCK_SEPARATOR_SIZE
                    dpg.configure_item(
                        self.bottom_region, pos=(0, job_y),
                        width=safe_width, height=job_height)
                    dpg.configure_item(
                        self.plot_region, pos=(0, plot_y),
                        width=safe_width, height=plot_height, show=True)
                    dpg.configure_item(
                        self.job_plot_separator, pos=(0, split_y),
                        width=safe_width,
                        height=self.PLOT_DOCK_SEPARATOR_SIZE, show=True)
                    dpg.configure_item(
                        self.job_plot_separator_hitbox,
                        pos=(0, split_y - self.HORIZONTAL_SPLITTER_HIT_PADDING),
                        width=safe_width,
                        height=(self.PLOT_DOCK_SEPARATOR_SIZE
                                + 2 * self.HORIZONTAL_SPLITTER_HIT_PADDING), show=True)
                    plot_layout_size = (safe_width, plot_height)
                manager = getattr(self, "plot_dock_manager", None)
                if manager is not None:
                    manager.layout(*plot_layout_size, force=force or interactive)
                else:
                    for plot_window in self.job_plot_windows.values():
                        if getattr(plot_window, "dock_mode", "docked") == "docked":
                            plot_window.resize(*plot_layout_size)
            else:
                dpg.configure_item(
                    self.bottom_region,
                    pos=(0, bottom_y),
                    width=safe_width, height=workspace_height,
                )
                dpg.configure_item(self.job_plot_separator, show=False)
                dpg.configure_item(
                    self.job_plot_separator_hitbox, show=False)
                dpg.configure_item(self.plot_region, show=False)
            if interactive:
                # Both lower panes already own fill-sized children. During a
                # live divider drag update only their parent rectangles; defer
                # expensive Job Viewer column/text relayout until release.
                if dpg.does_item_exist(self.jobs_view.container):
                    dpg.configure_item(
                        self.jobs_view.container, width=-1, height=-1)
            else:
                self.jobs_view.resize(job_view_width, job_view_height)

            # Custom pane geometry is authoritative; no table-cell readback is
            # required. The status strip leaves the same 9 px gutter empty.
            panel_height = file_height
            self.left.resize(left_width, panel_height)
            self.right.resize(right_width, panel_height)
            dpg.configure_item(
                self.left_status_window, pos=(0, 0),
                width=left_width, height=self.FILE_STATUS_HEIGHT,
            )
            dpg.configure_item(
                self.right_status_window, pos=(right_x, 0),
                width=right_width, height=self.FILE_STATUS_HEIGHT,
            )
            dpg.show_item(self.left_parent)
            dpg.show_item(self.right_parent)
        except Exception as exc:
            # Do not retry every rendered frame. A permanent invalid item or
            # unsupported configuration would otherwise create an endless
            # configure/redraw loop and visible flicker.
            self._layout_dirty = False
            self._pending_viewport_size = None
            self._resize_last_event = 0.0
            log_exception(
                "Split layout update failed",
                sys.exc_info(),
                fatal=False,
            )
        finally:
            self._layout_updating = False

    def _sync_horizontal_panel_divider(self):
        """Compatibility no-op; the custom Local/Server gutter owns layout."""
        return
