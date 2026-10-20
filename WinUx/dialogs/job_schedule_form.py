from __future__ import annotations

import inspect

from DearUIQt.backends import dpg
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.widgets import QLabel, QSpacer, QPushButton
from DearUIQt.modelview import QTableWidget
from DearUIQt.layouts import QVBoxLayout, QHBoxLayout
from DearUIQt.themes import DialogMetrics
from DearUIQt.themes import (
    METRICS, aligned_cell_theme, compact_stack_theme,
)


class JobScheduleDialog(QtDialog):
    REUSABLE_HOST = True
    DEFAULT_WIDTH = 840
    DEFAULT_HEIGHT = 260
    MIN_WINDOW_HEIGHT = 230
    MAX_WINDOW_HEIGHT = 500
    EMPTY_TABLE_HEIGHT = 72
    ROW_HEIGHT_HINT = 30
    HEADER_ROW_HEIGHT = METRICS.control_height
    TEXT_TOP_PAD = (METRICS.control_height - METRICS.check_size) // 2
    CHROME_HEIGHT = 188
    MAX_VISIBLE_ROWS = 7
    VIEWPORT_CHROME_HEIGHT = 40
    preferred_size = (DEFAULT_WIDTH, DEFAULT_HEIGHT)

    def __init__(self, view, schedule_provider, schedule_command):
        self.schedule_provider, self.schedule_command = schedule_provider, schedule_command
        # The WinUx schedule controller deliberately exposes blocking=False for
        # GUI snapshots.  Detect that capability once instead of acquiring its
        # locks in blocking mode every second on the render thread.  Generic
        # embedders with a legacy zero-argument provider retain old behavior.
        try:
            parameters = inspect.signature(schedule_provider).parameters.values()
            self._schedule_nonblocking = any(
                parameter.name == "blocking" or
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in parameters)
        except (TypeError, ValueError):
            self._schedule_nonblocking = False
        self._snapshot = None
        self._schedule_future = None
        self._schedule_request_generation = 0
        self._row_items = []
        self._header_cells = []
        self._header_recenter_scheduled = False
        self._geometry_balance_scheduled = False
        self._pending_geometry_row_count = None
        self._last_geometry_row_count = None
        super().__init__(view, "Job Schedule", self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        dpg.configure_item(self.tag, min_size=(680, self.MIN_WINDOW_HEIGHT))
        self.header("Job schedule", "Review pending and recent scheduled actions.")
        self._columns = (("Job", None), ("Action", 86), ("Scheduled time", 156),
                         ("Remaining", 88), ("Status", 92), ("Commands", 136))
        self.table_widget = self.own_widget(QTableWidget(
            0, len(self._columns), parent=self._qt_parent(self.content),
            after=view.after, backend=dpg, header_row=True, scroll_y=True,
            height=-30, width=-1, resizable=True, row_background=True,
            freeze_rows=1, grid_lines=True, sizing_policy=dpg.mvTable_SizingStretchProp))
        self.table = self.table_widget.tag
        self.table_widget.setHorizontalHeaderLabels([label for label, _width in self._columns])
        for column, (_label, width) in enumerate(self._columns):
            if width is None:
                self.table_widget.setColumnStretch(column, 1.0)
            else:
                self.table_widget.setColumnWidth(column, width)
        self.style_table(self.table)
        self._build_header_row()
        self.status = self.status_text("Loading schedule...")
        self.button_box([("Refresh", self.refresh, "secondary", False),
                         ("Close", self.destroy, "secondary", False)])
        self._refresh_timer = self.create_timer(1000, self.refresh, start=False)
        # Process-hosted dialogs still use the historical eager-visible
        # construction path, so initialize them here. In-process dialogs are
        # hidden until their complete tree is built; showEvent() performs the
        # one first refresh for that path and avoids a duplicate provider call.
        if self.isVisible():
            self.refresh()
            self._refresh_timer.start(1000)


    def showEvent(self, event):
        # QTimer-style lifetime: hidden retained dialogs consume no periodic
        # refresh budget. Reopen performs one immediate refresh and resumes.
        timer = getattr(self, "_refresh_timer", None)
        if timer is not None:
            self.refresh()
            timer.start(1000)

    def hideEvent(self, event):
        self._schedule_request_generation += 1
        timer = getattr(self, "_refresh_timer", None)
        if timer is not None:
            timer.stop()

    def _schedule_rows(self):
        if self._schedule_nonblocking:
            return self.schedule_provider(blocking=False)
        return self.schedule_provider()

    def _build_header_row(self):
        # QTableWidget owns the native header row. Keep these compatibility
        # fields so old geometry/debug hooks can inspect the form without
        # depending on DearPyGui table-row construction.
        self._header_cells = []
        self._header_row = None

    def _schedule_header_recenter(self):
        # Native QTableWidget headers are owned by the model/view layer and do
        # not require dialog-local post-layout recentering.
        self._header_recenter_scheduled = False

    def _flush_header_recenter(self):
        self._header_recenter_scheduled = False

    def _apply_layout(self):
        super()._apply_layout()

    def _target_window_height(self, row_count):
        row_count = max(0, int(row_count or 0))
        table_height = self.EMPTY_TABLE_HEIGHT
        if row_count:
            table_height = self.EMPTY_TABLE_HEIGHT + min(
                row_count, self.MAX_VISIBLE_ROWS) * self.ROW_HEIGHT_HINT
        return max(
            self.MIN_WINDOW_HEIGHT,
            min(self.MAX_WINDOW_HEIGHT, self.CHROME_HEIGHT + table_height),
        )

    def _schedule_geometry_balance(self, row_count):
        row_count = max(0, int(row_count or 0))
        if (row_count == self._last_geometry_row_count and
                self._pending_geometry_row_count is None):
            return
        self._pending_geometry_row_count = row_count
        if self._geometry_balance_scheduled:
            return
        self._geometry_balance_scheduled = True
        try:
            self.view.after(0, self._flush_geometry_balance)
        except Exception:
            self._geometry_balance_scheduled = False
            self._flush_geometry_balance()

    def _flush_geometry_balance(self):
        self._geometry_balance_scheduled = False
        row_count = self._pending_geometry_row_count
        self._pending_geometry_row_count = None
        if row_count is None or not self.winfo_exists():
            return
        self._last_geometry_row_count = row_count
        target = self._target_window_height(row_count)
        self.height = target
        try:
            dpg.configure_item(self.tag, height=target)
        except Exception:
            pass
        if bool(getattr(self.view, "is_standalone_ui_host", False)):
            try:
                dpg.set_viewport_height(target + self.VIEWPORT_CHROME_HEIGHT)
            except Exception:
                pass
        else:
            try:
                self.resize(self.width, target)
            except Exception:
                pass
        self._schedule_header_recenter()

    def refresh(self):
        if not self.winfo_exists():
            return False
        if not self._schedule_nonblocking:
            # A legacy provider has no nonblocking snapshot contract. It may
            # hold locks or do I/O, so it must never execute on the GUI thread.
            if self._schedule_future is not None and not self._schedule_future.isFinished():
                return False
            self._schedule_request_generation += 1
            generation = self._schedule_request_generation

            def collect():
                rows = self._schedule_rows()
                return None if rows is None else [tuple(row) for row in rows]

            def ready(rows):
                if (generation == self._schedule_request_generation and self.isVisible()
                        and rows is not None):
                    self.set_rows(rows)

            def failed(error):
                if generation == self._schedule_request_generation and self.isVisible():
                    self.set_control_value(self.status, "Schedule refresh failed: {}".format(error))

            self._schedule_future = self.runAsync(collect, on_result=ready, on_error=failed)
            return True
        rows = self._schedule_rows()
        # A non-blocking snapshot returns None on lock contention. Keep the
        # previous visible rows and try again on the next timer tick instead of
        # blocking the UI or briefly clearing/rebuilding the table.
        if rows is None:
            return False
        self.set_rows([tuple(row) for row in rows])
        return True

    def set_rows(self, rows):
        rows = [tuple(row) for row in rows]
        identities = [(str(row[5]), str(row[6])) for row in rows]
        previous = [] if self._snapshot is None else [
            (str(row[5]), str(row[6])) for row in self._snapshot]
        rebuilt = identities != previous

        if rebuilt:
            self.table_widget.setRowCount(0)
            self._row_items = []
            for row_index, row in enumerate(rows):
                self.table_widget.insertRow(row_index)
                native_row = self.table_widget.nativeRow(row_index)

                def text_cell(column, value):
                    holder_layout = QVBoxLayout(
                        parent=native_row, spacing=0, backend=dpg)
                    dpg.bind_item_theme(holder_layout.tag, aligned_cell_theme())
                    if self.TEXT_TOP_PAD:
                        QSpacer(0, self.TEXT_TOP_PAD, parent=holder_layout, backend=dpg)
                    label = QLabel(str(value), parent=holder_layout, backend=dpg)
                    self.table_widget.setCellWidget(row_index, column, holder_layout)
                    return label.tag

                cells = [text_cell(column, value) for column, value in enumerate(row[:5])]
                kind, key = str(row[5]), str(row[6])
                command_layout = QVBoxLayout(parent=native_row, spacing=0, backend=dpg)
                dpg.bind_item_theme(command_layout.tag, aligned_cell_theme())
                if self.TEXT_TOP_PAD:
                    QSpacer(
                        0, max(0, (self.ROW_HEIGHT_HINT - DialogMetrics.BUTTON_HEIGHT) // 2),
                        parent=command_layout, backend=dpg)
                lane_layout = QHBoxLayout(
                    parent=command_layout, spacing=DialogMetrics.BUTTON_GAP, backend=dpg)
                dpg.bind_item_theme(lane_layout.tag, compact_stack_theme())
                edit = QPushButton(
                    "Edit", parent=lane_layout, after=self.view.after, backend=dpg,
                    width=58, height=DialogMetrics.BUTTON_HEIGHT, role="secondary")
                edit.clicked.connect(
                    lambda kind=kind, key=key: self.request_action("edit", kind, key))
                cancel = QPushButton(
                    "Cancel", parent=lane_layout, after=self.view.after, backend=dpg,
                    width=68, height=DialogMetrics.BUTTON_HEIGHT, role="danger")
                cancel.clicked.connect(
                    lambda kind=kind, key=key: self.request_action("cancel", kind, key))
                self.table_widget.setCellWidget(row_index, 5, command_layout)
                self._row_items.append((cells, edit, cancel))

        for index, (row, (cells, edit, cancel)) in enumerate(zip(rows, self._row_items)):
            old_row = None if rebuilt else self._snapshot[index]
            for column, (cell, value) in enumerate(zip(cells, row[:5])):
                text = str(value)
                if old_row is not None and str(old_row[column]) != text:
                    dpg.set_value(cell, text)
            waiting = str(row[4]).casefold() == "waiting"
            if old_row is None or (str(old_row[4]).casefold() == "waiting") != waiting:
                edit.setEnabled(waiting)
                cancel.setEnabled(waiting)

        self._snapshot = rows
        self._schedule_geometry_balance(len(rows))
        if rebuilt or not previous:
            if not rows:
                text = "No scheduled actions | Updates automatically"
            elif len(rows) == 1:
                text = "1 scheduled action | Updates automatically"
            else:
                text = "{} scheduled actions | Updates automatically".format(len(rows))
            if self.control_value(self.status) != text:
                self.set_control_value(self.status, text)

    def destroy(self):
        self._geometry_balance_scheduled = False
        self._pending_geometry_row_count = None
        self._header_recenter_scheduled = False
        self._schedule_request_generation += 1
        return super().destroy()

    def request_refresh(self):
        self.view.after(0, self.refresh)

    def request_action(self, action, kind, key):
        self.view.after(0, self.schedule_command, str(action), str(kind), str(key))

    def handle_command(self, command, *args):
        if command == "set_rows":
            self.set_rows(*args)
        elif command == "status":
            self.set_control_value(self.status, str(args[0]))
