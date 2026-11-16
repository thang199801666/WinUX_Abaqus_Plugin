"""Resizable transfer queue with unclipped text and a pinned action footer."""
from __future__ import annotations

import itertools
import os
from pathlib import Path
import threading
import time
from collections import OrderedDict

from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.widgets import QFrame, QLabel, QRetainedItem, QToolButton, QComboBox
from DearUIQt.layouts import QVBoxLayout, QGridLayout
from DearUIQt.gui import QFontDatabase
from DearUIQt.core import Qt
from DearUIQt.gui.palette import QtFusionPalette, color_scheme
from DearUIQt.backends import dpg, get_backend
from DearUIQt.dialogs.placement import centered_over
from DearUIQt.themes import DialogMetrics
from DearUIQt.themes import (
    transfer_list_theme, transfer_row_theme, form_row_theme,
    transfer_progress_host_theme,
    progress_theme, transfer_status_text_theme, status_text_theme,
)
from DearUIQt.tooltip import add_styled_tooltip
from ...ui.components.toolbar import ResourceTextures
from ..logic.transfer import TransferCenterLogic, TransferTaskHandle, TransferItemRow

_TransferItemRow = TransferItemRow


def _percentage_overlay_theme():
    tag = 'winux.transfer.percentage.overlay.{}'.format(color_scheme().lower())
    if not dpg.does_item_exist(tag):
        with dpg.theme(tag=tag):
            for enabled in (True, False):
                with dpg.theme_component(dpg.mvButton, enabled_state=enabled):
                    for color in (dpg.mvThemeCol_Button, dpg.mvThemeCol_ButtonHovered,
                                  dpg.mvThemeCol_ButtonActive, dpg.mvThemeCol_Border):
                        dpg.add_theme_color(color, (0, 0, 0, 0))
                    dpg.add_theme_color(dpg.mvThemeCol_Text, QtFusionPalette.TEXT)
                    dpg.add_theme_style(dpg.mvStyleVar_ButtonTextAlign, .5, .5)
                    dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0)
                    dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
    return tag


def _transfer_toolbar_button_theme(*, checked=False):
    tag = 'winux.transfer.toolbar.{}.{}'.format(
        'checked' if checked else 'normal', color_scheme().lower())
    if not dpg.does_item_exist(tag):
        p = QtFusionPalette
        with dpg.theme(tag=tag):
            for component in (dpg.mvImageButton, dpg.mvButton):
                with dpg.theme_component(component):
                    # Intentionally stronger than the normal flat QToolButton
                    # chrome: these controls must read as real raised buttons.
                    face = p.HIGHLIGHT_SOFT if checked else p.BUTTON
                    hover = p.HIGHLIGHT_HOVER if checked else p.BUTTON_HOVER
                    active = p.HIGHLIGHT if checked else p.BUTTON_ACTIVE
                    border = p.HIGHLIGHT if checked else p.BORDER_DARK
                    dpg.add_theme_color(dpg.mvThemeCol_Button, face)
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, hover)
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, active)
                    dpg.add_theme_color(dpg.mvThemeCol_Border, border)
                    dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 2 if checked else 1)
                    dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 3)
                    dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 5, 4)
    return tag


