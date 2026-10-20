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
        return item

    def _on_viewport_resize(self, sender=None, app_data=None):
        """Defer layout changes until native viewport resizing has stopped."""
        try:
            if app_data and len(app_data) >= 2:
                width = int(app_data[0])
                height = int(app_data[1])
            else:
                app = QApplication.instance()
                screen = app.primaryScreen().availableGeometry() if app is not None else None
                if screen is None:
                    return
                width = int(screen.width())
                height = int(screen.height())
        except Exception:
            return

        self._pending_viewport_size = (max(1, width), max(1, height - 48))
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
            self._file_panel_splitter_dragging = True
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
                drag_delta = QCursor.dragDelta().toTuple()
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
                self._splitter_item(self.file_panel_separator).setTheme(
                    self._plot_splitter_hover_theme)
            except Exception:
                pass
            QCursor.setShape(QCursor.SizeHorCursor)
            self._set_native_windows_cursor(
                32644, "_native_resize_ew_cursor")
            self._file_panel_splitter_cursor_active = True
        elif self._file_panel_splitter_cursor_active:
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
            self._horizontal_splitter_drag_start_top = float(
                self._splitter_item(self.horizontal_splitter_hitbox).pos().toTuple()[1])
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
                self._splitter_item(self.horizontal_splitter).setTheme(
                    self._plot_splitter_hover_theme)
            except Exception:
                pass
            self._show_horizontal_splitter_cursor()
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

    def _update_horizontal_splitter_input(self):
        """Poll mouse state so splitter dragging survives missed callbacks."""
        down = self._left_mouse_button_down()
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
        return clamp_ratio(ratio)

    def _set_plot_ratio_for_area(self, ratio, area=None):
        area = self._normalize_plot_dock_area(
            self._plot_dock_area if area is None else area)
        ratio = clamp_ratio(ratio)
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
            self._console_splitter_drag_start_height = float(
                self._splitter_item(self.console_region).globalGeometry().height())
            self._console_splitter_drag_start_screen_y = (
                self._native_cursor_screen_y())
            drag_delta = QCursor.dragDelta().toTuple()
            self._console_splitter_drag_start_delta_y = (
                float(drag_delta[1])
                if self._console_splitter_drag_start_screen_y is None
                else 0.0)
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
                drag_delta = QCursor.dragDelta().toTuple()
                delta = (float(drag_delta[1])
                         - self._console_splitter_drag_start_delta_y)
            desired = self._console_splitter_drag_start_height - delta
            _width, height = self._content_size()
            split_y = float(self._splitter_item(self.horizontal_splitter_hitbox).pos().toTuple()[1])
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
        down = self._left_mouse_button_down()
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
        blocked = self._splitter_input_blocked(self._console_splitter_owner)
        hovered = (not blocked and self._console_dock_visible and (
            self._console_splitter_dragging
            or self._console_splitter_native_hovered()))
        if hovered:
            try:
                self._splitter_item(self.console_separator).setTheme(
                    self._plot_splitter_hover_theme)
            except Exception:
                pass
            QCursor.setShape(QCursor.SizeVerCursor)
            self._set_native_windows_cursor(
                32645, "_native_resize_ns_cursor")  # IDC_SIZENS
            self._console_splitter_cursor_active = True
        elif self._console_splitter_cursor_active:
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
            job_w, job_h = float(job_rect.width()), float(job_rect.height())
            self._plot_splitter_drag_start_width = job_w
            self._plot_splitter_drag_start_height = job_h
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
            job_geo = self._splitter_item(self.bottom_region).globalGeometry()
            plot_geo = self._splitter_item(self.plot_region).globalGeometry()
            job_rect = (job_geo.width(), job_geo.height())
            plot_rect = (plot_geo.width(), plot_geo.height())
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
        down = self._left_mouse_button_down()
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
        blocked = self._splitter_input_blocked(self._plot_splitter_owner)
        hovered = (not blocked and (self._plot_splitter_dragging
                   or self._job_plot_splitter_native_hovered()))
        if hovered and not self._plot_splitter_cursor_active:
            self._show_job_plot_splitter_cursor()
            try:
                self._splitter_item(self.job_plot_separator).setTheme(
                    self._plot_splitter_hover_theme)
            except Exception:
                pass
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
                1.0, height)
            self._layout_dirty = True
            self._apply_split_layout(force=True, interactive=True)
        except Exception:
            self._end_horizontal_splitter_drag()

    def _drag_vertical_splitter(self, sender=None, app_data=None):
        return self._drag_horizontal_splitter(sender, app_data)

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
            self._splitter_item(self.layout_root).configure( width=-1, height=-1)
            self._splitter_item(self.top_region).configure(
                pos=(0, 0), width=safe_width, height=file_height,
            )
            self._splitter_item(self.file_status_region).configure( pos=(0, file_height),
                width=safe_width, height=self.FILE_STATUS_HEIGHT,
            )
            splitter_line_y = (
                top_height
                + (self.FILE_JOB_SPLITTER_GUTTER_SIZE - self.SPLITTER_SIZE) // 2
            )
            self._splitter_item(self.horizontal_splitter).configure( pos=(0, splitter_line_y),
                width=safe_width, height=self.SPLITTER_SIZE,
            )
            self._splitter_item(self.horizontal_splitter_hitbox).configure(
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
            self._splitter_item(self.left_parent).configure( pos=(0, 0), width=left_width,
                height=file_height, show=True)
            self._splitter_item(self.right_parent).configure( pos=(right_x, 0), width=right_width,
                height=file_height, show=True)
            self._splitter_item(self.file_panel_separator).configure( pos=(line_x, 0),
                width=self.SPLITTER_SIZE, height=file_height, show=True)
            self._splitter_item(self.file_panel_separator_hitbox).configure( pos=(left_width, 0),
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
                self._splitter_item(self.console_separator).configure(
                    pos=(0, console_line_y),
                    width=safe_width,
                    height=self.CONSOLE_DOCK_SEPARATOR_SIZE,
                    show=True,
                )
                self._splitter_item(self.console_separator_hitbox).configure(
                    pos=(0, console_gutter_y),
                    width=safe_width,
                    height=self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE,
                    show=True,
                )
                self._splitter_item(self.console_region).configure(
                    pos=(0, console_y), width=safe_width,
                    height=console_height, show=True,
                )
                self.console_dock.sync_layout(
                    safe_width, console_height,
                    force=force or interactive)
            else:
                self._splitter_item(self.console_separator).configure( show=False)
                self._splitter_item(self.console_separator_hitbox).configure( show=False)
                self._splitter_item(self.console_region).configure( show=False)

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
                    self._splitter_item(self.bottom_region).configure( pos=(job_x, bottom_y),
                        width=job_width, height=workspace_height)
                    self._splitter_item(self.plot_region).configure( pos=(plot_x, bottom_y),
                        width=plot_width, height=workspace_height, show=True)
                    self._splitter_item(self.job_plot_separator).configure(
                        pos=(split_x + (self.PLOT_DOCK_SEPARATOR_SIZE - self.SPLITTER_SIZE) // 2, bottom_y),
                        width=self.SPLITTER_SIZE,
                        height=workspace_height, show=True)
                    self._splitter_item(self.job_plot_separator_hitbox).configure(
                        pos=(split_x, bottom_y),
                        width=self.PLOT_DOCK_SEPARATOR_SIZE,
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
                    self._splitter_item(self.bottom_region).configure( pos=(0, job_y),
                        width=safe_width, height=job_height)
                    self._splitter_item(self.plot_region).configure( pos=(0, plot_y),
                        width=safe_width, height=plot_height, show=True)
                    self._splitter_item(self.job_plot_separator).configure(
                        pos=(0, split_y + (self.PLOT_DOCK_SEPARATOR_SIZE - self.SPLITTER_SIZE) // 2),
                        width=safe_width,
                        height=self.SPLITTER_SIZE, show=True)
                    self._splitter_item(self.job_plot_separator_hitbox).configure(
                        pos=(0, split_y),
                        width=safe_width,
                        height=self.PLOT_DOCK_SEPARATOR_SIZE, show=True)
                    plot_layout_size = (safe_width, plot_height)
                manager = getattr(self, "plot_dock_manager", None)
                if manager is not None:
                    manager.layout(*plot_layout_size, force=force or interactive)
                else:
                    for plot_window in self.job_plot_windows.values():
                        if getattr(plot_window, "dock_mode", "docked") == "docked":
                            plot_window.resize(*plot_layout_size)
            else:
                self._splitter_item(self.bottom_region).configure(
                    pos=(0, bottom_y),
                    width=safe_width, height=workspace_height,
                )
                self._splitter_item(self.job_plot_separator).configure( show=False)
                self._splitter_item(self.job_plot_separator_hitbox).configure( show=False)
                self._splitter_item(self.plot_region).configure( show=False)
            if interactive:
                # Both lower panes already own fill-sized children. During a
                # live divider drag update only their parent rectangles; defer
                # expensive Job Viewer column/text relayout until release.
                if self._splitter_item(self.jobs_view.container).exists():
                    self._splitter_item(self.jobs_view.container).configure( width=-1, height=-1)
            else:
                self.jobs_view.resize(job_view_width, job_view_height)

            # Custom pane geometry is authoritative; no table-cell readback is
            # required. The status strip leaves the same 9 px gutter empty.
            panel_height = file_height
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
            self._layout_updating = False

    def _sync_horizontal_panel_divider(self):
        """Compatibility no-op; the custom Local/Server gutter owns layout."""
        return


__all__ = ["SplitterLayoutBehaviorMixin"]
