from __future__ import annotations

import itertools
import threading
import dearpygui.dearpygui as dpg
from .qt_dialog import QtDialog
from .theme import DialogMetrics
from ..components.qt_style import QtFusionPalette
from ..widgets.imgui_qt_style import (
    transfer_row_theme, form_row_theme, transfer_progress_host_theme,
)
from .logic.transfer import TransferCenterLogic, TransferTaskHandle, TransferItemRow

_TransferItemRow = TransferItemRow


class TransferCenterDialog(TransferCenterLogic, QtDialog):
    """Modeless DPG transfer center; coalesced task updates retain old handles."""

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
        self._pending_progress_recenter = set()
        self.row_widgets = {}
        QtDialog.__init__(self, view, "Transfer Center", 760, 340, modal=False)
        self.header("Transfers", "Per-file progress and queue controls.")
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

    def _paint_progress(self, row_id, retry=0):
        row = self.row_widgets.get(row_id)
        if not row:
            self._pending_progress_recenter.discard(row_id)
            return
        host = row.get("progress_host")
        canvas = row.get("progress_canvas")
        bg = row.get("progress_bg")
        fill = row.get("progress_fill")
        label = row.get("progress_text")
        if not host or not canvas or not bg or not fill or not label:
            self._pending_progress_recenter.discard(row_id)
            return
        try:
            width, _height = dpg.get_item_rect_size(host)
            if width <= 8:
                if retry > 0:
                    self.view.after(16, lambda _row_id=row_id, _retry=retry - 1: self._paint_progress(_row_id, _retry))
                    return
                self._pending_progress_recenter.discard(row_id)
                return
            width = max(12, int(round(width)))
            height = int(DialogMetrics.BUTTON_HEIGHT)
            ratio = max(0.0, min(1.0, float(row.get("ratio", 0.0))))
            dpg.configure_item(canvas, width=width, height=height, pos=(0, 0))
            dpg.configure_item(
                bg, pmin=(0, 0), pmax=(width - 1, height - 1),
                color=QtFusionPalette.BORDER, fill=QtFusionPalette.BASE, thickness=1.0)
            fill_right = 1 + int(round(max(0, width - 2) * ratio))
            fill_right = max(1, min(width - 1, fill_right))
            dpg.configure_item(
                fill, pmin=(1, 1), pmax=(fill_right, height - 2),
                color=QtFusionPalette.HIGHLIGHT, fill=QtFusionPalette.HIGHLIGHT, thickness=0.0)
            text = "{:.1f}%".format(ratio * 100.0)
            text_size = dpg.get_text_size(text)
            text_w = float(text_size[0]) if text_size else 0.0
            text_h = float(text_size[1]) if text_size and len(text_size) > 1 else 13.0
            x = max(0, int(round((width - text_w) * 0.5)))
            y = max(0, int(round((height - text_h) * 0.5)))
            text_color = QtFusionPalette.HIGHLIGHT_TEXT if ratio >= 0.50 else QtFusionPalette.TEXT
            dpg.configure_item(label, pos=(x, y), text=text, color=text_color)
        except Exception:
            if retry > 0:
                self.view.after(16, lambda _row_id=row_id, _retry=retry - 1: self._paint_progress(_row_id, _retry))
                return
        self._pending_progress_recenter.discard(row_id)

    def _schedule_progress_paint(self, row_id, retries=3):
        if row_id in self._pending_progress_recenter:
            return
        self._pending_progress_recenter.add(row_id)
        self.view.after(0, lambda _row_id=row_id, _retry=retries: self._paint_progress(_row_id, _retry))

    def _set_progress_text(self, row_id, ratio):
        row = self.row_widgets.get(row_id)
        if not row:
            return
        row["ratio"] = max(0.0, min(1.0, float(ratio)))
        self._schedule_progress_paint(row_id)

    def handle_command(self, command, *args):
        if command == "add_row":
            row_id, operation, name = args
            group = dpg.add_child_window(
                parent=self.content, width=-1, height=84, border=True,
                no_scrollbar=True, no_scroll_with_mouse=True,
            )
            dpg.bind_item_theme(group, transfer_row_theme(dpg))
            title = dpg.add_text("{}: {}".format(operation, name), parent=group)
            table = dpg.add_table(
                parent=group, header_row=False, width=-1,
                policy=dpg.mvTable_SizingStretchProp, pad_outerX=False,
                borders_innerH=False, borders_outerH=False,
                borders_innerV=False, borders_outerV=False,
            )
            dpg.bind_item_theme(table, form_row_theme(dpg))
            dpg.add_table_column(parent=table, width_stretch=True)
            dpg.add_table_column(parent=table, width_fixed=True, init_width_or_weight=10)
            dpg.add_table_column(parent=table, width_fixed=True, init_width_or_weight=86)
            with dpg.table_row(parent=table) as row_parent:
                progress_host = dpg.add_child_window(
                    parent=row_parent, width=-1, height=DialogMetrics.BUTTON_HEIGHT,
                    border=False, no_scrollbar=True, no_scroll_with_mouse=True,
                )
                dpg.bind_item_theme(progress_host, transfer_progress_host_theme(dpg))
                # Transfer progress is one custom-drawn surface. Keeping fill,
                # frame, and text on the same drawlist avoids Dear ImGui's
                # native overlay behavior, which moves text with the filled area.
                progress_canvas = dpg.add_drawlist(
                    width=1, height=DialogMetrics.BUTTON_HEIGHT,
                    parent=progress_host, pos=(0, 0))
                progress_bg = dpg.draw_rectangle(
                    (0, 0), (1, DialogMetrics.BUTTON_HEIGHT - 1),
                    parent=progress_canvas, color=QtFusionPalette.BORDER,
                    fill=QtFusionPalette.BASE, thickness=1.0)
                progress_fill = dpg.draw_rectangle(
                    (1, 1), (1, DialogMetrics.BUTTON_HEIGHT - 2),
                    parent=progress_canvas, color=QtFusionPalette.HIGHLIGHT,
                    fill=QtFusionPalette.HIGHLIGHT, thickness=0.0)
                progress_text = dpg.draw_text(
                    (0, 0), "0.0%", parent=progress_canvas,
                    color=QtFusionPalette.TEXT, size=13)
                dpg.add_spacer(parent=row_parent, width=10)
                action = self.action(
                    "Cancel",
                    lambda _row_id=row_id: self._request_row_action(_row_id),
                    "secondary",
                    False,
                    parent=row_parent,
                    width=86,
                    height=DialogMetrics.BUTTON_HEIGHT,
                )
            stats = self.status_text("Queued", parent=group, wrap=650)
            self.row_widgets[row_id] = {"group": group, "title": title,
                "progress_host": progress_host, "progress_canvas": progress_canvas,
                "progress_bg": progress_bg, "progress_fill": progress_fill,
                "progress_text": progress_text, "ratio": 0.0,
                "stats": stats, "action": action,
                "operation": operation, "name": name, "status": "Queued", "statistics": ""}
            try:
                with dpg.item_handler_registry() as resize_registry:
                    dpg.add_item_resize_handler(
                        callback=lambda *_args, _row_id=row_id: self._schedule_progress_paint(_row_id))
                dpg.bind_item_handler_registry(progress_host, resize_registry)
                self._control_handler_registries.append(resize_registry)
            except Exception:
                pass
            self._schedule_progress_paint(row_id, retries=4)
        elif command == "remove_row":
            row_id = args[0]
            self._pending_progress_recenter.discard(row_id)
            row = self.row_widgets.pop(row_id, None)
            if row:
                dpg.delete_item(row["group"])
        elif command == "flush_row_updates":
            for row_id, values in self._take_pending_row_updates():
                row = self.row_widgets.get(row_id)
                if not row:
                    continue
                for key in ("name", "status", "statistics"):
                    if key in values:
                        row[key] = values[key]
                dpg.set_value(row["title"], "{}: {}".format(row["operation"], row["name"]))
                dpg.set_value(row["stats"], "{} | {}".format(row["status"], row["statistics"]))
                if "ratio" in values:
                    self._set_progress_text(row_id, values["ratio"])
                if "action" in values:
                    wrapper = self._control_wrappers.get(row["action"])
                    if wrapper is not None:
                        wrapper.setText(values["action"])
                    else:
                        dpg.configure_item(row["action"], label=values["action"])
                if "action_enabled" in values:
                    self.set_control_enabled(row["action"], bool(values["action_enabled"]))

    def destroy(self):
        self.cancel_all(update_ui=False)
        QtDialog.destroy(self)


__all__ = ["TransferCenterDialog", "TransferTaskHandle"]
