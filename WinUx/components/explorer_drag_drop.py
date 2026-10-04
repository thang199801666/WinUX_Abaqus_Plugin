"""Item and Windows-shell drag/drop engine for ExplorerListView."""

import ctypes
import os
import shutil
import sys
import time
from ctypes import wintypes

import dearpygui.dearpygui as dpg

from ..diagnostics import log_event, log_exception


class ExplorerDragDropMixin:
    def _drain_pending_external_drops(self):
        """Route shell file drops stashed by WM_DROPFILES on the UI thread.

        The drop is claimed when Dear PyGui itself reports the pointer inside
        this view's body, which keeps hit-testing in a single consistent
        coordinate space (the raw Win32 screen point mixes physical pixels
        with DPG logical units on scaled displays and must not be used for
        geometry here; it is kept only for diagnostics). Entries that are
        never claimed - a drop onto another pane - expire and trigger the
        missed-drop hint instead of vanishing silently.
        """
        if not self.on_external_drop:
            return
        pending = type(self)._PENDING_EXTERNAL_DROPS
        if not pending:
            return
        now = time.monotonic()
        fresh = []
        expired = 0
        for entry in list(pending):
            try:
                age = now - float(entry.get("at", now))
            except Exception:
                age = 0.0
            if age > self._EXTERNAL_DROP_TTL_SECONDS:
                expired += 1
            else:
                fresh.append(entry)
        if expired:
            del pending[:]
            pending.extend(fresh)
            log_event(
                "External drop expired unclaimed for {}: {} entries "
                "(drop landed outside this pane)".format(self.uid, expired))
            missed = getattr(self, "on_external_drop_missed", None)
            if callable(missed):
                try:
                    missed()
                except Exception:
                    log_exception(
                        "Explorer external drop missed-hint failed",
                        sys.exc_info(),
                        fatal=False,
                    )
            return
        if not self._mouse_in_body():
            return
        try:
            mx, my = map(float, dpg.get_mouse_pos(local=False))
        except Exception:
            return
        del pending[:]
        for entry in fresh:
            paths = list(entry.get("paths", []))
            log_event(
                "External drop claimed by {}: {} file(s) at mouse "
                "({}, {})".format(
                    self.uid, len(paths), int(mx), int(my)))
            try:
                self.on_external_drop(paths, mx, my)
            except Exception:
                log_exception(
                    "Explorer external drop routing failed",
                    sys.exc_info(),
                    fatal=False,
                )

    def _cursor_over_other_top_level(self):
        """Return True when the physical pointer is over a non-WinUx window.

        Dear PyGui keeps mouse capture while an internal item drag is active,
        so its logical mouse position can continue updating outside the app.
        ``WindowFromPoint`` ignores that capture and tells us when the user has
        actually crossed into Explorer/taskbar/another top-level.  That is the
        exact moment to hand the gesture to OLE Shell drag-and-drop.
        """
        if os.name != "nt" or not self._native_hwnd:
            return False
        try:
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            GA_ROOT = 2
            user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
            user32.GetCursorPos.restype = wintypes.BOOL
            user32.WindowFromPoint.argtypes = [wintypes.POINT]
            user32.WindowFromPoint.restype = wintypes.HWND
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            point = wintypes.POINT()
            if not user32.GetCursorPos(ctypes.byref(point)):
                return False
            under = user32.WindowFromPoint(point)
            if not under:
                return True
            our_root = user32.GetAncestor(
                wintypes.HWND(int(self._native_hwnd)), GA_ROOT)
            other_root = user32.GetAncestor(under, GA_ROOT)
            return int(other_root or 0) != int(our_root or 0)
        except Exception:
            return False

    def _maybe_handoff_drag_to_windows_shell(self):
        """Promote a Local in-app drag to a real Windows Shell drag.

        The handoff happens only after the pointer leaves the WinUx top-level,
        so Local->Server and same-window folder drops keep the existing fast
        internal path.  Once promoted, SHDoDragDrop owns the mouse until the
        user drops/cancels, and the trailing Dear PyGui mouse-up is suppressed.
        """
        if (not self._item_drag_active or not callable(self.on_shell_drag)
                or self._shell_drag_handoff_active
                or not self._drag_source_items):
            return False
        if not self._cursor_over_other_top_level():
            return False

        dragged = list(self._drag_source_items)
        self._shell_drag_handoff_active = True
        self._suppress_next_left_release = True
        # The Windows Shell is about to become the real drag owner. Release the
        # app-level gesture lock first so it cannot survive the modal OLE loop.
        self._release_pointer_gesture()
        # Stop WinUx's preview/cursor before entering the Shell modal drag loop.
        self._finish_item_drag(perform_drop=False)
        self._mouse_down = False
        self._pending_click_index = None
        self._drag_started = False
        try:
            if os.name == "nt":
                try:
                    ctypes.windll.user32.ReleaseCapture()
                except Exception:
                    pass
            self.on_shell_drag(dragged, int(self._native_hwnd or 0))
        except Exception:
            log_exception(
                "Windows Shell outbound drag failed",
                sys.exc_info(),
                fatal=False,
            )
        finally:
            self._shell_drag_handoff_active = False
        return True

    def _drop_path_is_valid(self, target_path):
        """Return True when *target_path* can receive the current drag sources."""
        if not target_path:
            return False
        target_path = os.path.abspath(os.fspath(target_path))
        for source in self._drag_source_items:
            if not source.path:
                return False
            source_path = os.path.abspath(os.fspath(source.path))
            if os.path.normcase(source_path) == os.path.normcase(target_path):
                return False
            if source.is_dir:
                try:
                    if os.path.commonpath([source_path, target_path]) == source_path:
                        return False
                except ValueError:
                    pass
            if os.path.normcase(os.path.dirname(source_path)) == os.path.normcase(target_path):
                return False
        return True

    def _valid_drop_pinned_target(self):
        item = self._pinned_item
        return bool(
            item is not None
            and item.is_dir
            and item.path
            and self._mouse_in_pinned_row()
            and self._drop_path_is_valid(item.path)
        )

    def set_external_drop_target(self, index=None, pinned=False):
        """Highlight a target while another ListView owns the drag gesture."""
        old_index = self._external_drop_target_index
        old_pinned = self._external_drop_target_pinned
        self._external_drop_target_index = (
            int(index) if index is not None and 0 <= int(index) < len(self.items) else None
        )
        self._external_drop_target_pinned = bool(pinned and self._pinned_item is not None)
        if old_index != self._external_drop_target_index:
            self._update_row_visual(old_index)
            self._update_row_visual(self._external_drop_target_index)
        if old_pinned != self._external_drop_target_pinned:
            self._layout_pinned_row()

    def clear_external_drop_target(self):
        self.set_external_drop_target(None, False)

    def _valid_drop_folder_index(self):
        """Return the folder row currently under the mouse when it is a valid target."""
        index = self._row_at_mouse()
        if index is None or not (0 <= index < len(self.items)):
            return None
        target = self.items[index]
        if not target.is_dir or not target.path:
            return None

        return index if self._drop_path_is_valid(target.path) else None

    def _start_item_drag(self):
        index = self._drag_source_index
        if index is None or not (0 <= index < len(self.items)):
            return False

        # Explorer selects an unselected row before dragging it.
        if index not in self.selected:
            state = self._sync_qt_selection_from_fields()
            state.select(index, ctrl=False, shift=False, selected=True)
            self._commit_selection_state()

        self._drag_source_items = list(self.get_selected())
        if not self._drag_source_items:
            return False
        self._drag_started = True
        self._item_drag_active = True
        self._pending_click_index = None
        self._drop_target_index = None
        self._drop_target_pinned = False
        self._hide_rubber_rect()
        if self.on_drag_start:
            try:
                self.on_drag_start(list(self._drag_source_items))
            except Exception:
                pass
        self._drag_preview.begin(self._drag_source_items)
        return True

    def _update_item_drag(self):
        old_target = self._drop_target_index
        old_pinned = self._drop_target_pinned
        self._drop_target_pinned = self._valid_drop_pinned_target()
        self._drop_target_index = None if self._drop_target_pinned else self._valid_drop_folder_index()
        if old_target != self._drop_target_index:
            self._update_row_visual(old_target)
            self._update_row_visual(self._drop_target_index)
        if old_pinned != self._drop_target_pinned:
            self._layout_pinned_row()
        self._external_drop_valid = False
        self._external_drop_target_name = None
        if self.on_drag_motion:
            try:
                mx, my = map(float, dpg.get_mouse_pos(local=False))
                feedback = self.on_drag_motion(mx, my)
                self._external_drop_valid = bool(feedback)
                if isinstance(feedback, str):
                    self._external_drop_target_name = feedback
            except Exception:
                self._external_drop_valid = False
                self._external_drop_target_name = None
        self._update_drag_cursor()

    def _apply_native_drag_cursor(self):
        """Apply the current drag cursor immediately and refresh WM_SETCURSOR.

        WM_SETCURSOR is not guaranteed to fire when only the Python-side drop
        target changes while the pointer remains inside the same native HWND.
        Apply the cursor directly on every drag update, then post WM_SETCURSOR
        so the native hook remains authoritative if GLFW changes it later.
        """
        if os.name != "nt" or not self._item_drag_active:
            return

        try:
            user32 = ctypes.windll.user32
            user32.SetCursor.argtypes = [wintypes.HANDLE]
            user32.SetCursor.restype = wintypes.HANDLE

            # Always retain the default Windows arrow during item dragging.
            # Do not switch to SizeAll/NotAllowed, which can become an invisible
            # or ``None`` cursor with some Windows cursor schemes.
            cursor = self._native_cursor_arrow
            if cursor:
                user32.SetCursor(cursor)

            if self._native_hwnd:
                WM_SETCURSOR = 0x0020
                HTCLIENT = 1
                WM_MOUSEMOVE = 0x0200
                lparam = (WM_MOUSEMOVE << 16) | HTCLIENT
                user32.PostMessageW(
                    wintypes.HWND(self._native_hwnd),
                    WM_SETCURSOR,
                    wintypes.WPARAM(self._native_hwnd),
                    wintypes.LPARAM(lparam),
                )
        except Exception:
            pass

    def _update_drag_cursor(self):
        """Update the drag cursor and preview for the current drop target."""
        valid_target = (
            self._item_drag_active
            and ((self._drop_target_index is not None
                  and 0 <= self._drop_target_index < len(self.items))
                 or self._drop_target_pinned
                 or getattr(self, "_external_drop_valid", False))
        )

        target_name = (
            getattr(self, "_external_drop_target_name", None)
            if getattr(self, "_external_drop_valid", False) else None
        )

        if valid_target and self._drop_target_pinned and self._pinned_item is not None:
            target_name = self._pinned_item.name
        elif valid_target and self._drop_target_index is not None:
            target_item = self.items[self._drop_target_index]

            # _valid_drop_folder_index() should already guarantee this, but keep
            # the validation here so the preview cannot display an invalid target
            # if the item collection changes during a drag operation.
            if target_item.is_dir:
                target_name = target_item.name
            else:
                valid_target = False

        if self._item_drag_active:
            self._drag_preview.update(
                can_copy=valid_target,
                target_name=target_name,
            )

            # Match Explorer's normal pointer while moving items. The preview
            # and target highlight provide the drop feedback.
            self._set_mouse_cursor("mvMouseCursor_Arrow")

            self._apply_native_drag_cursor()

        self._drag_cursor_active = valid_target

    def _unique_destination(self, target_dir, basename):
        """Return an unused destination path, matching Explorer's non-destructive behavior."""
        candidate = os.path.join(target_dir, basename)
        if not os.path.exists(candidate):
            return candidate
        stem, extension = os.path.splitext(basename)
        counter = 2
        while True:
            candidate = os.path.join(target_dir, f"{stem} ({counter}){extension}")
            if not os.path.exists(candidate):
                return candidate
            counter += 1

    def _perform_item_drop(self):
        index = self._drop_target_index
        if self._drop_target_pinned and self._pinned_item is not None:
            target_dir = self._pinned_item.path
        elif index is not None and 0 <= index < len(self.items):
            target_dir = self.items[index].path
        else:
            return []
        moved = []
        errors = []
        for item in self._drag_source_items:
            try:
                destination = self._unique_destination(target_dir, os.path.basename(item.path))
                new_path = shutil.move(item.path, destination)
                moved.append((item, new_path, target_dir))
            except Exception as exc:
                errors.append((item, exc))

        # Remove successfully moved rows from the current directory view.
        moved_ids = {id(item) for item, _, _ in moved}
        if moved_ids:
            self.items = [item for item in self.items if id(item) not in moved_ids]
            self.selected.clear()
            self.last_clicked_index = None
            self._current_index = None
            self._sync_qt_selection_from_fields()
            self.hover_index = None
            self._rebuild_draw_items()
            self._update_status_bar()
            if self.on_selection_change:
                self.on_selection_change([])
            if self.on_items_moved:
                self.on_items_moved(moved)

        if errors:
            if self.on_move_error:
                self.on_move_error(errors)
            else:
                for item, exc in errors:
                    print(f"[move error] {item.path}: {exc}")
        return moved

    def _finish_item_drag(self, perform_drop=True):
        old_target = self._drop_target_index
        moved = self._perform_item_drop() if perform_drop and (old_target is not None or self._drop_target_pinned) else []
        self._item_drag_active = False
        self._drag_source_index = None
        self._drag_source_items = []
        old_pinned = self._drop_target_pinned
        self._drop_target_index = None
        self._drop_target_pinned = False
        self._drag_cursor_active = False
        self._update_row_visual(old_target)
        if old_pinned:
            self._layout_pinned_row()
        self._drag_preview.end()
        self._set_mouse_cursor("mvMouseCursor_Arrow")
        return moved
