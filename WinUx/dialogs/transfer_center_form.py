"""Resizable transfer queue with unclipped text and a pinned action footer."""
from __future__ import annotations

import itertools
import threading
from collections import OrderedDict

from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.widgets import QFrame, QLabel, QRetainedItem
from DearUIQt.layouts import QVBoxLayout, QGridLayout
from DearUIQt.gui import QFontMetrics
from DearUIQt.backends import dpg
from DearUIQt.dialogs.placement import centered_over
from DearUIQt.themes import DialogMetrics
from DearUIQt.themes import (
    transfer_list_theme, transfer_row_theme, form_row_theme,
    transfer_progress_host_theme, transfer_progress_text_theme,
    progress_theme, transfer_status_text_theme, status_text_theme,
)
from DearUIQt.tooltip import add_styled_tooltip
from .logic.transfer import TransferCenterLogic, TransferTaskHandle, TransferItemRow

_TransferItemRow = TransferItemRow


class TransferCenterDialog(TransferCenterLogic, QtDialog):
    """Keep filenames, status, progress and actions on independent surfaces."""

    REUSABLE_HOST = True
    NATIVE_RESIZABLE = True
    ALLOW_MINIMIZE = True
    ALLOW_MAXIMIZE = True
    ACTION_WIDTH = 86
    ROWS_PER_TURN = 40
    PROGRESS_HEIGHT = DialogMetrics.BUTTON_HEIGHT
    PROGRESS_TEXT_Y_OFFSET = -2
    DEFAULT_WIDTH = 820
    DEFAULT_HEIGHT = 320
    MIN_WINDOW_HEIGHT = 240
    MAX_WINDOW_HEIGHT = 520
    EMPTY_ROWS_HEIGHT = 40
    ROW_HEIGHT_HINT = 86
    CHROME_HEIGHT = 174
    MAX_VISIBLE_ROWS = 4
    # Row actions continue to use QtDialog.action(), which applies
    # DialogMetrics.BUTTON_HEIGHT internally for consistent DearUIQt sizing.

    def __init__(self, view, on_cancel_all=None, on_clear_finished=None, on_row_action=None):
        self._on_cancel_all = on_cancel_all
        self._on_clear_finished = on_clear_finished
        self._on_row_action = on_row_action
        self.tasks = []
        self._active_batch_failed = False
        self._row_ids = itertools.count(1)
        self._row_to_task = {}
        self._row_update_lock = threading.Lock()
        self._pending_row_updates = {}
        self._row_update_scheduled = False
        self.row_widgets = {}
        self._pending_row_creations = OrderedDict()
        self._deferred_row_updates = {}
        self._row_creation_scheduled = False
        self._row_wrap_width = None
        self._summary_refresh_scheduled = False
        self._window_balance_scheduled = False
        self._pending_progress_recenter = set()
        self._progress_recenter_scheduled = False
        self._last_auto_height = None
        self._center_on_first_row = False
        QtDialog.__init__(self, view, "Transfer Center", self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT, modal=False)
        self.setMinimumSize(620, self.MIN_WINDOW_HEIGHT)
        QRetainedItem(self.content).configure(no_scrollbar=True, no_scroll_with_mouse=True)
        self.header("File transfers")
        self.summary = self.status_text("Ready for transfers.")
        self._rows_host_frame = QFrame(
            parent=self.contentWidget(), width=-1, height=-1, frame_shape=QFrame.NoFrame,
            no_scrollbar=False, no_scroll_with_mouse=False)
        self.rows_host = self._rows_host_frame.tag
        self._rows_host_frame.setTheme(transfer_list_theme())
        self.empty_label = self.status_text("No transfers in the queue.", parent=self.rows_host)
        QRetainedItem(self.empty_label).setTheme(transfer_status_text_theme(state="muted"))
        self.button_box([("Cancel All", self.request_cancel_all, "danger", False),
                         ("Clear Finished", self.request_clear_finished, "secondary", False),
                         ("Hide", self.hide, "secondary", False)], button_gap=10)
        self.hide()

    def _close_from_escape(self):
        self.hide()

    def request_cancel_all(self):
        if callable(self._on_cancel_all):
            self._on_cancel_all()
        else:
            super().request_cancel_all()

    def request_clear_finished(self):
        if callable(self._on_clear_finished):
            self._on_clear_finished()
        else:
            super().request_clear_finished()

    def _request_row_action(self, row_id):
        if callable(self._on_row_action):
            self._on_row_action(row_id)
        else:
            super()._request_row_action(row_id)

    def _center_over_winux(self, *, presented=False):
        """Place this modeless window over the actual WinUx owner, not the desktop.

        Transfer Center is prewarmed hidden.  QtDialog centers automatically on
        show only for modal dialogs, so the first explicit transfer must place
        this retained *modeless* window separately.  This method is never called
        from progress/row updates once the first transfer row is laid out.
        """
        native = getattr(self, "_native_window_backend", None)
        if native is not None:
            resolver = getattr(self.view, "_find_main_viewport_hwnd", None)
            try:
                hwnd = int(resolver() or 0) if callable(resolver) else 0
            except (TypeError, ValueError, OSError):
                hwnd = 0
            if hwnd:
                if presented:
                    try:
                        if native.centerOverOwner(self.tag, owner_hwnd=hwnd):
                            return True
                    except Exception:
                        pass
                try:
                    pos = native.centerBeforeShow(
                        self.tag, width=self.width, height=self.height,
                        owner_hwnd=hwnd)
                    if pos is not None:
                        return True
                except Exception:
                    pass

        # A standard DPG window shares the main viewport's coordinate system.
        # Center over the primary WinUx container, not the current mouse point
        # or whichever OS window happened to have focus.
        owner = getattr(self.view, "primary_window_tag", None)
        try:
            if owner is not None and dpg.does_item_exist(owner):
                x, y = dpg.get_item_rect_min(owner)
                width, height = dpg.get_item_rect_size(owner)
                if width > 0 and height > 0:
                    bounds = (0, 0, dpg.get_viewport_client_width(),
                              dpg.get_viewport_client_height())
                    pos = centered_over(
                        (x, y, width, height), (self.width, self.height), bounds)
                    dpg.set_item_pos(self.tag, pos)
                    return True
        except (TypeError, ValueError, KeyError):
            pass
        # Early startup: primary bounds may not be available yet.
        QtDialog.center(self)
        return False

    def _apply_layout(self):
        super()._apply_layout()
        if not hasattr(self, "rows_host") or not self.winfo_exists():
            return
        try:
            width = int(QRetainedItem(self.rows_host).globalGeometry().width())
        except (KeyError, TypeError, ValueError):
            width = 0
        width = max(280, width - 32 if width > 0 else int(self.width) - 72)
        if width == self._row_wrap_width:
            return
        self._row_wrap_width = width
        for row_id, row in self.row_widgets.items():
            QRetainedItem(row["title"]).configure(wrap=width)
            QRetainedItem(row["status_text"]).configure(wrap=width)
            QRetainedItem(row["stats"]).configure(wrap=width)
            self._schedule_progress_recenter(row_id)

    @staticmethod
    def _format_row_title(operation, name):
        return "{}: {}".format(operation, name)

    @staticmethod
    def _text_theme_state(state):
        state = str(state or "").lower()
        if state in ("failed",):
            return "error"
        if state in ("cancelled", "cancelling"):
            return "warning"
        if state in ("completed",):
            return "success"
        if state in ("running", "finalizing"):
            return "running"
        return "muted"

    @staticmethod
    def _progress_theme_state(state):
        state = str(state or "").lower()
        if state in ("completed",):
            return "success"
        if state in ("failed",):
            return "error"
        if state in ("cancelled", "cancelling", "queued", "skipped"):
            return "paused"
        return "normal"

    @staticmethod
    def _infer_state(label, fallback="queued"):
        value = str(label or "").strip().lower()
        if not value:
            return fallback
        if "cancel" in value:
            return "cancelling" if value.startswith("cancelling") else "cancelled"
        if "fail" in value or "denied" in value or "error" in value:
            return "failed"
        if "complete" in value or "done" in value:
            return "completed"
        if "running" in value:
            return "running"
        if "final" in value:
            return "finalizing"
        if "not started" in value or "skip" in value:
            return "skipped"
        if "queue" in value or "prepare" in value:
            return "queued"
        return fallback

    def _set_row_status_visuals(self, row, state=None, label=None):
        state = self._infer_state(label, fallback=state or row.get("state") or "queued")
        row["state"] = state
        if label is not None:
            row["status"] = label
        label = row.get("status") or str(label or "")
        QRetainedItem(row["status_text"]).setValue(str(label).strip())
        QRetainedItem(row["status_text"]).setTheme(
            transfer_status_text_theme(state=self._text_theme_state(state)))
        QRetainedItem(row["progress"]).setTheme(
            progress_theme(state=self._progress_theme_state(state)))

    def _schedule_summary_refresh(self):
        if not hasattr(self, "_summary_refresh_scheduled"):
            return
        if self._summary_refresh_scheduled:
            return
        self._summary_refresh_scheduled = True
        try:
            self.view.after(0, self._flush_summary_refresh)
        except Exception:
            self._summary_refresh_scheduled = False
            self._refresh_summary()

    def _flush_summary_refresh(self):
        self._summary_refresh_scheduled = False
        if self.winfo_exists():
            self._refresh_summary()

    def _refresh_summary(self):
        count = len(self.row_widgets)
        if count:
            active = sum(1 for row in self.row_widgets.values()
                         if row.get("state") in ("queued", "running", "finalizing", "cancelling"))
            attention = sum(1 for row in self.row_widgets.values()
                            if row.get("state") in ("failed", "cancelled"))
            parts = []
            if active:
                parts.append("{} active".format(active))
            if attention:
                parts.append("{} need attention".format(attention))
            summary = "{} item(s) in the transfer queue".format(count)
            if parts:
                summary += " - " + ", ".join(parts)
        else:
            summary = "Ready for transfers."
        QRetainedItem(self.summary).setValue(summary)
        QRetainedItem(self.empty_label).setVisible(not count)

    def _target_window_height(self):
        total_rows = len(self.row_widgets) + len(self._pending_row_creations)
        if total_rows <= 0:
            rows_height = self.EMPTY_ROWS_HEIGHT
        else:
            rows_height = min(total_rows, self.MAX_VISIBLE_ROWS) * self.ROW_HEIGHT_HINT
        return max(
            self.MIN_WINDOW_HEIGHT,
            min(self.MAX_WINDOW_HEIGHT, self.CHROME_HEIGHT + rows_height),
        )

    def _schedule_window_balance(self):
        if not hasattr(self, "_window_balance_scheduled"):
            return
        if self._window_balance_scheduled:
            return
        self._window_balance_scheduled = True
        try:
            self.view.after(0, self._flush_window_balance)
        except Exception:
            self._window_balance_scheduled = False
            self._flush_window_balance()

    def _flush_window_balance(self):
        self._window_balance_scheduled = False
        if not self.winfo_exists():
            return
        target_height = self._target_window_height()
        if target_height != self._last_auto_height:
            self._last_auto_height = target_height
            self.height = target_height
            try:
                self.resize(self.width, target_height)
            except Exception:
                QRetainedItem(self.tag).configure(height=target_height)
        # The first row can be added one UI turn after show(). Center once at
        # the *final* auto-height so the newly opened dialog isn't offset.
        # Never move the window during later progress refreshes or new batches.
        if self._center_on_first_row and (self.row_widgets or not self.tasks):
            self._center_on_first_row = False
            if self.isVisible():
                self._center_over_winux(presented=True)

    def _schedule_progress_recenter(self, row_id):
        if row_id not in self.row_widgets:
            return
        if not hasattr(self, "_pending_progress_recenter"):
            self._pending_progress_recenter = set()
        self._pending_progress_recenter.add(row_id)
        if getattr(self, "_progress_recenter_scheduled", False):
            return
        self._progress_recenter_scheduled = True
        try:
            self.view.after(0, self._flush_progress_recenter)
        except Exception:
            self._progress_recenter_scheduled = False
            self._flush_progress_recenter()

    def _flush_progress_recenter(self):
        self._progress_recenter_scheduled = False
        pending = tuple(self._pending_progress_recenter)
        self._pending_progress_recenter.clear()
        for row_id in pending:
            row = self.row_widgets.get(row_id)
            if row is not None:
                self._recenter_progress_text(row)

    @staticmethod
    def _safe_rect_size(item):
        try:
            size = QRetainedItem(item).globalGeometry().size()
            return max(0, int(size.width())), max(0, int(size.height()))
        except Exception:
            return 0, 0

    def _recenter_progress_text(self, row):
        host_width, host_height = self._safe_rect_size(row["progress_host"])
        value = str(QRetainedItem(row["percentage"]).value("0.0%") or "0.0%")
        try:
            measured = QFontMetrics().size(value)
            text_width, text_height = measured.width(), measured.height()
        except Exception:
            text_width, text_height = self._safe_rect_size(row["percentage"])
        if host_width <= 0 or host_height <= 0 or text_width <= 0 or text_height <= 0:
            return
        x = max(0, (host_width - text_width) // 2)
        # Dear ImGui text metrics include baseline/descent space. A tiny upward
        # correction centers the visible glyphs, not merely the item rectangle.
        y = max(0, (host_height - text_height) // 2 + self.PROGRESS_TEXT_Y_OFFSET)
        try:
            QRetainedItem(row["percentage"]).setPosition((x, y))
        except Exception:
            pass

    def _add_row(self, row_id, operation, name):
        if row_id in self.row_widgets:
            return
        width = self._row_wrap_width or max(280, int(self.width) - 72)
        # Auto-height is essential: wrapped filenames/errors must grow the card,
        # not disappear behind a fixed 84px child-window clipping rectangle.
        group_frame = QFrame(
            parent=self._rows_host_frame, width=-1, height=0,
            auto_resize_y=True, frame_shape=QFrame.StyledPanel,
            no_scrollbar=True, no_scroll_with_mouse=True)
        group = group_frame.tag
        group_frame.setTheme(transfer_row_theme())
        content_layout = QVBoxLayout(parent=group_frame, spacing=0)
        QRetainedItem(content_layout.tag).setTheme(form_row_theme())
        content = content_layout.tag
        title = QLabel(
            self._format_row_title(operation, name), parent=content_layout,
            wrap=width).tag
        name_tooltip = add_styled_tooltip(title, str(name))
        status = QLabel("", parent=content_layout, wrap=width).tag

        # This grid lives in an auto-height row. Height=-1 is a viewport-fill
        # table and feeds its measured height back into the row every frame,
        # producing an ever-shrinking scrollbar with even one transfer.
        controls_grid = QGridLayout(
            2, column_widths=(None, self.ACTION_WIDTH),
            parent=content_layout, height=0)
        QRetainedItem(controls_grid.tag).setTheme(form_row_theme())
        progress_cell = controls_grid.cell(0, 0)
        progress_host_frame = QFrame(
            parent=progress_cell, width=-1, height=self.PROGRESS_HEIGHT,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True)
        progress_host = progress_host_frame.tag
        progress_host_frame.setTheme(transfer_progress_host_theme())
        progress = self.progress_bar(0.0, parent=progress_host, overlay="")
        QRetainedItem(progress).configure(width=-1, height=self.PROGRESS_HEIGHT)
        percentage = QLabel("0.0%", parent=progress_host_frame).tag
        QRetainedItem(percentage).setTheme(transfer_progress_text_theme(light=False))
        action_cell = controls_grid.cell(0, 1)
        action = self.action(
            "Cancel", lambda: self._request_row_action(row_id),
            "secondary", False, parent=action_cell.tag,
            width=self.ACTION_WIDTH, height=self.PROGRESS_HEIGHT)
        stats = self.status_text("", parent=content, wrap=width)
        QRetainedItem(stats).setTheme(status_text_theme(muted=True))
        QRetainedItem(stats).hide()
        self.row_widgets[row_id] = {
            "group": group, "title": title, "status_text": status, "stats": stats,
            "progress": progress, "progress_host": progress_host,
            "percentage": percentage, "action": action,
            "native_parents": (progress_cell.tag, progress_host), "name_tooltip": name_tooltip,
            "operation": operation, "name": name, "status": "Queued", "statistics": "",
            "state": "queued",
        }
        self._set_row_status_visuals(self.row_widgets[row_id], "queued", "Queued")
        self._schedule_progress_recenter(row_id)
        self._schedule_summary_refresh()
        self._schedule_window_balance()
        pending = self._deferred_row_updates.pop(row_id, None)
        if pending:
            self._apply_row_update(self.row_widgets[row_id], row_id, pending)

    def _flush_row_creations(self):
        if not self.winfo_exists():
            self._pending_row_creations.clear()
            self._deferred_row_updates.clear()
            self._row_creation_scheduled = False
            self._summary_refresh_scheduled = False
            return
        # Yield to render/IPC between batches, even for thousands of dropped
        # files. ChildView schedules the next callback on a later UI turn.
        for _ in range(self.ROWS_PER_TURN):
            if not self._pending_row_creations:
                break
            row_id, (operation, name) = self._pending_row_creations.popitem(last=False)
            self._add_row(row_id, operation, name)
        if self._pending_row_creations:
            self._schedule_summary_refresh()
            self._schedule_window_balance()
            self.view.after(0, self._flush_row_creations)
        else:
            self._row_creation_scheduled = False
            self._schedule_summary_refresh()
            self._schedule_window_balance()

    def _set_progress_text(self, row_id, ratio):
        row = self.row_widgets.get(row_id)
        if row is None:
            return
        ratio = max(0.0, min(1.0, float(ratio)))
        QRetainedItem(row["progress"]).setValue(ratio)
        QRetainedItem(row["percentage"]).setValue("{:.1f}%".format(ratio * 100))
        self._schedule_progress_recenter(row_id)

    def handle_command(self, command, *args):
        if command == "add_row":
            self._add_row(*args)
        elif command == "add_rows":
            for row_id, operation, name in args[0]:
                if row_id not in self.row_widgets:
                    self._pending_row_creations[row_id] = (operation, name)
            if self._pending_row_creations and not self._row_creation_scheduled:
                self._row_creation_scheduled = True
                self.view.after(0, self._flush_row_creations)
        elif command == "remove_row":
            self._pending_row_creations.pop(args[0], None)
            self._deferred_row_updates.pop(args[0], None)
            getattr(self, "_pending_progress_recenter", set()).discard(args[0])
            row = self.row_widgets.pop(args[0], None)
            if row:
                for key in ("action", "progress"):
                    widget = self._control_wrappers.pop(row[key], None)
                    if widget is not None:
                        widget.delete()
                self._focus_order = [tag for tag in self._focus_order if tag != row["action"]]
                for tag in row["native_parents"]:
                    owner = self._native_parent_owners.pop(tag, None)
                    if owner is not None:
                        owner.delete()
                QRetainedItem(row["group"]).deleteNative()
                self._schedule_summary_refresh()
                self._schedule_window_balance()
        elif command == "flush_row_updates":
            for row_id, values in self._take_pending_row_updates():
                row = self.row_widgets.get(row_id)
                if row is None:
                    if row_id in self._pending_row_creations:
                        self._deferred_row_updates.setdefault(row_id, {}).update(values)
                    continue
                self._apply_row_update(row, row_id, values)

    def _apply_row_update(self, row, row_id, values):
        if "name" in values:
            row["name"] = values["name"]
            QRetainedItem(row["title"]).setValue(
                self._format_row_title(row["operation"], row["name"]))
            for text in QRetainedItem(row["name_tooltip"]).childItems(1):
                text.setValue(row["name"])
        if "status" in values or "state" in values:
            status = values.get("status", row.get("status", "Queued"))
            state = values.get("state", row.get("state", "queued"))
            self._set_row_status_visuals(row, state, status)
            self._schedule_summary_refresh()
        if "statistics" in values:
            row["statistics"] = values["statistics"]
            QRetainedItem(row["stats"]).setValue(row["statistics"])
            QRetainedItem(row["stats"]).setVisible(bool(row["statistics"]))
        if "ratio" in values:
            self._set_progress_text(row_id, values["ratio"])
        if "action" in values:
            wrapper = self._control_wrappers.get(row["action"])
            if wrapper is not None:
                wrapper.setText(values["action"])
            else:
                QRetainedItem(row["action"]).setLabel(values["action"])
        if "action_enabled" in values:
            self.set_control_enabled(row["action"], bool(values["action_enabled"]))

    def show(self):
        # Center on each hidden->visible transition (including file/folder
        # drag-and-drop). Do not reposition a transfer window already on screen:
        # the user may have moved it while transfers are running.
        was_visible = bool(getattr(self, "_visible_state", False))
        if not was_visible:
            target_height = self._target_window_height()
            self.height = target_height
            self._last_auto_height = target_height
            self.resize(self.width, target_height)
            self._center_over_winux()
            self._center_on_first_row = True
        shown = super().show()
        self._schedule_window_balance()
        return shown

    def destroy(self):
        self.cancel_all(update_ui=False)
        self._pending_row_creations.clear()
        self._deferred_row_updates.clear()
        self._summary_refresh_scheduled = False
        self._window_balance_scheduled = False
        self._pending_progress_recenter.clear()
        self._progress_recenter_scheduled = False
        QtDialog.destroy(self)


__all__ = ["TransferCenterDialog", "TransferTaskHandle"]
