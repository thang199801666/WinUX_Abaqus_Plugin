"""Excel-friendly two-column XY worksheet used by Reference Chart.

The worksheet deliberately separates *model availability* from *native row
construction*.  A saved reference is attached to ``ReferenceTableModel`` in
O(1), the dialog is allowed to present, and the complete native table is then
materialized in short event-loop batches.  This gives users a normal table with
all rows/native scrolling without putting an O(N) construction wall in front of
the first dialog frame.
"""
from __future__ import annotations

from time import perf_counter

from DearUIQt.core import Qt, QGlobalInputBinding
from DearUIQt.input_gate import popup_input_active
from DearUIQt.gui import (
    QClipboard, QCursor, QKeyboard, QtFusionMetrics, QtFusionPalette,
)
from DearUIQt.widgets import QLineEdit, QFrame, QMenu
from DearUIQt.modelview import QTableWidget, QTableWidgetItem
from DearUIQt.themes import worksheet_theme_spec

from ...services.reference_charts import ReferenceTableModel
from .reference_qt_model import ReferenceWorksheetQtModel




class _PassiveNavigationControl:
    """Non-visual compatibility target for deferred navigation state updates.

    The worksheet no longer exposes explicit First/Prev/Next/Last chrome or a
    loading/count label, but population code and regression tests still route
    their state changes through these attributes.  A tiny stub keeps that
    contract without reserving any layout space above the sheet.
    """

    def __init__(self):
        self.enabled = True
        self.text = ""

    def setEnabled(self, value):
        self.enabled = bool(value)

    def setText(self, value):
        self.text = str(value)


class _ReferenceCellEditorAccess:
    """Compatibility accessor that activates the one transient cell editor.

    Older callers/tests accessed ``sheet.cells[row, column]`` because every
    visible cell used to own a permanent QLineEdit.  The full-row table keeps
    only one editor alive at a time (Qt delegate semantics), but retaining this
    accessor avoids forcing application code to know that implementation detail.
    """

    def __init__(self, owner):
        self._owner = owner

    def __getitem__(self, position):
        row, column = map(int, position)
        editor = self._owner._activate_editor(row, column, focus=False)
        if editor is None:
            raise KeyError(position)
        return editor

    def get(self, position, default=None):
        try:
            return self[position]
        except (KeyError, TypeError, ValueError):
            return default

    def __len__(self):
        return 1 if self._owner._active_editor is not None else 0

    def items(self):
        if self._owner._active_editor is None or self._owner._active_position is None:
            return ()
        return ((self._owner._active_position, self._owner._active_editor),)


