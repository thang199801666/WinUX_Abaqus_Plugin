"""QTableWidget convenience item view.

This is the item-based counterpart to :class:`QTableView`: it owns rows,
QTableWidgetItem values and optional cell widgets while keeping native table
construction inside DearUIQt rather than application forms.
"""
from __future__ import annotations

from ..core.object import QObject, Signal, Qt
from ..widgets.widget import QWidget
from ..gui.palette import QtFusionMetrics


class QTableWidgetItem:
    UserType = 1000

    # Large data grids may own hundreds of thousands of items.  Keeping an
    # instance ``__dict__`` plus a two-entry role dictionary for every cell is
    # disproportionately expensive, especially for worksheet/reference data
    # where DisplayRole/EditRole account for virtually every access.  Store the
    # two hot roles directly and allocate a sparse role dictionary only when an
    # uncommon role (tooltip/check state/etc.) is actually used.
    __slots__ = (
        "_type", "_display", "_edit", "_extra_data", "_flags",
        "_table", "_row", "_column",
    )

    def __init__(self, text="", item_type=0):
        self._type = int(item_type)
        value = str(text)
        self._display = value
        self._edit = value
        self._extra_data = None
        self._flags = Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled
        self._table = None
        self._row = -1
        self._column = -1

    def type(self): return self._type
    def tableWidget(self): return self._table
    def row(self): return self._row
    def column(self): return self._column
    def text(self): return str(self._display)
    def setText(self, text): self.setData(Qt.DisplayRole, str(text))
    def data(self, role):
        role = int(role)
        if role == Qt.DisplayRole:
            return self._display
        if role == Qt.EditRole:
            return self._edit
        return None if self._extra_data is None else self._extra_data.get(role)

    def setData(self, role, value):
        role = int(role)
        if role == Qt.DisplayRole:
            value = str(value)
            if self._display == value and self._edit == value:
                return
            self._display = value
            self._edit = value
        elif role == Qt.EditRole:
            display = "" if value is None else str(value)
            if self._edit == value and self._display == display:
                return
            self._display = display
            self._edit = value
        else:
            current = None if self._extra_data is None else self._extra_data.get(role)
            if current == value:
                return
            if self._extra_data is None:
                self._extra_data = {}
            self._extra_data[role] = value
        if self._table is not None:
            self._table._item_changed(self, role)
    def flags(self): return self._flags
    def setFlags(self, flags):
        flags = int(flags)
        if flags == self._flags:
            return
        self._flags = flags
        if self._table is not None:
            self._table._item_flags_changed(self)
    def checkState(self):
        value = None if self._extra_data is None else self._extra_data.get(Qt.CheckStateRole)
        return int(Qt.Unchecked if value is None else value)
    def setCheckState(self, state): self.setData(Qt.CheckStateRole, int(state))
    def toolTip(self):
        value = None if self._extra_data is None else self._extra_data.get(Qt.ToolTipRole)
        return str(value or "")
    def setToolTip(self, text): self.setData(Qt.ToolTipRole, str(text or ""))