class TransferCenterDialog(TransferCenterLogic, QtDialog):
    """Keep filenames, status, progress and actions on independent surfaces."""

    REUSABLE_HOST = True
    NATIVE_RESIZABLE = True
    NATIVE_REUSE_PRESENTATION = True
    ALLOW_MINIMIZE = True
    ALLOW_MAXIMIZE = True
    ACTION_WIDTH = 76
    ROWS_PER_TURN = 40
    PROGRESS_HEIGHT = 18
    PROGRESS_TEXT_Y_OFFSET = 0
    DEFAULT_WIDTH = 580
    DEFAULT_HEIGHT = 238
    MIN_WINDOW_HEIGHT = 208
    MAX_WINDOW_HEIGHT = 460
    EMPTY_ROWS_HEIGHT = 34
    ROW_HEIGHT_HINT = 138
    CHROME_HEIGHT = 78
    MAX_VISIBLE_ROWS = 3
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
        self._progress_render_token = None
        self._dialog_speed_limit_bps = None
        self._dialog_speed_limit_label = "Unlimited"
        self._dialog_paused = False
        self._dialog_auto_close = True
        self._dialog_keep_open = False
        QtDialog.__init__(self, view, "Transfer", self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT,
                          modal=False, footer=True)
        # Keep the row action button and progress bar at exactly the same
        # height, using the current DearUIQt dialog button metric so the
        # layout stays consistent across font/DPI changes.
        self.PROGRESS_HEIGHT = self.action_height()
        self.setMinimumSize(520, self.MIN_WINDOW_HEIGHT)
        QRetainedItem(self.content).configure(no_scrollbar=True, no_scroll_with_mouse=True)
        self.summary = self.status_text("Ready for transfers.")
        QRetainedItem(self.summary).hide()
        self._rows_host_frame = QFrame(
            parent=self.contentWidget(), width=-1, height=-1, frame_shape=QFrame.NoFrame,
            no_scrollbar=False, no_scroll_with_mouse=False)
        self.rows_host = self._rows_host_frame.tag
        self._rows_host_frame.setTheme(transfer_list_theme())
        self.empty_label = self.status_text("No transfers in the queue.", parent=self.rows_host)
        QRetainedItem(self.empty_label).setTheme(transfer_status_text_theme(state="muted"))
        self._build_dialog_toolbar()
        self.hide()

    def _refresh_theme_surfaces(self):
        """Rebind custom transfer-row surfaces after a Light/Dark switch."""
        try:
            self._rows_host_frame.setTheme(transfer_list_theme())
        except Exception:
            pass
        try:
            QRetainedItem(self.empty_label).setTheme(
                transfer_status_text_theme(state="muted"))
        except Exception:
            pass
        for row in tuple(self.row_widgets.values()):
            try:
                QRetainedItem(row.get("group")).setTheme(transfer_row_theme())
            except Exception:
                pass
            try:
                QRetainedItem(row.get("progress_host")).setTheme(
                    transfer_progress_host_theme())
            except Exception:
                pass
            state = str(row.get("state") or "queued")
            try:
                progress_state = self._progress_theme_state(state)
                QRetainedItem(row.get("progress")).setTheme(
                    progress_theme(state=progress_state))
                row["_progress_theme_state"] = progress_state
            except Exception:
                pass
            try:
                self._set_row_status_visuals(
                    row, state, str(row.get("status") or ""))
            except Exception:
                pass
            try:
                QRetainedItem(row.get("stats")).setTheme(status_text_theme(muted=True))
            except Exception:
                pass
            try:
                dpg.bind_item_theme(row.get("percentage"), _percentage_overlay_theme())
            except Exception:
                pass

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

    def _prepare_native_hidden(self):
        ready = super()._prepare_native_hidden()
        # Warm geometry alone is not permission to expose an empty first frame:
        # newly queued transfer rows must also have reached native layout.
        for row_id in itertools.islice(self._row_to_task, self.MAX_VISIBLE_ROWS):
            row = self.row_widgets.get(row_id)
            if row is None or min(self._safe_rect_size(row['group'])) <= 0:
                return False
        return ready

    @staticmethod
    def _format_row_title(operation, name):
        return "File:   {}".format(name)

    @staticmethod
    def _operation_gerund(operation):
        value = str(operation or "Transfer").strip()
        lower = value.lower()
        if lower.endswith("upload"):
            return "Uploading"
        if lower.endswith("download"):
            return "Downloading"
        if lower.endswith("copy"):
            return "Copying"
        if lower.endswith("ing"):
            return value
        return "Transferring"

    def _refresh_window_title(self):
        active = next((row for row in self.row_widgets.values()
                       if row.get("state") in ("running", "finalizing", "queued", "cancelling")), None)
        if active is None:
            self.setWindowTitle("Transfer")
            return
        ratio = max(0.0, min(1.0, float(active.get("_ratio", 0.0) or 0.0)))
        self.setWindowTitle("{}% {}".format(
            int(round(ratio * 100.0)), self._operation_gerund(active.get("operation"))))

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
        previous_state = row.get('state')
        row["state"] = state
        if label is not None:
            row["status"] = label
        label = row.get("status") or str(label or "")
        label = str(label).strip()
        if row.get('_status_label') != label:
            QRetainedItem(row['status_text']).setValue(label)
            row['_status_label'] = label
        # Normal transfer states are redundant with the dynamic window title.
        # Surface only states that require attention or communicate completion.
        status_visible = state in ("failed", "cancelled", "cancelling", "completed")
        if row.get('_status_visible') != status_visible:
            QRetainedItem(row['status_text']).setVisible(status_visible)
            row['_status_visible'] = status_visible
        text_state = self._text_theme_state(state)
        if row.get('_text_theme_state') != text_state:
            QRetainedItem(row['status_text']).setTheme(transfer_status_text_theme(state=text_state))
            row['_text_theme_state'] = text_state
        progress_state = self._progress_theme_state(state)
        if row.get('_progress_theme_state') != progress_state:
            QRetainedItem(row['progress']).setTheme(progress_theme(state=progress_state))
            row['_progress_theme_state'] = progress_state
        return previous_state != state

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
        # The WinSCP-style progress dialog does not expose queue bookkeeping
        # in its normal single-transfer presentation. Keep this retained label
        # only for compatibility with controller/tests and show it only when a
        # real queue exists.
        QRetainedItem(self.summary).setVisible(count > 1)
        QRetainedItem(self.empty_label).setVisible(not count)
        self._refresh_window_title()

    def _target_window_height(self):
        # Task models exist before their queued add_row commands reach the
        # widget tree. Size correctly on the very first show, avoiding a second
        # grow/recenter transaction after the native window appears.
        total_rows = max(len(self.row_widgets) + len(self._pending_row_creations),
                         len(self._row_to_task))
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
                if not self._recenter_progress_text(row):
                    # Initial UI callbacks can run before the first layout.
                    # Keep the request for the next render instead of losing it.
                    self._pending_progress_recenter.add(row_id)

    @staticmethod
    def _safe_rect_size(item):
        try:
            size = QRetainedItem(item).globalGeometry().size()
            return max(0, int(size.width())), max(0, int(size.height()))
        except Exception:
            return 0, 0

    def _recenter_progress_text(self, row):
        # The native control centers its own label at submission time, using
        # the actual available width. No pre-layout text measurements needed.
        dpg.configure_item(row['percentage'], pos=(0, 0), width=-1,
                           height=self.PROGRESS_HEIGHT)
        return True

    def _task_for_row(self, row_id):
        return self._row_to_task.get(row_id)

    def _active_task(self):
        for task in self.tasks:
            if task.state in ("running", "cancelling") and task.winfo_exists():
                return task
        for task in self.tasks:
            if task.winfo_exists():
                return task
        return None

    def _active_row_id(self):
        task = self._active_task()
        if task is None:
            return None
        row = getattr(task, "_active_row", None)
        if row is not None and row.exists():
            return row.row_id
        for row in getattr(task, "rows", ()):
            if row.exists():
                return row.row_id
        return None

    def _build_dialog_toolbar(self):
        """Create one WinSCP-like control strip for the whole dialog."""
        toolbar = QGridLayout(
            6, column_widths=(34, 34, 34, 34, 30, 132),
            parent=self.footer, height=0)
        toolbar.setHorizontalSpacing(4)
        QRetainedItem(toolbar.tag).setTheme(form_row_theme())
        self._dialog_toolbar = toolbar

        def icon_control(column, icon_name, callback, tooltip, *, checkable=False, checked=False):
            texture = ResourceTextures.get(icon_name, pixel_size=32)
            widget = self.own_widget(QToolButton(
                "", parent=self._qt_parent(toolbar.cell(0, column).tag),
                icon=texture, width=30, height=self.PROGRESS_HEIGHT,
                icon_size=(18, 18), auto_raise=False))
            widget.setCheckable(checkable)
            widget.setChecked(checked)
            widget.clicked.connect(callback)
            tag = widget.tag
            self._control_wrappers[tag] = widget
            self._remember_focusable(tag)
            widget.setTheme(_transfer_toolbar_button_theme(checked=checked))
            if checkable:
                widget.toggled.connect(
                    lambda state, w=widget: w.setTheme(
                        _transfer_toolbar_button_theme(checked=bool(state))))
            add_styled_tooltip(tag, tooltip)
            return tag

        self._toolbar_cancel = icon_control(
            0, "transfer_cancel", self.request_cancel_all,
            "Cancel all transfers")
        self._toolbar_pause = icon_control(
            1, "transfer_pause", self._toggle_dialog_pause,
            "Pause or resume all active transfers",
            checkable=True, checked=False)
        self._toolbar_hide = icon_control(
            2, "transfer_hide", self.hide,
            "Hide transfer dialog; transfers continue in the background")
        self._toolbar_finish = icon_control(
            3, "transfer_finish", self._toggle_dialog_keep_open,
            "Auto-close dialog when all transfers finish",
            checkable=True, checked=True)
        self._toolbar_speed_icon = icon_control(
            4, "transfer_speed", self._show_speed_menu,
            "Transfer speed limit")

        pause_widget = self._control_wrappers.get(self._toolbar_pause)
        if pause_widget is not None:
            pause_widget.toggled.connect(
                lambda state: add_styled_tooltip(
                    self._toolbar_pause,
                    "Paused (click to resume)" if state else "Running (click to pause)"))
        finish_widget = self._control_wrappers.get(self._toolbar_finish)
        if finish_widget is not None:
            finish_widget.toggled.connect(
                lambda state: add_styled_tooltip(
                    self._toolbar_finish,
                    "Auto-close: ON" if state else "Auto-close: OFF"))

        speed_items = [
            "Unlimited", "128 KB/s", "256 KB/s", "512 KB/s",
            "1 MB/s", "2 MB/s", "5 MB/s", "10 MB/s", "20 MB/s", "50 MB/s",
        ]
        speed_combo = self.own_widget(QComboBox(
            speed_items, current="Unlimited",
            parent=self._qt_parent(toolbar.cell(0, 5).tag), after=self.view.after,
            backend=get_backend(), editable=False, width=126))
        speed_combo.setMaxVisibleItems(10)
        speed_combo.setPopupParent(self.tag)
        speed_combo.currentTextChanged.connect(self._speed_combo_changed)
        self._toolbar_speed = speed_combo.tag
        self._toolbar_speed_focus = (
            speed_combo._choice_field.button
            if speed_combo._choice_field is not None else speed_combo.tag)
        self._control_wrappers[self._toolbar_speed] = speed_combo
        self._control_wrappers[self._toolbar_speed_focus] = speed_combo
        self._remember_focusable(self._toolbar_speed_focus)
        add_styled_tooltip(self._toolbar_speed_focus, "Transfer speed limit")

    def _apply_dialog_options_to_task(self, task):
        event = task.cancel_event
        event._winux_speed_limit_bps = self._dialog_speed_limit_bps
        event._winux_rate_state = None
        pause_event = getattr(event, "_winux_pause_event", None)
        if pause_event is None:
            pause_event = threading.Event()
            event._winux_pause_event = pause_event
        if self._dialog_paused:
            pause_event.set()
        else:
            pause_event.clear()
        task.keep_open_when_finished = not bool(self._dialog_auto_close)

    def add_task(self, operation, cancel_event, items=None):
        task = super().add_task(operation, cancel_event, items)
        self._apply_dialog_options_to_task(task)
        return task

    def _toggle_dialog_pause(self):
        button = self._control_wrappers.get(getattr(self, "_toolbar_pause", None))
        if button is not None and hasattr(button, "isChecked"):
            self._dialog_paused = bool(button.isChecked())
        else:
            self._dialog_paused = not self._dialog_paused
        active = [task for task in self.tasks
                  if task.state in ("running", "cancelling") and task.winfo_exists()]
        for task in active:
            event = getattr(task.cancel_event, "_winux_pause_event", None)
            if event is None:
                event = threading.Event()
                task.cancel_event._winux_pause_event = event
            if self._dialog_paused:
                event.set()
            else:
                event.clear()
        return bool(active)

    def _set_dialog_speed_limit(self, bytes_per_second, label):
        self._dialog_speed_limit_bps = (
            None if bytes_per_second is None else max(1, int(bytes_per_second)))
        self._dialog_speed_limit_label = str(label)
        for task in self.tasks:
            if task.state not in ("running", "cancelling"):
                continue
            task.cancel_event._winux_speed_limit_bps = self._dialog_speed_limit_bps
            task.cancel_event._winux_rate_state = None
        wrapper = self._control_wrappers.get(getattr(self, "_toolbar_speed", None))
        if wrapper is not None and hasattr(wrapper, "setCurrentText"):
            if str(wrapper.currentText() or "") != self._dialog_speed_limit_label:
                wrapper.setCurrentText(self._dialog_speed_limit_label)
        return True

    def _show_speed_menu(self):
        wrapper = self._control_wrappers.get(getattr(self, "_toolbar_speed", None))
        if wrapper is not None and hasattr(wrapper, "showPopup"):
            return bool(wrapper.showPopup())
        return False

    def _speed_combo_changed(self, text):
        values = {
            "Unlimited": None,
            "128 KB/s": 128 * 1024,
            "256 KB/s": 256 * 1024,
            "512 KB/s": 512 * 1024,
            "1 MB/s": 1024 * 1024,
            "2 MB/s": 2 * 1024 * 1024,
            "5 MB/s": 5 * 1024 * 1024,
            "10 MB/s": 10 * 1024 * 1024,
            "20 MB/s": 20 * 1024 * 1024,
            "50 MB/s": 50 * 1024 * 1024,
        }
        label = str(text or "").strip()
        if label in values:
            self._set_dialog_speed_limit(values[label], label)

    def _toggle_dialog_keep_open(self):
        widget = self._control_wrappers.get(getattr(self, "_toolbar_finish", None))
        if widget is not None and hasattr(widget, "isChecked"):
            self._dialog_auto_close = bool(widget.isChecked())
        else:
            self._dialog_auto_close = not bool(self._dialog_auto_close)
        self._dialog_keep_open = not self._dialog_auto_close
        for task in self.tasks:
            task.keep_open_when_finished = not self._dialog_auto_close
        return True

    def task_finished(self, task):
        super().task_finished(task)
        if not self._dialog_auto_close or task.state != "completed":
            return
        remaining = [item for item in self.tasks
                     if item is not task and item.winfo_exists()
                     and item.state in ("running", "cancelling", "queued")]
        if remaining:
            return
        try:
            self.view.after(self.AUTO_REMOVE_DELAY_MS, self.hide)
        except Exception:
            self.hide()

    def _add_row(self, row_id, operation, name):
        if row_id in self.row_widgets:
            return
        width = self._row_wrap_width or max(280, int(self.width) - 72)
        # Auto-height is essential: wrapped filenames/errors must grow the card,
        # not disappear behind a fixed 84px child-window clipping rectangle.
        group_frame = QFrame(
            parent=self._rows_host_frame, width=-1, height=0,
            auto_resize_y=True, frame_shape=QFrame.NoFrame,
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
        status = QLabel("{}".format(self._operation_gerund(operation)),
                        parent=content_layout, wrap=width).tag
        # Running/queued state is already communicated by the native caption
        # (e.g. "27% Downloading"). Only exceptional/final states need an
        # extra status line inside the body.
        QRetainedItem(status).hide()

        # WinSCP-like compact surface: keep the Cancel/Retry action immediately
        # beside the progress bar, matching the reference layout.
        controls_grid = QGridLayout(
            2, column_widths=(None, self.ACTION_WIDTH), parent=content_layout, height=0)
        controls_grid.setHorizontalSpacing(8)
        QRetainedItem(controls_grid.tag).setTheme(form_row_theme())
        progress_cell = controls_grid.cell(0, 0)
        action_cell = controls_grid.cell(0, 1)
        progress_host_frame = QFrame(
            parent=progress_cell, width=-1, height=self.PROGRESS_HEIGHT,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True)
        progress_host = progress_host_frame.tag
        progress_host_frame.setTheme(transfer_progress_host_theme())
        progress = self.progress_bar(0.0, parent=progress_host, overlay="")
        QRetainedItem(progress).configure(width=-1, height=self.PROGRESS_HEIGHT)
        if not hasattr(self, '_progress_font'):
            self._progress_font_database = QFontDatabase(parent=self)
            path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'segoeuib.ttf'
            self._progress_font = self._progress_font_database.addApplicationFont(
                path, DialogMetrics.BODY_FONT_SIZE)
        bold_font = self._progress_font
        percentage = dpg.add_button(
            parent=progress_host, label='0.0%', width=-1,
            height=self.PROGRESS_HEIGHT, pos=(0, 0), enabled=False)
        dpg.bind_item_theme(percentage, _percentage_overlay_theme())
        if bold_font is not None:
            dpg.bind_item_font(percentage, bold_font.nativeId())
        # Reserve enough width for the longest labels so text never runs into
        # the value column (the previous 104 px column made
        # ``Bytes transferred:193.0 MB`` look concatenated).  Values remain
        # left-aligned and all label/value pairs share a text baseline.
        stats_grid = QGridLayout(
            4, column_widths=(128, None, 112, None),
            parent=content_layout, height=0)
        stats_grid.setHorizontalSpacing(8)
        stats_grid.setVerticalSpacing(4)
        QRetainedItem(stats_grid.tag).setTheme(form_row_theme())
        stat_items = {}

        def add_stat(row_index, label_column, label_text, key):
            label_cell = stats_grid.cell(row_index, label_column)
            value_cell = stats_grid.cell(row_index, label_column + 1)
            label_widget = QLabel(label_text, parent=label_cell)
            value_widget = QLabel("--", parent=value_cell)
            label_widget.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            value_widget.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            label_cell.setAlignment(label_widget, Qt.AlignBaseline)
            value_cell.setAlignment(value_widget, Qt.AlignBaseline)
            stat_items[key] = value_widget.tag

        add_stat(0, 0, "Time left:", "time_left")
        add_stat(0, 2, "Time elapsed:", "time_elapsed")
        add_stat(1, 0, "Bytes transferred:", "bytes_transferred")
        add_stat(1, 2, "Speed:", "speed_text")

        # Keep the per-transfer action directly beside the progress bar.
        # This matches the WinSCP-like composition the user requested.
        action = self.action(
            "Cancel", lambda: self._request_row_action(row_id),
            "secondary", False, parent=action_cell.tag,
            width=self.ACTION_WIDTH, height=self.PROGRESS_HEIGHT)
        action_cell.setAlignment(QRetainedItem(action), Qt.AlignRight | Qt.AlignVCenter)

        stats = self.status_text("", parent=content, wrap=width)
        QRetainedItem(stats).setTheme(status_text_theme(muted=True))
        QRetainedItem(stats).hide()

        self.row_widgets[row_id] = {
            "group": group, "title": title, "status_text": status, "stats": stats,
            "stat_items": stat_items,
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
        if row.get('_ratio') != ratio:
            QRetainedItem(row['progress']).setValue(ratio)
            row['_ratio'] = ratio
            refresh_title = getattr(self, '_refresh_window_title', None)
            if callable(refresh_title):
                refresh_title()
        text = '{:.1f}%'.format(ratio * 100)
        if row.get('_percentage_text') != text:
            QRetainedItem(row['percentage']).setLabel(text)
            row['_percentage_text'] = text
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
                removed_focus = {row["action"]}
                self._focus_order = [tag for tag in self._focus_order if tag not in removed_focus]
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
            if self._set_row_status_visuals(row, state, status):
                self._schedule_summary_refresh()
        if "statistics" in values:
            previous = row.get('statistics', '')
            statistics = values['statistics']
            if previous != statistics:
                row['statistics'] = statistics
                QRetainedItem(row['stats']).setValue(statistics)
                if bool(previous) != bool(statistics):
                    QRetainedItem(row['stats']).setVisible(bool(statistics))
        stat_items = row.get("stat_items") or {}
        for key in ("time_left", "time_elapsed", "bytes_transferred", "speed_text"):
            if key in values and key in stat_items:
                QRetainedItem(stat_items[key]).setValue(str(values[key]))
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

    def _flush_live_progress(self):
        if not self.winfo_exists() or not self.isVisible():
            return
        deadline = time.perf_counter() + .003
        for task in tuple(self.tasks):
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break
            if task.state in ('running', 'cancelling'):
                task.flush_progress(time_budget_ms=remaining * 1000)
        # Bypass the additional post-to-UI turn for data already on the GUI
        # thread. Only existing row values are written here, never new dialogs.
        self.handle_command('flush_row_updates')
        if self._pending_progress_recenter:
            self._flush_progress_recenter()

    def _detach_progress_render(self):
        runtime = getattr(self.view, '_gui_runtime', None)
        if self._progress_render_token is not None and runtime is not None:
            runtime.removeBeforeRenderCallback(self._progress_render_token)
        self._progress_render_token = None

    def hide(self):
        self._detach_progress_render()
        return super().hide()

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
        self._pending_progress_recenter.update(self.row_widgets)
        runtime = getattr(self.view, '_gui_runtime', None)
        if runtime is not None and self._progress_render_token is None:
            self._progress_render_token = runtime.addBeforeRenderCallback(self._flush_live_progress)
        self._schedule_window_balance()
        return shown

    def destroy(self):
        self._detach_progress_render()
        self.cancel_all(update_ui=False)
        self._pending_row_creations.clear()
        self._deferred_row_updates.clear()
        self._summary_refresh_scheduled = False
        self._window_balance_scheduled = False
        self._pending_progress_recenter.clear()
        self._progress_recenter_scheduled = False
        QtDialog.destroy(self)


__all__ = ["TransferCenterDialog", "TransferTaskHandle"]