class ReferenceDataTable:
    """Editable X/Y grid for exactly one reference chart at a time.

    All logical rows are eventually represented by native table rows.  Native
    construction is deferred and time-sliced so opening the Reference Chart is
    independent of the number of points.  Editing uses one transient QLineEdit
    at the active cell instead of two persistent editors per row.
    """

    ROW_NUMBER_WIDTH = 32
    VALUE_COLUMN_WIDTH = 150
    TABLE_WIDTH = ROW_NUMBER_WIDTH + (2 * VALUE_COLUMN_WIDTH) + 18
    PASTE_TRAILING_ROWS = 5

    # A single population turn may use only a small piece of the GUI frame.
    # Native widget creation remains on the one QApplication/UI thread; the
    # event loop regains control between batches so first paint, input and close
    # requests are never queued behind thousands of row creations.
    FIRST_POPULATE_BUDGET_MS = 2.0
    POPULATE_BUDGET_MS = 4.0
    POPULATE_MIN_BATCH = 4
    POPULATE_MAX_BATCH = 128
    POPULATE_INITIAL_BATCH = 24

    def __init__(self, parent, after, on_error, height=285, menu_parent=None,
                 on_import=None, on_change=None):
        self.after, self.on_error = after, on_error
        self.on_import, self.on_change = on_import, on_change
        self.model = ReferenceTableModel()
        self.qt_model = ReferenceWorksheetQtModel(self.model)
        self._closed = False
        self._disposed = False
        self.current_cell = (0, 0)

        self._population_generation = 0
        self._population_cursor = 0
        self._population_target = 0
        self._population_scheduled = False
        self._population_complete = False
        self._population_batch_hint = self.POPULATE_INITIAL_BATCH
        self._pending_focus = None
        self._scroll_to_end_when_ready = False
        self._navigation_enabled = None
        self._population_label_text = None

        self._active_editor = None
        self._active_position = None
        self.cells = _ReferenceCellEditorAccess(self)

        # Excel-like row selection is independent from the transient X/Y cell
        # editor. Clicking the row-number gutter selects whole rows; Ctrl-click
        # toggles rows and Shift-click extends from an anchor. Ctrl+C copies
        # exactly those selected X/Y rows as tab-delimited text.
        self._selected_rows = set()
        self._selection_anchor = None

        self._frame = QFrame(
            parent=parent, width=-1, height=int(height), frame_shape=QFrame.NoFrame,
            no_scrollbar=True, no_scroll_with_mouse=True)
        self.tag = self._frame.tag
        self._theme = worksheet_theme_spec().createObject(parent=self._frame)
        self._frame.setTheme(self._theme)
        self._clipboard = QClipboard(backend=self._frame.backend)

        # The worksheet now behaves like a plain spreadsheet pane: mouse-wheel,
        # scrollbar and keyboard navigation remain available, but the redundant
        # First/Prev/Next/Last bar and row-count/loading label are removed from
        # the visible layout so the sheet can start directly below the header.
        # Passive controls preserve the state-update/testing contract without
        # reserving any UI space inside the dialog.
        self._first_page = _PassiveNavigationControl()
        self._previous_page = _PassiveNavigationControl()
        self._page_label = _PassiveNavigationControl()
        self._next_page = _PassiveNavigationControl()
        self._last_page = _PassiveNavigationControl()

        self._key_binding = QGlobalInputBinding(parent=self._frame)
        self._key_binding.onKeyPress(Qt.Key_C, self._key_pressed, user_data=Qt.Key_C)
        self._key_binding.onKeyPress(Qt.Key_V, self._key_pressed, user_data=Qt.Key_V)
        self._key_binding.onKeyPress(Qt.Key_Return, self._key_pressed, user_data=Qt.Key_Return)
        self._key_binding.onKeyPress(Qt.Key_Enter, self._key_pressed, user_data=Qt.Key_Enter)
        self._key_binding.onKeyPress(Qt.Key_PageUp, self._key_pressed, user_data=Qt.Key_PageUp)
        self._key_binding.onKeyPress(Qt.Key_PageDown, self._key_pressed, user_data=Qt.Key_PageDown)
        self._key_binding.onKeyPress(Qt.Key_Home, self._key_pressed, user_data=Qt.Key_Home)
        self._key_binding.onKeyPress(Qt.Key_End, self._key_pressed, user_data=Qt.Key_End)
        # One global click binding is cheaper than one native handler registry
        # per cell and still lets the table use a single delegate-style editor.
        # Mouse work is intentionally deferred to button release. DearPyGui
        # dispatches global click handlers in the same native press cycle as
        # ordinary controls; mutating/focusing worksheet children from that
        # press can cancel a combo/list popup elsewhere in the dialog. Qt-like
        # release routing lets the native control finish its own gesture first.
        self._key_binding.onMouseRelease(Qt.LeftButton, self._mouse_left_released)
        self._key_binding.onMouseRelease(Qt.RightButton, self._mouse_right_released)
        self._key_binding.activate()

        self._context_menu = QMenu([
            {"id": "paste", "label": "Paste", "action": "paste"},
            {"id": "copy_cell", "label": "Copy cell", "action": "copy_cell"},
            {"id": "copy_table", "label": "Copy selected row(s)", "action": "copy_table"},
            {"label": "---"},
            {"id": "clear_cell", "label": "Clear cell", "action": "clear_cell"},
            {"id": "clear_row", "label": "Clear row", "action": "clear_row"},
            {"id": "clear_all", "label": "Clear all data", "action": "clear_all"},
            {"label": "---"},
            {"id": "add_rows", "label": "Add 10 rows", "action": "add_rows"},
        ], after=self.after, min_width=170, parent_window=menu_parent)
        self._context_menu.triggered.connect(self._context_action)

        self._create_table()
        # Do not synchronously create even the default rows.  Let the owner show
        # its dialog first, then populate on the next UI event-loop turn.
        self._schedule_population_from(0)

    # ------------------------------------------------------------------
    # Native table construction / deferred full population
    # ------------------------------------------------------------------
    def _create_table(self):
        self._table_widget = QTableWidget(
            0, 3, parent=self._frame,
            width=self.TABLE_WIDTH, height=-1,
            sizing_policy=QTableWidget.FixedFit, scroll_x=False, scroll_y=True,
            freeze_rows=1, freeze_columns=1, resizable=True, row_background=True,
            grid_lines=True, saved_settings=False)
        self._table_widget.setHorizontalHeaderLabels(("#", "X", "Y"))
        self._table_widget.setColumnWidth(0, self.ROW_NUMBER_WIDTH)
        self._table_widget.setColumnResizable(0, False)
        self._table_widget.setColumnWidth(1, self.VALUE_COLUMN_WIDTH)
        self._table_widget.setColumnWidth(2, self.VALUE_COLUMN_WIDTH)
        self._table_widget.setTheme(self._theme)
        self.table = self._table_widget.tag

    def _schedule_population_from(self, start=0):
        """Schedule a complete native-table sync without blocking this turn."""
        if self._closed:
            return False
        self._read_inputs()
        self._population_generation += 1
        generation = self._population_generation
        self._population_cursor = max(0, int(start))
        self._population_target = int(self.model.row_count)
        self._population_complete = False
        self._population_scheduled = True
        self._update_population_label()
        self.after(1, self._populate_batch, generation)
        return True

    def _extend_population_target(self):
        """Extend an existing population pass after paste/add-row operations."""
        if self._closed:
            return False
        target = int(self.model.row_count)
        if self._population_scheduled:
            self._population_target = max(self._population_target, target)
            return True
        if self._table_widget.rowCount() < target:
            self._population_generation += 1
            generation = self._population_generation
            self._population_cursor = self._table_widget.rowCount()
            self._population_target = target
            self._population_complete = False
            self._population_scheduled = True
            self._update_population_label()
            self.after(1, self._populate_batch, generation)
            return True
        return False

    def _update_population_label(self):
        if self._closed:
            return
        native_rows = self._table_widget.rowCount()
        target = max(0, int(self._population_target or self.model.row_count))
        synced = min(max(0, self._population_cursor), target)
        if self._population_scheduled or native_rows != target:
            label = "Loading {:,} / {:,} rows…".format(synced, target)
        else:
            label = "{:,.0f} rows".format(target)
        # A native configure call per button per population batch is wasted
        # after the first row has arrived. Retain the last applied state while
        # leaving every logical row available to the normal table scroller.
        if getattr(self, "_population_label_text", None) != label:
            self._page_label.setText(label)
            self._population_label_text = label
        enabled = native_rows > 0
        if getattr(self, "_navigation_enabled", None) != enabled:
            for button in (self._first_page, self._previous_page,
                           self._next_page, self._last_page):
                button.setEnabled(enabled)
            self._navigation_enabled = enabled

    def _ensure_native_row(self, row):
        table = self._table_widget
        while table.rowCount() <= row:
            table.insertRow(table.rowCount())
        if table.item(row, 0) is None:
            number = QTableWidgetItem(str(row + 1))
            number.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            table.setItem(row, 0, number)
        else:
            item = table.item(row, 0)
            text = str(row + 1)
            if item.text() != text:
                item.setText(text)
        # The Qt model stays a sparse read-through adapter, not a second grid.
        values = getattr(self, "qt_model", self.model).row_text(row)
        for logical_column, value in enumerate(values):
            table_column = logical_column + 1
            item = table.item(row, table_column)
            if item is None:
                item = QTableWidgetItem(str(value or ""))
                table.setItem(row, table_column, item)
            elif self._active_position != (row, logical_column):
                text = str(value or "")
                if item.text() != text:
                    item.setText(text)
        if row in getattr(self, "_selected_rows", set()):
            self._set_row_highlight(row, True)

    def _populate_batch(self, generation):
        if self._closed or generation != self._population_generation:
            return
        self._population_scheduled = False
        target = int(self.model.row_count)
        self._population_target = target
        started = perf_counter()
        first_native_batch = (self._population_cursor == 0 and
                              self._table_widget.rowCount() == 0)
        budget_ms = (self.FIRST_POPULATE_BUDGET_MS if first_native_batch
                     else self.POPULATE_BUDGET_MS)
        budget = budget_ms / 1000.0
        processed = 0
        max_batch = max(self.POPULATE_MIN_BATCH,
                        min(self.POPULATE_MAX_BATCH, int(self._population_batch_hint)))

        # Update/create the complete logical row set. Existing native rows are
        # reused, so reopening or switching similarly-sized references is much
        # cheaper than deleting/recreating the whole table.
        while self._population_cursor < target and processed < max_batch:
            self._ensure_native_row(self._population_cursor)
            self._population_cursor += 1
            processed += 1
            if processed >= self.POPULATE_MIN_BATCH and perf_counter() - started >= budget:
                break

        # When a newly selected series is shorter, trim old tail rows in the
        # same bounded manner. QTableWidget has an optimized tail-remove path.
        while (self._population_cursor >= target
               and self._table_widget.rowCount() > target
               and processed < max_batch):
            self._table_widget.removeRow(self._table_widget.rowCount() - 1)
            processed += 1
            if processed >= self.POPULATE_MIN_BATCH and perf_counter() - started >= budget:
                break

        elapsed = max(1e-6, perf_counter() - started)
        if processed:
            estimate = int(processed * (budget / elapsed))
            self._population_batch_hint = max(
                self.POPULATE_MIN_BATCH,
                min(self.POPULATE_MAX_BATCH, (self._population_batch_hint + estimate) // 2))

        if self._population_cursor < target or self._table_widget.rowCount() > target:
            self._population_scheduled = True
            self._update_population_label()
            self.after(1, self._populate_batch, generation)
            return

        self._population_complete = True
        self._population_scheduled = False
        self._population_cursor = target
        self._update_population_label()

        pending = self._pending_focus
        self._pending_focus = None
        if pending is not None:
            self.after(1, self.focus_cell, *pending)
        if self._scroll_to_end_when_ready:
            self._scroll_to_end_when_ready = False
            self.after(1, self._scroll_last)

    @property
    def population_complete(self):
        return bool(self._population_complete and
                    self._table_widget.rowCount() == self.model.row_count)

    def materialized_row_count(self):
        return int(self._table_widget.rowCount())

    # ------------------------------------------------------------------
    # One transient editor (QStyledItemDelegate-like behavior)
    # ------------------------------------------------------------------
    def _read_inputs(self):
        self._commit_active_editor()

    def _activate_editor(self, row, column, *, focus=True):
        if self._closed:
            return None
        row, column = int(row), int(column)
        if column not in (0, 1) or not 0 <= row < self.model.row_count:
            return None
        if row >= self._table_widget.rowCount():
            # Never synchronously construct thousands of preceding rows just to
            # satisfy one far-away focus request. Population continues in the
            # event loop and the requested focus is applied when rows exist.
            self._pending_focus = (row, column)
            return None
        if self._active_position == (row, column) and self._active_editor is not None:
            if focus:
                self._active_editor.setFocus()
            return self._active_editor

        self._commit_active_editor()
        self.current_cell = (row, column)
        row_tag = self._table_widget.nativeRow(row)
        editor = QLineEdit(
            self.model.cell_text(row, column), parent=row_tag, width=-1,
            auto_select_all=True, callback=self._editor_changed)
        self._table_widget.setCellWidget(row, column + 1, editor)
        self._active_editor = editor
        self._active_position = (row, column)
        if focus:
            editor.setFocus()
        return editor

    def _editor_changed(self, sender, text, _user=None):
        editor = self._active_editor
        position = self._active_position
        if self._closed or editor is None or position is None or editor.tag != sender:
            return
        row, column = position
        if self.qt_model.setData(self.qt_model.index(row, column), str(text or "")):
            self.current_cell = position
            self._changed()

    def _commit_active_editor(self):
        editor = self._active_editor
        position = self._active_position
        if editor is None or position is None:
            return False
        row, column = position
        try:
            text = editor.text()
        except Exception:
            text = self.model.cell_text(row, column)
        changed = self.qt_model.setData(self.qt_model.index(row, column), text)
        try:
            editor.delete()
        except Exception:
            pass
        self._active_editor = None
        self._active_position = None
        try:
            self._table_widget.removeCellWidget(row, column + 1)
        except Exception:
            pass
        item = self._table_widget.item(row, column + 1)
        if item is not None:
            value = self.model.cell_text(row, column)
            if item.text() != value:
                item.setText(value)
        if changed:
            self._changed()
        return True

    # ------------------------------------------------------------------
    # Excel-like whole-row selection / clipboard
    # ------------------------------------------------------------------
    @property
    def selected_rows(self):
        return tuple(sorted(self._selected_rows))

    def _set_row_highlight(self, row, selected):
        row = int(row)
        if not 0 <= row < self._table_widget.rowCount():
            return False
        try:
            if selected:
                self._table_widget.backend.highlight_table_row(
                    self.table, row, QtFusionPalette.SELECTION_ACTIVE)
            else:
                self._table_widget.backend.unhighlight_table_row(self.table, row)
            return True
        except Exception:
            return False

    def _apply_row_selection(self, rows, anchor=None):
        normalized = {int(row) for row in rows
                      if 0 <= int(row) < self.model.row_count}
        previous = set(self._selected_rows)
        if normalized == previous and (
                (anchor is None and self._selection_anchor is None)
                or anchor == self._selection_anchor):
            return False
        for row in previous - normalized:
            self._set_row_highlight(row, False)
        self._selected_rows = normalized
        for row in normalized - previous:
            self._set_row_highlight(row, True)
        if anchor is not None:
            self._selection_anchor = int(anchor)
        elif not normalized:
            self._selection_anchor = None
        return True

    def clear_row_selection(self):
        return self._apply_row_selection(set(), anchor=None)

    def select_row(self, row, *, ctrl=False, shift=False):
        row = int(row)
        if not 0 <= row < self.model.row_count:
            return False
        self._commit_active_editor()
        current = set(self._selected_rows)
        anchor = self._selection_anchor
        if shift and anchor is not None:
            first, last = sorted((int(anchor), row))
            span = set(range(first, last + 1))
            target = current | span if ctrl else span
            return self._apply_row_selection(target, anchor=anchor)
        if ctrl:
            if row in current:
                current.remove(row)
            else:
                current.add(row)
            return self._apply_row_selection(current, anchor=row)
        return self._apply_row_selection({row}, anchor=row)

    def _row_header_at_pointer(self):
        if self._closed or popup_input_active():
            return None
        point = self._pointer_position()
        if point is None or not self._table_under_mouse(point):
            return None
        x, y = point
        row = self._row_at_pointer(y)
        if row is None:
            return None
        try:
            table_left = float(
                self._table_widget.backend.get_item_rect_min(self._table_widget.tag)[0])
        except Exception:
            return None
        native_x = self._table_widget.nativeItem(row, 1)
        if native_x is not None:
            try:
                x_start = float(
                    self._table_widget.backend.get_item_rect_min(native_x)[0])
            except Exception:
                x_start = table_left + self.ROW_NUMBER_WIDTH
        else:
            x_start = table_left + self.ROW_NUMBER_WIDTH
        return row if table_left <= x < x_start else None

    def copy_selected_rows(self):
        if self._closed:
            return False
        self._read_inputs()
        rows = [row for row in sorted(self._selected_rows)
                if 0 <= row < self.model.row_count]
        if not rows:
            self.on_error("Select one or more rows using the # column, then copy.")
            return False
        text = "\n".join(
            "\t".join(map(str, self.model.row_text(row))) for row in rows)
        self._clipboard.setText(text)
        return True

    # ------------------------------------------------------------------
    # Pointer hit testing / native scrolling
    # ------------------------------------------------------------------
    @staticmethod
    def _point_in_native_rect(backend, tag, point):
        """Hit-test current renderer geometry instead of last-frame hover state.

        ``is_item_hovered`` is sampled by Dear ImGui during rendering. A quick
        move from the worksheet to a combo can therefore leave the cell/table
        reported as hovered for one callback turn. Global mouse handlers must
        not use that stale state or they can refocus the worksheet and close
        the combo popup that was just clicked.
        """
        if tag is None or point is None:
            return False
        try:
            left, top = backend.get_item_rect_min(tag)
            width, height = backend.get_item_rect_size(tag)
            x, y = float(point[0]), float(point[1])
            left, top = float(left), float(top)
            width, height = float(width), float(height)
            return (width > 0.0 and height > 0.0
                    and left <= x < left + width
                    and top <= y < top + height)
        except Exception:
            return False

    def _pointer_position(self):
        try:
            point = QCursor.pos(backend=self._frame.backend)
            return float(point.x()), float(point.y())
        except Exception:
            return None

    def _table_under_mouse(self, point=None):
        table = getattr(self, "_table_widget", None)
        if table is None:
            return False
        point = self._pointer_position() if point is None else point
        if self._point_in_native_rect(table.backend, table.tag, point):
            return True
        editor = self._active_editor
        return bool(editor is not None and self._point_in_native_rect(
            editor.backend, editor.tag, point))

    def _row_at_pointer(self, y):
        # Native hit testing lives in DearUIQt's shared table view.  The view
        # probes the estimated native row first, avoiding repeated broad scans
        # on every worksheet click as data sets grow.
        row = self._table_widget.rowAtGlobal(y)
        return None if row < 0 else row

    def _cell_at_pointer(self):
        if self._closed or popup_input_active():
            return None
        point = self._pointer_position()
        if point is None or not self._table_under_mouse(point):
            return None
        x, y = point
        editor = self._active_editor
        if (editor is not None and self._active_position is not None
                and self._point_in_native_rect(editor.backend, editor.tag, point)):
            return self._active_position
        row = self._row_at_pointer(y)
        if row is None:
            return None
        # During an in-place series switch the table may temporarily retain
        # old native rows below the population cursor.  They are intentionally
        # reused for speed, but must not become editable until their text has
        # been synchronized to the newly selected model.
        if self._population_scheduled and row >= self._population_cursor:
            return None
        starts = []
        backend = self._table_widget.backend
        for table_column in range(3):
            native = self._table_widget.nativeItem(row, table_column)
            if native is None and self._active_position == (row, table_column - 1):
                native = getattr(self._active_editor, "tag", None)
            if native is None:
                starts.append(None)
                continue
            try:
                starts.append(float(backend.get_item_rect_min(native)[0]))
            except Exception:
                starts.append(None)
        # X and Y starts are enough to disambiguate the two editable columns.
        x_start, y_start = starts[1], starts[2]
        if x_start is None:
            try:
                table_left = float(backend.get_item_rect_min(self._table_widget.tag)[0])
            except Exception:
                table_left = 0.0
            x_start = table_left + self.ROW_NUMBER_WIDTH
        if y_start is None:
            y_start = x_start + self.VALUE_COLUMN_WIDTH
        if x < x_start:
            return None
        return (row, 0 if x < y_start else 1)

    def _mouse_left_released(self, *_args):
        row = self._row_header_at_pointer()
        if row is not None:
            ctrl = QKeyboard.isControlDown(backend=self._frame.backend)
            shift = QKeyboard.isShiftDown(backend=self._frame.backend)
            # Do not alter the native table tree inside the renderer's release
            # callback. Schedule the selection after native control dispatch.
            self.after(1, self._select_row_deferred, row, ctrl, shift)
            return
        position = self._cell_at_pointer()
        if position is not None:
            # Excel-like split of responsibilities: row numbers select whole
            # rows, while X/Y cells remain directly editable. Keep all focus
            # changes out of the global release callback itself.
            self.after(1, self._activate_clicked_cell, *position)

    def _select_row_deferred(self, row, ctrl=False, shift=False):
        if self._closed:
            return
        self.select_row(row, ctrl=bool(ctrl), shift=bool(shift))

    def _activate_clicked_cell(self, row, column):
        if self._closed:
            return
        self.clear_row_selection()
        self._activate_editor(row, column)

    def _mouse_right_released(self, *_args):
        row = self._row_header_at_pointer()
        if row is not None:
            self.after(1, self._open_row_context_menu, row)
            return
        position = self._cell_at_pointer()
        if position is None:
            return
        self.current_cell = position
        self.after(1, self._open_context_menu, position)

    def _open_row_context_menu(self, row):
        if self._closed:
            return
        row = int(row)
        if row not in self._selected_rows:
            self.select_row(row)
        self.current_cell = (row, 0)
        self._open_context_menu(self.current_cell)

    def _scroll_first(self):
        if self._closed:
            return
        try:
            self._table_widget.backend.set_y_scroll(self.table, 0.0)
        except Exception:
            pass

    def _scroll_last(self):
        if self._closed:
            return
        if not self.population_complete:
            self._scroll_to_end_when_ready = True
            return
        try:
            backend = self._table_widget.backend
            backend.set_y_scroll(self.table, float(backend.get_y_scroll_max(self.table)))
        except Exception:
            pass

    def _scroll_page(self, direction):
        if self._closed:
            return
        try:
            backend = self._table_widget.backend
            current = float(backend.get_y_scroll(self.table))
            height = float(backend.get_item_rect_size(self.table)[1])
            maximum = float(backend.get_y_scroll_max(self.table))
            target = max(0.0, min(maximum, current + float(direction) * max(1.0, height * .85)))
            backend.set_y_scroll(self.table, target)
        except Exception:
            pass

    def _scroll_to_row(self, row):
        if self._closed or not 0 <= int(row) < self._table_widget.rowCount():
            return False
        try:
            backend = self._table_widget.backend
            maximum = float(backend.get_y_scroll_max(self.table))
            target = min(maximum, max(0.0, float(row) * float(QtFusionMetrics.ROW_HEIGHT)))
            backend.set_y_scroll(self.table, target)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Editing / clipboard behavior
    # ------------------------------------------------------------------
    def _changed(self):
        if self.on_change is not None and not self._closed:
            self.on_change()

    def _open_context_menu(self, position):
        if self._closed:
            return
        self.current_cell = position
        point = QCursor.pos(backend=self._frame.backend)
        self._context_menu.popup((point.x(), point.y()), context=position)

    def _context_action(self, action, context=None):
        if self._closed:
            return
        if isinstance(context, (tuple, list)) and len(context) == 2:
            self.current_cell = (int(context[0]), int(context[1]))
        action = str(action or "")
        if action == "paste":
            self.after(1, self.paste_clipboard)
        elif action == "copy_cell":
            self.copy_cell()
        elif action == "copy_table":
            self.copy_selected_rows()
        elif action == "clear_cell":
            self.after(1, self.clear_current_cell)
        elif action == "clear_row":
            self.after(1, self.clear_current_row)
        elif action == "clear_all":
            self.after(1, self.clear_cells)
        elif action == "add_rows":
            self.after(1, self.add_rows)

    def focused_position(self):
        if self._closed or self._active_editor is None or self._active_position is None:
            return None
        try:
            return self._active_position if self._active_editor.hasFocus() else None
        except Exception:
            return None

    def owns_keyboard(self):
        return self.focused_position() is not None

    def _key_pressed(self, _sender, _native_key, qt_key=None):
        ctrl = QKeyboard.isControlDown(backend=self._frame.backend)
        # Whole-row selection intentionally commits/closes the transient cell
        # editor, so Ctrl+C must work even when no X/Y editor currently owns
        # keyboard focus.  The binding is scoped to this worksheet instance.
        if qt_key == Qt.Key_C and ctrl and self._selected_rows:
            self.copy_selected_rows()
            return
        position = self.focused_position()
        if position is None:
            return
        row, column = position
        if qt_key == Qt.Key_C and ctrl:
            self.copy_selected_rows()
        elif qt_key == Qt.Key_V and ctrl:
            text = self._clipboard.text()
            if any(separator in text for separator in ("\t", "\n", "\r", ",", ";")):
                self.after(1, self.paste_text, text, position)
        elif qt_key in (Qt.Key_Return, Qt.Key_Enter):
            target = max(0, row + (-1 if QKeyboard.isShiftDown(backend=self._frame.backend) else 1))
            self.after(1, self.move_cell, target, column)
        elif qt_key == Qt.Key_PageUp:
            self.after(1, self._scroll_page, -1)
        elif qt_key == Qt.Key_PageDown:
            self.after(1, self._scroll_page, +1)
        elif qt_key == Qt.Key_Home:
            self.after(1, self._scroll_first)
        elif qt_key == Qt.Key_End:
            self.after(1, self._scroll_last)

    def focus_cell(self, row, column):
        if self._closed:
            return False
        row, column = int(row), int(column)
        if row >= self.model.row_count:
            return False
        if row >= self._table_widget.rowCount():
            self._pending_focus = (row, column)
            self._extend_population_target()
            return False
        self._scroll_to_row(row)
        editor = self._activate_editor(row, column, focus=True)
        return editor is not None

    def show_page(self, row):
        """Compatibility alias: reveal a row in the full native table."""
        row = max(0, min(int(row), self.model.row_count - 1))
        if row >= self._table_widget.rowCount():
            self._pending_focus = (row, self.current_cell[1])
            return False
        return self._scroll_to_row(row)

    def move_cell(self, row, column):
        if self._closed:
            return
        row, column = int(row), int(column)
        self._read_inputs()
        if row >= self.model.row_count:
            self.model.ensure_size(row + 10)
            self.qt_model.synchronize_row_count()
            self._extend_population_target()
        self.focus_cell(row, column)

    def _sync_loaded_range(self, first, last):
        if self._closed:
            return
        self._commit_active_editor()
        first = max(0, int(first))
        last = min(int(last), self._table_widget.rowCount() - 1)
        for row in range(first, last + 1):
            self._ensure_native_row(row)

    def paste_text(self, text, position=None):
        if self._closed:
            return
        self._read_inputs()
        row, column = position if position is not None else self.current_cell
        try:
            pasted_rows = self.model.paste(text, row, column)
        except ValueError as exc:
            self.on_error(str(exc))
            return
        if not pasted_rows:
            return
        last_row = row + pasted_rows - 1
        self.model.ensure_size(last_row + 1 + self.PASTE_TRAILING_ROWS)
        # Update already-materialized affected rows immediately; any new rows
        # are appended in bounded event-loop batches.
        self._sync_loaded_range(row, last_row)
        self.qt_model.notify_cells_changed(row, last_row)
        self._extend_population_target()
        self._changed()
        self.after(1, self.focus_cell, row, column)

    def paste_clipboard(self):
        self.paste_text(self._clipboard.text())

    def copy_cell(self):
        if self._closed:
            return
        self._read_inputs()
        row, column = self.current_cell
        if 0 <= row < self.model.row_count and 0 <= column < 2:
            self._clipboard.setText(self.model.cell_text(row, column))

    def copy_table(self):
        """Compatibility alias for the row-selection copy workflow."""
        return self.copy_selected_rows()

    def add_rows(self):
        if self._closed:
            return
        self._read_inputs()
        self.model.ensure_size(self.model.row_count + 10)
        self.qt_model.synchronize_row_count()
        self._extend_population_target()
        self._changed()

    def clear_current_cell(self):
        if self._closed:
            return
        self._read_inputs()
        row, column = self.current_cell
        self.model.clear_cell(row, column)
        self._sync_loaded_range(row, row)
        self.qt_model.notify_cells_changed(row, row, column, column)
        self._changed()
        self.after(1, self.focus_cell, row, column)

    def clear_current_row(self):
        if self._closed:
            return
        self._read_inputs()
        row, column = self.current_cell
        self.model.clear_row(row)
        self._sync_loaded_range(row, row)
        self.qt_model.notify_cells_changed(row, row)
        self._changed()
        self.after(1, self.focus_cell, row, column)

    def clear_cells(self):
        if self._closed:
            return
        self._read_inputs()
        self.model.clear()
        self.qt_model.notify_cells_changed(0, self.model.row_count - 1)
        self._schedule_population_from(0)
        self._changed()
        self.after(1, self.focus_cell, 0, 0)

    def reset(self):
        self._read_inputs()
        self.clear_row_selection()
        self.model = ReferenceTableModel()
        self.qt_model.reset_worksheet(self.model)
        self.current_cell = (0, 0)
        self._pending_focus = (0, 0)
        self._schedule_population_from(0)

    def load_series(self, series):
        self._read_inputs()
        self.clear_row_selection()
        self.model.load_series(series)
        self.qt_model.reset_worksheet()
        self.current_cell = (0, 0)
        self._pending_focus = (0, 0)
        self._scroll_first()
        self._schedule_population_from(0)

    def refresh_visible_page(self):
        """Compatibility hook used after the dialog receives final geometry.

        Full population is already scheduled.  Unlike the old virtual-page
        implementation, this method performs no O(N) work and never blocks the
        first presented frame.
        """
        if self._closed:
            return False
        self._extend_population_target()
        return True

    def has_data(self):
        self._read_inputs()
        return self.model.has_data()

    def to_series(self, name):
        self._read_inputs()
        return self.model.to_series(name)

    def setVisible(self, visible):
        self._frame.setVisible(bool(visible))
        return self

    def isVisible(self):
        return self._frame.isVisible()

    def resize(self, width, height):
        self._frame.resize(width, height)
        return self

    def suspend(self):
        self._closed = True
        self._population_generation += 1
        self._population_scheduled = False

    def delete(self):
        if self._disposed:
            return
        self._closed = True
        self._disposed = True
        self._population_generation += 1
        self._population_scheduled = False
        try:
            self._commit_active_editor()
        except Exception:
            pass
        try:
            self._context_menu.delete()
        except Exception:
            pass
        qt_model = getattr(self, "qt_model", None)
        if qt_model is not None:
            try:
                qt_model.delete()
            except Exception:
                pass
        table_widget = getattr(self, "_table_widget", None)
        if table_widget is not None:
            try:
                table_widget.delete()
            except Exception:
                pass
            self._table_widget = None
        try:
            self._frame.delete()
        except Exception:
            pass