class QTableWidget(QWidget):
    """Retained item table with optional QWidget cell editors."""

    StretchProportional = "stretch_proportional"
    StretchSame = "stretch_same"
    FixedFit = "fixed_fit"
    FixedSame = "fixed_same"

    @staticmethod
    def _resolve_sizing_policy(backend, policy):
        if policy is None:
            return getattr(backend, "mvTable_SizingStretchProp", 0)
        names = {
            QTableWidget.StretchProportional: "mvTable_SizingStretchProp",
            QTableWidget.StretchSame: "mvTable_SizingStretchSame",
            QTableWidget.FixedFit: "mvTable_SizingFixedFit",
            QTableWidget.FixedSame: "mvTable_SizingFixedSame",
        }
        name = names.get(policy)
        return getattr(backend, name, 0) if name else policy

    def __init__(self, rows=0, columns=0, parent=None, *, after=None, backend=None,
                 width=-1, height=-1, header_row=True, scroll_x=False,
                 scroll_y=True, resizable=True, row_background=True,
                 grid_lines=True, freeze_rows=1, freeze_columns=0,
                 sizing_policy=None, saved_settings=False, **native_options):
        backend, options = self._construction(parent, backend)
        sizing_policy = self._resolve_sizing_policy(backend, sizing_policy)
        table_options = dict(
            options, header_row=bool(header_row), width=width, height=height,
            scrollX=bool(scroll_x), scrollY=bool(scroll_y),
            freeze_rows=int(freeze_rows), freeze_columns=int(freeze_columns),
            resizable=bool(resizable), row_background=bool(row_background),
            borders_innerH=bool(grid_lines), borders_innerV=bool(grid_lines),
            borders_outerH=True, borders_outerV=True, policy=sizing_policy,
            no_saved_settings=not bool(saved_settings),
        )
        table_options.update(native_options)
        tag = backend.add_table(**table_options)
        super().__init__(tag, parent=parent, after=after, backend=backend)
        self.cellClicked = Signal(self)
        self.cellDoubleClicked = Signal(self)
        self.cellChanged = Signal(self)
        self.currentCellChanged = Signal(self)
        self.itemChanged = Signal(self)
        self._header_row_visible = bool(header_row)
        self._rows = 0
        self._columns = 0
        self._row_tags = []
        self._column_tags = []
        self._items = {}
        self._cell_widgets = {}
        self._cell_widget_keys = {}
        self._native_items = {}
        self._headers = []
        self._current = (-1, -1)
        self.setColumnCount(columns)
        self.setRowCount(rows)

    def rowCount(self): return self._rows
    def columnCount(self): return self._columns

    def rowAt(self, y):
        """Return the row under a *viewport-relative* Y coordinate, as in Qt.

        ``y=0`` starts just below the table header.  This is a bounded native
        geometry probe, not a scan of all retained rows, so its cost does not
        grow with the row count on ordinary fixed-height tables.
        """
        try:
            top = float(self.backend.get_item_rect_min(self.tag)[1])
        except Exception:
            return -1
        header = float(QtFusionMetrics.HEADER_HEIGHT) if self._header_row_visible else 0.0
        return self._row_at_screen_y(top + header + float(y), top, header)

    def rowAtGlobal(self, y):
        """Return the row under an absolute screen Y coordinate.

        Dear PyGui exposes global mouse coordinates, whereas Qt's ``rowAt``
        takes viewport-relative coordinates.  Keep that translation inside the
        reusable view rather than duplicating table hit testing in dialogs.
        """
        try:
            top = float(self.backend.get_item_rect_min(self.tag)[1])
        except Exception:
            return -1
        header = float(QtFusionMetrics.HEADER_HEIGHT) if self._header_row_visible else 0.0
        return self._row_at_screen_y(float(y), top, header)

    def _row_at_screen_y(self, y, table_top, header):
        if not self._rows or y < table_top + header:
            return -1
        backend = self.backend
        try:
            height = float(backend.get_item_rect_size(self.tag)[1])
            if height <= 0 or y >= table_top + height:
                return -1
            scroll = max(0.0, float(backend.get_y_scroll(self.tag)))
        except Exception:
            return -1

        row_height = max(1.0, float(QtFusionMetrics.ROW_HEIGHT))
        estimated = int((y - table_top - header + scroll) // row_height)
        estimated = max(0, min(self._rows - 1, estimated))

        # Fixed-height rows hit on the first probe.  For tables with small
        # variations in row height, expand nearby without re-probing previous
        # candidates.  Native geometry of off-screen rows may be undefined;
        # return -1 rather than selecting an unrelated row in that case.
        def contains(row):
            try:
                tag = self._row_tags[row]
                row_top = float(backend.get_item_rect_min(tag)[1])
                row_height_native = float(backend.get_item_rect_size(tag)[1])
                return row_height_native > 0 and row_top <= y < row_top + row_height_native
            except Exception:
                return False

        if contains(estimated):
            return estimated
        for distance in range(1, 33):
            lower = estimated - distance
            upper = estimated + distance
            if lower >= 0 and contains(lower):
                return lower
            if upper < self._rows and contains(upper):
                return upper
            if lower < 0 and upper >= self._rows:
                break
        return -1

    def setRowHidden(self, row, hidden):
        row = int(row)
        if not 0 <= row < self._rows:
            return False
        self.backend.configure_item(self._row_tags[row], show=not bool(hidden))
        return True

    def isRowHidden(self, row):
        row = int(row)
        if not 0 <= row < self._rows:
            return True
        return not bool(self.backend.get_item_configuration(self._row_tags[row]).get("show", True))

    def setColumnCount(self, count):
        count = max(0, int(count))
        while self._columns < count:
            column = self._columns
            tag = self.backend.add_table_column(
                parent=self.tag, label="", user_data=column, width_stretch=True,
                init_width_or_weight=1.0)
            self._column_tags.append(tag)
            self._headers.append("")
            self._columns += 1
        while self._columns > count:
            self.removeColumn(self._columns - 1)
        return self

    def setRowCount(self, count):
        count = max(0, int(count))
        while self._rows < count:
            self.insertRow(self._rows)
        while self._rows > count:
            self.removeRow(self._rows - 1)
        return self

    def insertRow(self, row):
        row = max(0, min(int(row), self._rows))
        old_rows = self._rows
        tag = self.backend.add_table_row(parent=self.tag)
        if row < old_rows:
            before = self._row_tags[row]
            try:
                self.backend.move_item(tag, before=before)
            except Exception:
                pass
        self._row_tags.insert(row, tag)
        self._rows += 1
        # Appending is the hot path for large, progressively populated tables.
        # Nothing after the insertion point can require reindexing when the new
        # row is appended at the tail, so avoid rebuilding every retained item
        # dictionary on every append (which otherwise turns N appends into O(N²)).
        if row < old_rows:
            self._reindex_after_row_change(row, +1)
            self._shift_current_for_row_insert(row)
        return row

    def removeRow(self, row):
        row = int(row)
        if not 0 <= row < self._rows:
            return False
        tail_remove = row == self._rows - 1

        # QTableWidget owns widgets installed with setCellWidget(). Dispose
        # them before the native table row is removed so QObject ownership and
        # renderer lifetime stay synchronized.
        # Tail removal dominates worksheet shrink operations.  Probe the
        # (row, column) keys directly instead of scanning every editor in the
        # entire table on every removed row (quadratic with row count).
        row_widgets = [self._cell_widgets[(row, column)]
                       for column in range(self._columns)
                       if (row, column) in self._cell_widgets]
        for widget in row_widgets:
            try:
                widget.delete()
            except Exception:
                pass

        tag = self._row_tags.pop(row)
        try:
            if self.backend.does_item_exist(tag):
                self.backend.delete_item(tag)
        except Exception:
            pass
        for column in range(self._columns):
            key = (row, column)
            item = self._items.pop(key, None)
            if item is not None:
                item._table, item._row, item._column = None, -1, -1
            self._native_items.pop(key, None)
            widget = self._cell_widgets.pop(key, None)
            if widget is not None:
                self._cell_widget_keys.pop(id(widget), None)

        self._rows -= 1
        if not tail_remove:
            self._cell_widgets = {((r - 1 if r > row else r), c): widget
                                  for (r, c), widget in self._cell_widgets.items()}
            self._reindex_cell_widget_keys()
            self._items = {((r - 1 if r > row else r), c): item
                           for (r, c), item in self._items.items()}
            self._native_items = {((r - 1 if r > row else r), c): native
                                  for (r, c), native in self._native_items.items()}
            for (r, c), item in self._items.items():
                item._row, item._column = r, c
            self._shift_current_for_row_remove(row)
        elif self._current[0] == row:
            self._set_current_after_structure_change(-1, -1)
        return True

    def _reindex_after_row_change(self, row, delta):
        if delta <= 0:
            return
        self._items = {((r + delta if r >= row else r), c): item
                       for (r, c), item in self._items.items()}
        self._cell_widgets = {((r + delta if r >= row else r), c): widget
                              for (r, c), widget in self._cell_widgets.items()}
        self._reindex_cell_widget_keys()
        self._native_items = {((r + delta if r >= row else r), c): tag
                              for (r, c), tag in self._native_items.items()}
        for (r, c), item in self._items.items():
            item._row, item._column = r, c

    def _set_current_after_structure_change(self, row, column):
        old_row, old_column = self._current
        current = (int(row), int(column))
        if current == (old_row, old_column):
            return
        self._current = current
        self.currentCellChanged.emit(current[0], current[1], old_row, old_column)

    def _shift_current_for_row_insert(self, row):
        current_row, current_column = self._current
        if current_row >= row and current_row >= 0:
            self._set_current_after_structure_change(current_row + 1, current_column)

    def _shift_current_for_row_remove(self, row):
        current_row, current_column = self._current
        if current_row < 0:
            return
        if current_row == row:
            self._set_current_after_structure_change(-1, -1)
        elif current_row > row:
            self._set_current_after_structure_change(current_row - 1, current_column)

    def removeColumn(self, column):
        """Remove one column and dispose the table-owned contents in it.

        Dear PyGui maps row children to table columns by order. Deleting the
        native column plus the removed cell roots shifts surviving later cells
        left, matching QTableWidget's structural semantics without rebuilding
        unaffected rows.
        """
        column = int(column)
        if not 0 <= column < self._columns:
            return False

        for key in [key for key in self._cell_widgets if key[1] == column]:
            widget = self._cell_widgets.pop(key)
            try:
                widget.delete()
            except Exception:
                pass

        for key in [key for key in self._items if key[1] == column]:
            item = self._items.pop(key)
            item._table, item._row, item._column = None, -1, -1
            native = self._native_items.pop(key, None)
            if native is not None:
                try:
                    if self.backend.does_item_exist(native):
                        self.backend.delete_item(native)
                except Exception:
                    pass

        tag = self._column_tags.pop(column)
        try:
            if self.backend.does_item_exist(tag):
                self.backend.delete_item(tag)
        except Exception:
            pass
        if column < len(self._headers):
            self._headers.pop(column)

        self._cell_widgets = {
            (r, c - 1 if c > column else c): widget
            for (r, c), widget in self._cell_widgets.items()
        }
        self._reindex_cell_widget_keys()
        self._items = {
            (r, c - 1 if c > column else c): item
            for (r, c), item in self._items.items()
        }
        self._native_items = {
            (r, c - 1 if c > column else c): native
            for (r, c), native in self._native_items.items()
        }
        self._columns -= 1
        for (r, c), item in self._items.items():
            item._row, item._column = r, c
        for index, column_tag in enumerate(self._column_tags):
            try:
                self.backend.configure_item(column_tag, user_data=index)
            except Exception:
                pass

        current_row, current_column = self._current
        if current_column == column:
            self._set_current_after_structure_change(-1, -1)
        elif current_column > column:
            self._set_current_after_structure_change(current_row, current_column - 1)
        return True

    def nativeRow(self, row):
        row = int(row)
        return self._row_tags[row] if 0 <= row < self._rows else None

    def nativeColumn(self, column):
        column = int(column)
        return self._column_tags[column] if 0 <= column < self._columns else None

    def nativeItem(self, row, column):
        return self._native_items.get((int(row), int(column)))

    def setSortingEnabled(self, enabled):
        try:
            self.backend.configure_item(self.tag, sortable=bool(enabled))
        except Exception:
            pass
        return self

    def setColumnSortIndicator(self, column, ascending=True, *, default=True):
        """Configure one column's native sort direction without leaking renderer flags."""
        column = int(column)
        if not 0 <= column < self._columns:
            return False
        try:
            self.backend.configure_item(
                self._column_tags[column],
                default_sort=bool(default),
                prefer_sort_ascending=bool(ascending),
                prefer_sort_descending=not bool(ascending),
            )
            return True
        except Exception:
            return False

    def setColumnSortable(self, column, sortable=True):
        """Enable or disable sorting for one item-table column."""
        column = int(column)
        if not 0 <= column < self._columns:
            return False
        try:
            self.backend.configure_item(
                self._column_tags[column], no_sort=not bool(sortable))
            return True
        except Exception:
            return False

    def setHorizontalHeaderLabels(self, labels):
        labels = [str(label) for label in labels]
        if len(labels) > self._columns:
            self.setColumnCount(len(labels))
        normalized = labels[:self._columns] + [""] * max(0, self._columns - len(labels))
        self._headers = normalized
        for column, label in enumerate(normalized):
            try:
                self.backend.configure_item(self._column_tags[column], label=label)
            except Exception:
                pass
        return self

    def setColumnWidth(self, column, width):
        column = int(column)
        if not 0 <= column < self._columns:
            return False
        self.backend.configure_item(self._column_tags[column], width_fixed=True,
                                    width_stretch=False,
                                    init_width_or_weight=max(1.0, float(width)))
        return True

    def setColumnResizable(self, column, resizable=True):
        column = int(column)
        if not 0 <= column < self._columns:
            return False
        self.backend.configure_item(self._column_tags[column], no_resize=not bool(resizable))
        return True

    def setColumnStretch(self, column, stretch=1.0):
        column = int(column)
        if not 0 <= column < self._columns:
            return False
        self.backend.configure_item(self._column_tags[column], width_fixed=False,
                                    width_stretch=True,
                                    init_width_or_weight=max(.01, float(stretch)))
        return True

    def item(self, row, column):
        return self._items.get((int(row), int(column)))

    def setItem(self, row, column, item):
        row, column = int(row), int(column)
        if not (0 <= row < self._rows and 0 <= column < self._columns):
            raise IndexError("QTableWidget cell out of range")
        if not isinstance(item, QTableWidgetItem):
            raise TypeError("item must be QTableWidgetItem")
        old = self._items.get((row, column))
        if old is not None and old is not item:
            old._table, old._row, old._column = None, -1, -1
        item._table, item._row, item._column = self, row, column
        self._items[(row, column)] = item
        self._render_item(item)
        return item

    def takeItem(self, row, column):
        key = (int(row), int(column))
        item = self._items.pop(key, None)
        native = self._native_items.pop(key, None)
        if native is not None:
            try: self.backend.delete_item(native)
            except Exception: pass
        if item is not None:
            item._table, item._row, item._column = None, -1, -1
        return item

    def _render_item(self, item):
        key = (item._row, item._column)
        # A cell widget owns the visual slot while installed. Keep the logical
        # QTableWidgetItem retained but do not create a competing native child.
        if key in self._cell_widgets:
            return
        native = self._native_items.get(key)
        text = item.text()
        if native is None:
            native = self.backend.add_text(text, parent=self._row_tags[item._row])
            self._native_items[key] = native
            # Dear PyGui assigns table columns by child order. When an item is
            # restored after a transient cell editor closes, append-at-end would
            # move that item to the wrong column. Place it before the next
            # rendered cell (item or widget) when one exists.
            before = None
            for next_column in range(item._column + 1, self._columns):
                widget = self._cell_widgets.get((item._row, next_column))
                if widget is not None and not getattr(widget, "_deleted", False):
                    before = widget._layout_tag()
                    break
                before = self._native_items.get((item._row, next_column))
                if before is not None:
                    break
            if before is not None:
                try:
                    self.backend.move_item(native, before=before)
                except Exception:
                    pass
            # Native text items are enabled by default.  Avoid one extra
            # configure_item() crossing for the overwhelmingly common case;
            # on a 100k x 3 worksheet this removes 300k renderer calls from
            # initial materialization.  Disabled items still receive an
            # explicit state write.
            if not bool(item.flags() & Qt.ItemIsEnabled):
                try:
                    self.backend.configure_item(native, enabled=False)
                except Exception:
                    pass
        else:
            try: self.backend.set_value(native, text)
            except Exception: self.backend.configure_item(native, label=text)

    def _item_changed(self, item, role):
        if role in (Qt.DisplayRole, Qt.EditRole):
            self._render_item(item)
        self.itemChanged.emit(item)
        self.cellChanged.emit(item.row(), item.column())

    def _item_flags_changed(self, item):
        if item.tableWidget() is not self:
            return
        native = self._native_items.get((item._row, item._column))
        if native is None:
            self._render_item(item)
            return
        try:
            self.backend.configure_item(
                native, enabled=bool(item.flags() & Qt.ItemIsEnabled))
        except Exception:
            pass

    def setCellWidget(self, row, column, widget):
        row, column = int(row), int(column)
        if not (0 <= row < self._rows and 0 <= column < self._columns):
            raise IndexError("QTableWidget cell out of range")
        if not isinstance(widget, QWidget):
            raise TypeError("cell widget must be QWidget")
        key = (row, column)
        previous_key = self._cell_widget_keys.get(id(widget))
        if previous_key is not None and previous_key != key:
            self._cell_widgets.pop(previous_key, None)
            previous_item = self._items.get(previous_key)
            if previous_item is not None and previous_key not in self._native_items:
                self._render_item(previous_item)
        previous = self._cell_widgets.get(key)
        if previous is not None and previous is not widget:
            self._cell_widget_keys.pop(id(previous), None)
            try:
                previous.delete()
            except Exception:
                pass

        # Qt allows a logical QTableWidgetItem and a cell widget to coexist,
        # with the cell widget replacing the item's visual representation. DPG
        # assigns table columns by native child order, so keeping both native
        # children would shift every following cell one column to the right.
        # Remove only the item's native renderer while the widget is installed;
        # the QTableWidgetItem object remains retained and is restored when the
        # widget is removed.
        item_native = self._native_items.pop(key, None)
        if item_native is not None:
            try:
                if self.backend.does_item_exist(item_native):
                    self.backend.delete_item(item_native)
            except Exception:
                pass

        native = widget._layout_tag()
        try:
            row_children = list(self.backend.get_item_children(self._row_tags[row], 1) or [])
        except Exception:
            row_children = []
        # Insert before the next cell's renderer when possible so the widget
        # occupies the exact table column rather than being appended at the end.
        before = None
        for next_column in range(column + 1, self._columns):
            before = self._native_items.get((row, next_column))
            if before is not None:
                break
        try:
            if before is not None:
                self.backend.move_item(native, parent=self._row_tags[row], before=before)
            else:
                self.backend.move_item(native, parent=self._row_tags[row])
        except Exception:
            try:
                self.backend.move_item(native, parent=self._row_tags[row])
            except Exception:
                pass
        # QTableWidget owns installed cell widgets. Keep QObject ownership on
        # the table even though the renderer item itself must live below the
        # native table-row container. This mirrors Qt and guarantees dialog/row
        # teardown disposes wrapper state as well as native descendants.
        if widget.parent is not self:
            widget.setParent(self)
        self._cell_widgets[key] = widget
        self._cell_widget_keys[id(widget)] = key
        return widget

    def _reindex_cell_widget_keys(self):
        self._cell_widget_keys = {id(widget): key for key, widget in self._cell_widgets.items()}

    def cellWidget(self, row, column):
        return self._cell_widgets.get((int(row), int(column)))

    def removeCellWidget(self, row, column):
        # Match Qt: transfer/removal does not implicitly destroy the widget.
        # Restore the retained item's native renderer after the widget has been
        # removed from the cell. Callers that intend to reuse the widget should
        # reparent/move it after this call; deleted widgets are safe here too.
        key = (int(row), int(column))
        widget = self._cell_widgets.pop(key, None)
        if widget is not None:
            self._cell_widget_keys.pop(id(widget), None)
        item = self._items.get(key)
        if item is not None and key not in self._native_items:
            self._render_item(item)
        return widget

    def clearContents(self):
        # Dense worksheets can contain hundreds of thousands of cells.  Do not
        # first allocate a second list containing every (row, column) key just
        # to empty the dictionaries; pop in-place and release native renderers
        # as we go.
        while self._items:
            key, item = self._items.popitem()
            native = self._native_items.pop(key, None)
            if native is not None:
                try:
                    self.backend.delete_item(native)
                except Exception:
                    pass
            item._table, item._row, item._column = None, -1, -1
        for widget in tuple(dict.fromkeys(self._cell_widgets.values())):
            try:
                widget.delete()
            except Exception:
                pass
        self._cell_widgets.clear()
        self._cell_widget_keys.clear()
        return self

    def clear(self):
        """Clear items/cell widgets and reset header labels, retaining shape."""
        self.clearContents()
        self.setHorizontalHeaderLabels([""] * self._columns)
        return self

    def currentRow(self): return self._current[0]
    def currentColumn(self): return self._current[1]
    def setCurrentCell(self, row, column):
        row, column = int(row), int(column)
        current = (row, column) if (0 <= row < self._rows and 0 <= column < self._columns) else (-1, -1)
        self._set_current_after_structure_change(*current)
        return self

    def delete(self):
        if self._deleted:
            return
        # Detach logical items before QObject/native teardown without copying a
        # potentially enormous values view into a temporary tuple.  The item
        # dictionary itself remains stable until the final cleanup block.
        for item in self._items.values():
            item._table, item._row, item._column = None, -1, -1
        try:
            super().delete()
        finally:
            if self._deleted:
                self._items.clear()
                self._cell_widgets.clear()
                self._cell_widget_keys.clear()
                self._native_items.clear()
                self._row_tags.clear()
                self._column_tags.clear()
                self._headers.clear()
                self._rows = 0
                self._columns = 0
                self._current = (-1, -1)


__all__ = ["QTableWidget", "QTableWidgetItem"]
