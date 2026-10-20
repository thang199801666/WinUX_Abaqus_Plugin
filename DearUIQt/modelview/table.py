"""QTableView-like retained data-grid implementation."""
from __future__ import annotations

from typing import Any

from ..core.object import Signal, Qt
from ..core.item_model import QModelIndex
from ..widgets.menu import ImGuiMenu
from ..gui.palette import QtFusionMetrics
from .models import QtGridColumn, QtGridRow
from .themes import (
    _normalize_menu_spec, qt_item_row_theme, qt_item_text_theme, qt_item_view_theme,
)
from .base import _QtAbstractItemView

class ImGuiHeaderView:
    """Small QHeaderView-like facade over Dear ImGui table columns.

    Dear PyGui owns the native resize hit testing, while this facade keeps
    application code independent of table implementation details.  It exposes
    the commonly used QHeaderView properties and maps them to the table
    or individual column items.
    """

    Interactive = "interactive"
    Fixed = "fixed"
    Stretch = "stretch"

    def __init__(self, grid):
        self._grid = grid
        self._visible = True
        self._stretch_last = False
        self._sections_movable = False
        self._sections_clickable = True
        self._default_section_size = 100.0

    def isVisible(self):
        return bool(self._visible)

    def setVisible(self, visible):
        self._visible = bool(visible)
        self._grid.setHeaderVisible(self._visible)
        return self

    def setStretchLastSection(self, enabled):
        self._stretch_last = bool(enabled)
        columns = list(self._grid.columns)
        if columns:
            item = self._grid._column_item(columns[-1].key)
            if item is not None:
                try:
                    self._grid.backend.configure_item(
                        item,
                        width_fixed=not self._stretch_last,
                        width_stretch=self._stretch_last,
                        init_width_or_weight=(1.0 if self._stretch_last
                                              else self._default_section_size),
                    )
                except Exception:
                    pass
        return self

    def stretchLastSection(self):
        return bool(self._stretch_last)

    def setSectionsMovable(self, enabled):
        self._sections_movable = bool(enabled)
        try:
            self._grid.backend.configure_item(
                self._grid.tag, reorderable=self._sections_movable)
        except Exception:
            pass
        return self

    def sectionsMovable(self):
        return bool(self._sections_movable)

    def setSectionsClickable(self, enabled):
        self._sections_clickable = bool(enabled)
        try:
            self._grid.backend.configure_item(
                self._grid.tag, sortable=self._sections_clickable)
        except Exception:
            pass
        return self

    def sectionsClickable(self):
        return bool(self._sections_clickable)

    def setDefaultSectionSize(self, size):
        self._default_section_size = max(1.0, float(size))
        return self

    def defaultSectionSize(self):
        return float(self._default_section_size)

    def resizeSection(self, section, size):
        try:
            column = self._grid.columns[int(section)]
        except (IndexError, TypeError, ValueError):
            return False
        return self._grid.setColumnWidth(column.key, size)

    def sectionSize(self, section):
        try:
            column = self._grid.columns[int(section)]
        except (IndexError, TypeError, ValueError):
            return None
        return self._grid.columnWidth(column.key)

    def setSectionResizeMode(self, section, mode):
        try:
            column = self._grid.columns[int(section)]
        except (IndexError, TypeError, ValueError):
            return False
        item = self._grid._column_item(column.key)
        if item is None:
            return False
        mode = str(mode).lower()
        try:
            if mode == self.Stretch:
                self._grid.backend.configure_item(
                    item, width_fixed=False, width_stretch=True,
                    init_width_or_weight=max(.01, float(column.stretch or 1.0)))
            elif mode in (self.Fixed, self.Interactive):
                width = self._grid.columnWidth(column.key)
                if width is None:
                    width = column.width or self._default_section_size
                self._grid.backend.configure_item(
                    item, width_fixed=True, width_stretch=False,
                    init_width_or_weight=max(1.0, float(width)))
            else:
                return False
            return True
        except Exception:
            return False


QHeaderView = ImGuiHeaderView


class QtDataGridView(_QtAbstractItemView):
    """QTableView-like flat data grid with stable row keys."""

    def __init__(self, parent=None, columns=(), *, width=-1, height=-1, multiple=False,
                 after=None, backend=None, sortable=False, resizable=True,
                 reorderable=False, alternating_rows=True, grid_lines=True,
                 horizontal_scrollbar=True, on_activate=None):
        backend, parent_options = self._construction(parent, backend)
        normalized = []
        for index, column in enumerate(columns):
            if isinstance(column, QtGridColumn):
                normalized.append(column)
            elif isinstance(column, str):
                normalized.append(QtGridColumn(str(index), column))
            else:
                data = dict(column)
                normalized.append(QtGridColumn(
                    key=str(data.get("key", index)),
                    label=str(data.get("label", data.get("key", index))),
                    width=data.get("width"),
                    stretch=float(data.get("stretch", data.get("weight", 1.0))),
                    align=str(data.get("align", "left")),
                    sortable=bool(data.get("sortable", True)),
                ))
        self.columns = normalized
        self._model_columns_generated = not bool(normalized)
        self.rows: list[tuple[Any, tuple[Any, ...]]] = []
        self.row_data: dict[Any, Any] = {}
        self.row_backgrounds: dict[Any, Any] = {}
        self.row_enabled: dict[Any, bool] = {}
        self.items: dict[Any, Any] = {}
        self._cell_text_items: dict[Any, list[Any]] = {}
        self._row_tags: dict[Any, Any] = {}
        self._row_index: dict[Any, int] = {}
        self._row_visual_state: dict[Any, tuple[bool, bool, bool, bool]] = {}
        self._sort_key = None
        self._sort_ascending = True
        self._row_key_role = None
        self._model_row_by_key = {}
        self._cell_native_items = {}
        self.sortChanged = Signal()
        self.contextMenuRequested = Signal()
        self._external_activate = on_activate
        self._context_specs = []
        self._context_items = {}
        self._context_key = None
        self._context_open_callback = None
        self._context_trigger_callback = None
        self._context_handler_registry = None
        self._context_popup = None
        self._context_menu = None
        # Compatibility with draw-list item views serviced by a host view's
        # post-render layout loop. QTableView-backed grids do not need that
        # custom pass, but exposing the same tiny surface lets specialized
        # views migrate without branching the main render loop.
        self._resize_layout_pending = False
        self._scroller_arrow_overlay = None
        options = dict(
            **parent_options, header_row=True, width=width, height=height,
            scrollY=True, scrollX=bool(horizontal_scrollbar), freeze_rows=1,
            resizable=bool(resizable), reorderable=bool(reorderable),
            sortable=bool(sortable), row_background=bool(alternating_rows),
            borders_innerH=bool(grid_lines), borders_outerH=True,
            borders_innerV=bool(grid_lines), borders_outerV=True,
            policy=backend.mvTable_SizingStretchProp,
        )
        if sortable:
            options["callback"] = self._sort_specs_changed
        tag = backend.add_table(**options)
        super().__init__(tag, parent=parent, after=after, backend=backend, multiple=multiple)
        self.sortChanged.owner = self
        self.contextMenuRequested.owner = self
        self._horizontal_header = ImGuiHeaderView(self)
        self._horizontal_header._sections_movable = bool(reorderable)
        self._horizontal_header._sections_clickable = bool(sortable)
        for column in self.columns:
            self._add_native_column(column)
        try:
            backend.bind_item_theme(self.tag, qt_item_view_theme(backend))
        except Exception:
            pass
        if callable(on_activate):
            self.activated.connect(on_activate)

    def _model_index_for_key(self, key):
        model = self.model()
        if model is None:
            return super()._model_index_for_key(key)
        row = self._model_row_by_key.get(key, key)
        try:
            return model.index(int(row), 0)
        except (TypeError, ValueError):
            return super()._model_index_for_key(key)

    def setRowKeyRole(self, role):
        self._row_key_role = None if role is None else int(role)
        if self.model() is not None:
            self._model_changed()
        return self

    def rowKeyRole(self):
        return self._row_key_role

    def _selection_model_command(self):
        from ..core.item_model import QItemSelectionModel
        return QItemSelectionModel.Select | QItemSelectionModel.Rows

    def _add_native_column(self, column):
        kwargs = dict(parent=self.tag, label=column.label, user_data=column.key,
                      no_sort=not column.sortable)
        if column.width is not None:
            kwargs.update(width_fixed=True, init_width_or_weight=float(column.width))
        else:
            kwargs.update(width_stretch=True, init_width_or_weight=max(.01, column.stretch))
        return self.backend.add_table_column(**kwargs)

    def _rebuild_model_columns(self, model):
        count = int(model.columnCount())
        if self.columns and not self._model_columns_generated:
            return
        for item in list(self.backend.get_item_children(self.tag, 0) or []):
            try:
                self.backend.delete_item(item)
            except Exception:
                pass
        columns = []
        for column in range(count):
            label = model.headerData(column, Qt.Horizontal, Qt.DisplayRole)
            columns.append(QtGridColumn(str(column), str(label if label is not None else column)))
        self.columns = columns
        self._model_columns_generated = True
        for column in columns:
            self._add_native_column(column)

    def _model_changed(self, *_args):
        model = self.model()
        if model is None:
            return None
        # dataChanged(topLeft, bottomRight, roles) can update retained native
        # cell values in place.  Rebuilding every table row would destroy an
        # active persistent editor and unnecessarily reset native row identity.
        if (len(_args) >= 2 and isinstance(_args[0], QModelIndex)
                and isinstance(_args[1], QModelIndex)):
            self._refresh_model_data_range(_args[0], _args[1])
            return self
        if _args:
            self._clear_index_editors()
        self._rebuild_model_columns(model)
        rows = []
        self._model_row_by_key.clear()
        for row in range(int(model.rowCount())):
            values = []
            enabled = True
            background = None
            first_index = None
            key = row
            for column in range(min(int(model.columnCount()), len(self.columns))):
                index = model.index(row, column)
                if first_index is None:
                    first_index = index
                    enabled = bool(index.flags() & Qt.ItemIsEnabled)
                    background = index.data(Qt.BackgroundRole)
                    if self._row_key_role is not None:
                        candidate = index.data(self._row_key_role)
                        if candidate is not None:
                            key = candidate
                values.append(index.data(Qt.DisplayRole))
            self._model_row_by_key[key] = row
            rows.append(QtGridRow(key, tuple(values), data=first_index,
                                  enabled=enabled, background=background))
        self.set_rows(rows)
        return self

    def _model_key_for_row(self, row):
        model = self.model()
        if model is None:
            return row
        if self._row_key_role is not None:
            index = model.index(int(row), 0)
            if index.isValid():
                value = index.data(self._row_key_role)
                if value is not None:
                    return value
        return int(row)

    def _refresh_model_data_range(self, top_left, bottom_right):
        model = self.model()
        if model is None or not top_left.isValid() or not bottom_right.isValid():
            return False
        # A row-key role mutation changes view identity; use the safe full rebuild.
        for row in range(top_left.row(), bottom_right.row() + 1):
            key = self._model_key_for_row(row)
            if key not in self._row_index:
                self._model_changed()
                return True
            # The native row index is kept in sync by set_rows().  Look it up
            # directly instead of scanning the entire table twice for every
            # changed row (quadratic for large dataChanged ranges).
            position = self._row_index[key]
            values = list(self.rows[position][1])
            while len(values) < len(self.columns):
                values.append(None)
            cells = self._cell_native_items.get(key, ())
            for column in range(top_left.column(), bottom_right.column() + 1):
                if column >= model.columnCount():
                    continue
                index = model.index(row, column)
                value = index.data(Qt.DisplayRole)
                previous = values[column] if column < len(values) else None
                if column < len(values):
                    values[column] = value
                if self.isPersistentEditorOpen(index) or self.indexWidget(index) is not None:
                    continue
                native = cells[column] if 0 <= column < len(cells) else None
                if native is not None:
                    text = "" if value is None else str(value)
                    # Do not cross into the renderer for unchanged text.  Keep
                    # the previous None handling: initial materialization and
                    # incremental update format None differently in this view.
                    if previous is not None and str(previous) == text:
                        continue
                    try:
                        if column == 0:
                            # mvSelectable.value is a boolean selection flag;
                            # updating its display text must target label.
                            self.backend.configure_item(native, label=text)
                        else:
                            self.backend.set_value(native, text)
                    except Exception:
                        if column != 0:
                            try:
                                self.backend.configure_item(native, label=text)
                            except Exception:
                                pass
            self.rows[position] = (key, tuple(values))
        return True

    def indexAtRow(self, row, column=0):
        model = self.model()
        if model is None:
            return None
        return model.index(int(row), int(column))

    def _editor_parent_for_index(self, index):
        if index is None or not index.isValid():
            return self
        key = index.row()
        if self._row_key_role is not None:
            candidate = index.model().index(index.row(), 0).data(self._row_key_role)
            if candidate is not None:
                key = candidate
        row_tag = self._row_tags.get(key)
        return (row_tag, self.backend) if row_tag is not None else self

    def _native_item_for_index(self, index):
        if index is None or not index.isValid():
            return None
        key = index.row()
        if self._row_key_role is not None:
            candidate = index.model().index(index.row(), 0).data(self._row_key_role)
            if candidate is not None:
                key = candidate
        cells = self._cell_native_items.get(key, ())
        column = index.column()
        return cells[column] if 0 <= column < len(cells) else None

    def openPersistentEditor(self, index):
        editor = super().openPersistentEditor(index)
        if editor is not None:
            native = editor._layout_tag()
            target = self._native_item_for_index(index)
            if target is not None:
                try:
                    self.backend.move_item(native, before=target)
                except Exception:
                    pass
        return editor

    def edit(self, index):
        """Create an editor through the current delegate for one model index.

        Rendering the editor inline is backend-specific; callers that need a
        persistent cell widget can parent the returned editor to the view/row
        container and commit through :meth:`commitEditor`.
        """
        if index is None or not getattr(index, "isValid", lambda: False)():
            return None
        delegate = self.itemDelegate(index)
        editor = delegate.createEditor(self, None, index) if delegate is not None else None
        if editor is not None:
            delegate.setEditorData(editor, index)
        return editor

    def commitEditor(self, editor, index):
        delegate = self.itemDelegate(index)
        model = self.model()
        if delegate is None or model is None:
            return False
        committed = bool(delegate.setModelData(editor, model, index))
        if committed:
            delegate.commitData.emit(editor)
        return committed

    def horizontalHeader(self):
        return self._horizontal_header

    def _update_rows_in_place(self, normalized, previous, previous_enabled,
                              previous_backgrounds, *, prefix_count=None,
                              trim_suffix=False):
        """Retain native rows when an update preserves their order and shape.

        Job/ODB polling often provides a new Python list every cycle. Replacing
        identical table rows drops hover, scroll, editors and creates thousands
        of unnecessary native objects. Only DisplayRole text and row state are
        written here; structural changes still use the existing full rebuild.
        """
        native_count = len(self._row_tags)
        if prefix_count is None:
            if len(normalized) != native_count:
                return False
            existing_rows = normalized
        elif trim_suffix:
            # A shrinking suffix still has stable native IDs for every
            # surviving row.  Check that shape before deleting old rows.
            if prefix_count != native_count or not 0 < len(normalized) < native_count:
                return False
            existing_rows = normalized
        else:
            # Append-only refresh: validate the retained prefix BEFORE any
            # backend writes, then render only newly appended rows.
            if prefix_count != native_count or len(normalized) <= native_count:
                return False
            existing_rows = normalized[:native_count]
        for position, (key, values) in enumerate(existing_rows):
            if self._row_index.get(key) != position or key not in self.items:
                return False
            count = max(1, min(len(values), len(self.columns)))
            if len(self._cell_native_items.get(key, ())) != count:
                return False
        try:
            for position, (key, values) in enumerate(existing_rows):
                old_values = previous.get(key, ())
                cells = self._cell_native_items[key]
                for column, native in enumerate(cells):
                    # Renderer-owned display strings, never opaque UserRole
                    # objects (e.g. NumPy arrays), determine visual equality.
                    new_text = str(values[column]) if column < len(values) else ""
                    old_text = (str(old_values[column])
                                if column < len(old_values) else "")
                    if old_text == new_text:
                        continue
                    if column == 0:
                        # A selectable stores its label in configuration; its
                        # value is the selection boolean, NOT its displayed text.
                        self.backend.configure_item(native, label=new_text)
                    else:
                        self.backend.set_value(native, new_text)
                enabled = bool(self.row_enabled.get(key, True))
                if enabled != bool(previous_enabled.get(key, True)):
                    self.backend.configure_item(self.items[key], enabled=enabled)
                old_bg = previous_backgrounds.get(key)
                new_bg = self.row_backgrounds.get(key)
                if old_bg is not new_bg:
                    try:
                        same_bg = old_bg == new_bg
                        if not isinstance(same_bg, bool):
                            same_bg = False
                    except (TypeError, ValueError):
                        same_bg = False
                    if not same_bg:
                        if new_bg is None:
                            self.backend.unhighlight_table_row(self.tag, position)
                        else:
                            self.backend.highlight_table_row(self.tag, position, new_bg)
        except Exception:
            # Retry using the authoritative structural renderer. Partial native
            # updates are discarded by the rebuild below.
            return False
        return True

    def _append_native_rows(self, start=0):
        """Materialize only the table suffix while preserving prefix item IDs.

        Existing renderer rows own selection, focus and persistent editors; do
        not delete or recreate them for append-only streaming results.
        """
        for row_index in range(start, len(self.rows)):
            key, values = self.rows[row_index]
            row_tag = self.backend.add_table_row(parent=self.tag)
            self._row_tags[key] = row_tag
            self._row_index[key] = row_index
            selectable = self.backend.add_selectable(
                label=str(values[0]) if values else "",
                span_columns=True, height=QtFusionMetrics.ROW_HEIGHT,
                default_value=key in self.selected, user_data=key,
                enabled=bool(self.row_enabled.get(key, True)),
                callback=self._row_clicked, parent=row_tag,
            )
            self.items[key] = selectable
            text_items = [
                self.backend.add_text(str(value), parent=row_tag)
                for value in values[1:len(self.columns)]
            ]
            self._cell_text_items[key] = text_items
            self._cell_native_items[key] = [selectable] + text_items
            background = self.row_backgrounds.get(key)
            if background is not None:
                try:
                    self.backend.highlight_table_row(self.tag, row_index, background)
                except Exception:
                    pass

    def set_rows(self, rows):
        previous = {key: values for key, values in self.rows}
        previous_enabled = self.row_enabled
        previous_backgrounds = self.row_backgrounds
        old_selected = set(self.selected)
        normalized = []
        row_data = {}
        row_backgrounds = {}
        row_enabled = {}
        for row in rows:
            if isinstance(row, QtGridRow):
                key, values = row.key, tuple(row.values)
                row_data[key] = row.data
                row_enabled[key] = bool(row.enabled)
                if row.background is not None:
                    row_backgrounds[key] = row.background
            else:
                key, values = row
                values = tuple(values)
                row_enabled[key] = True
            normalized.append((key, values))
        self.rows = normalized
        self.row_data = row_data
        self.row_backgrounds = row_backgrounds
        self.row_enabled = row_enabled
        if self._sort_key is not None:
            self._apply_sort_in_place()
        self._state.replace(key for key, _values in self.rows)
        if self._update_rows_in_place(self.rows, previous, previous_enabled,
                                      previous_backgrounds):
            self._sync_selection_visuals()
            if old_selected != self.selected:
                self.selectionChanged.emit(set(self.selected))
            return self
        # Streaming tables frequently append a few new records to a stable
        # prefix. No existing row/editor needs to be destroyed in that case.
        # Sorting, reordering, duplicate keys and altered cell shape must
        # still take the authoritative rebuild path below.
        existing_count = len(self._row_tags)
        appended_keys = [key for key, _values in self.rows[existing_count:]]
        append_only = (
            self._sort_key is None and existing_count > 0 and
            len(self.rows) > existing_count and
            len(set(appended_keys)) == len(appended_keys) and
            all(key not in self._row_tags for key in appended_keys) and
            all(self._row_index.get(key) == i
                for i, (key, _values) in enumerate(self.rows[:existing_count]))
        )
        if append_only and self._update_rows_in_place(
                self.rows, previous, previous_enabled, previous_backgrounds,
                prefix_count=existing_count):
            try:
                self._append_native_rows(existing_count)
            except Exception:
                # The native backend may have failed midway through a suffix.
                # Rebuild all rows to discard partial native state.
                pass
            else:
                self._sync_selection_visuals()
                if old_selected != self.selected:
                    self.selectionChanged.emit(set(self.selected))
                return self
        # When the stream loses only its trailing rows, preserve native row
        # identities and renderer-owned scroll/hover state for the prefix.
        # Persistent editors or attached index widgets need full structural
        # handling; never remove their backing rows through this shortcut.
        previous_count = len(self._row_tags)
        tail_only = (
            self._sort_key is None and 0 < len(self.rows) < previous_count
            and not self._persistent_editors and not self._index_widgets
            and len(self._row_index) == previous_count
            and all(self._row_index.get(key) == i
                    for i, (key, _values) in enumerate(self.rows))
        )
        if tail_only and self._update_rows_in_place(
                self.rows, previous, previous_enabled, previous_backgrounds,
                prefix_count=previous_count, trim_suffix=True):
            try:
                removed_keys = [key for key in previous
                                if key not in self._row_index or
                                self._row_index[key] >= len(self.rows)]
                if len(removed_keys) != previous_count - len(self.rows):
                    raise RuntimeError("native table row keys changed")
                for key in reversed(removed_keys):
                    self.backend.delete_item(self._row_tags[key])
            except Exception:
                # Fall back to the authoritative renderer if removal failed.
                pass
            else:
                for key in removed_keys:
                    self.items.pop(key, None)
                    self._cell_text_items.pop(key, None)
                    self._cell_native_items.pop(key, None)
                    self._row_visual_state.pop(key, None)
                    self._row_tags.pop(key, None)
                    self._row_index.pop(key, None)
                self._sync_selection_visuals()
                if old_selected != self.selected:
                    self.selectionChanged.emit(set(self.selected))
                return self
        try:
            old_scroll_y = float(self.backend.get_y_scroll(self.tag))
        except Exception:
            old_scroll_y = 0.0
        try:
            old_scroll_x = float(self.backend.get_x_scroll(self.tag))
        except Exception:
            old_scroll_x = 0.0
        self._delete_rows()
        self._append_native_rows()
        self._sync_selection_visuals()
        # Preserve the user's viewport on a structural rebuild.
        try:
            self.backend.set_y_scroll(self.tag, old_scroll_y)
        except Exception:
            pass
        try:
            self.backend.set_x_scroll(self.tag, old_scroll_x)
        except Exception:
            pass
        if old_selected != self.selected:
            self.selectionChanged.emit(set(self.selected))
        return self

    setRows = set_rows

    def _delete_rows(self):
        for row in list(self.backend.get_item_children(self.tag, 1) or []):
            try:
                self.backend.delete_item(row)
            except Exception:
                pass
        self.items.clear()
        self._cell_text_items.clear()
        self._row_tags.clear()
        self._row_index.clear()
        self._row_visual_state.clear()
        self._cell_native_items.clear()

    def rowValues(self, key):
        # This index is maintained in visible/native row order, including after
        # sorting. Reading one row should not scan the full table.
        position = self._row_index.get(key)
        return self.rows[position][1] if position is not None else None

    def selectedRows(self):
        return [(key, values) for key, values in self.rows if key in self.selected]

    def rowData(self, key):
        return self.row_data.get(key)

    def setRowBackground(self, key, color):
        if key not in self._row_index:
            return False
        if color is None:
            self.row_backgrounds.pop(key, None)
            try:
                self.backend.unhighlight_table_row(self.tag, self._row_index[key])
            except Exception:
                pass
        else:
            self.row_backgrounds[key] = color
            try:
                self.backend.highlight_table_row(self.tag, self._row_index[key], color)
            except Exception:
                pass
        return True

    def setColumnWidth(self, key, width):
        column = self._column_item(key)
        if column is None:
            return False
        try:
            self.backend.configure_item(
                column, width_fixed=True, width_stretch=False,
                init_width_or_weight=max(1.0, float(width)))
            return True
        except Exception:
            return False

    def setColumnSortIndicator(self, key, ascending=True, *, default=True):
        """Configure the native sort indicator for one logical column."""
        column = self._column_item(key)
        if column is None:
            return False
        try:
            self.backend.configure_item(
                column,
                default_sort=bool(default),
                prefer_sort_ascending=bool(ascending),
                prefer_sort_descending=not bool(ascending),
            )
            return True
        except Exception:
            return False

    def setColumnSortable(self, key, sortable=True):
        """Enable or disable user sorting for one logical column."""
        column = self._column_item(key)
        if column is None:
            return False
        try:
            self.backend.configure_item(column, no_sort=not bool(sortable))
            return True
        except Exception:
            return False

    def columnWidth(self, key):
        column = self._column_item(key)
        if column is None:
            return None
        try:
            config = self.backend.get_item_configuration(column)
            value = config.get("init_width_or_weight")
            return None if value is None else float(value)
        except Exception:
            return None

    def _column_item(self, key):
        key = str(key)
        for item in list(self.backend.get_item_children(self.tag, 0) or []):
            try:
                if str(self.backend.get_item_user_data(item)) == key:
                    return item
            except Exception:
                pass
        return None

    def _layout_all(self):
        self._resize_layout_pending = False

    def resize(self, width=-1, height=-1):
        try:
            self.backend.configure_item(self.tag, width=width, height=height)
        except Exception:
            pass
        return self

    def setAlternatingRowColors(self, enabled):
        try:
            self.backend.configure_item(self.tag, row_background=bool(enabled))
        except Exception:
            pass
        return self

    def setShowGrid(self, enabled):
        enabled = bool(enabled)
        try:
            self.backend.configure_item(
                self.tag,
                borders_innerH=enabled,
                borders_innerV=enabled,
            )
        except Exception:
            pass
        return self

    def setHeaderVisible(self, visible):
        try:
            self.backend.configure_item(self.tag, header_row=bool(visible))
        except Exception:
            pass
        return self

    def setSortingEnabled(self, enabled):
        try:
            self.backend.configure_item(self.tag, sortable=bool(enabled))
        except Exception:
            pass
        return self

    def _apply_sort_in_place(self):
        if self._sort_key is None:
            return
        index = next((i for i, column in enumerate(self.columns)
                      if column.key == self._sort_key), None)
        if index is None:
            return
        def value(row):
            values = row[1]
            raw = values[index] if index < len(values) else ""
            if isinstance(raw, (int, float)):
                return (0, float(raw))
            text = str(raw).strip()
            try:
                return (0, float(text))
            except (TypeError, ValueError):
                return (1, text.casefold())
        self.rows.sort(key=value, reverse=not self._sort_ascending)

    def setContextMenu(self, items, *, on_open=None, on_trigger=None):
        """Attach the shared Dear ImGui ``ImGuiMenu`` to the grid."""
        self._context_specs = [_normalize_menu_spec(item) for item in (items or ())]
        self._context_open_callback = on_open
        self._context_trigger_callback = on_trigger
        self._delete_context_menu()
        if not self._context_specs:
            return self
        self._context_menu = ImGuiMenu(
            self._context_specs, backend=self.backend, after=self._after)
        self._context_menu.triggered.connect(self._context_triggered_from_menu)
        try:
            with self.backend.handler_registry() as registry:
                self.backend.add_mouse_click_handler(
                    button=self.backend.mvMouseButton_Right,
                    callback=self._context_mouse_down,
                )
            self._context_handler_registry = registry
        except Exception:
            self._context_handler_registry = None
        return self

    set_context_menu = setContextMenu

    def _context_mouse_down(self, *_args):
        point = None
        try:
            point = tuple(map(float, self.backend.get_mouse_pos(local=False)))
        except Exception:
            pass
        if point is None or not self._point_in_item(self.tag, point):
            return
        key = None
        for row_key, selectable in tuple(self.items.items()):
            if self._point_in_item(selectable, point):
                key = row_key
                break
        self._context_key = key
        if key is not None and key not in self.selected:
            self.setCurrentKey(key, select=True)
        if callable(self._context_open_callback):
            self._context_open_callback(key)
        self.contextMenuRequested.emit(key)
        if self._context_menu is not None:
            self._context_menu.popup(point, context=key)

    def _point_in_item(self, item, point):
        try:
            left, top = map(float, self.backend.get_item_rect_min(item))
            width, height = map(float, self.backend.get_item_rect_size(item))
            x, y = point
            return left <= x < left + width and top <= y < top + height
        except Exception:
            return False

    def _context_triggered_from_menu(self, action, context):
        self._context_key = context
        if callable(self._context_trigger_callback):
            self._context_trigger_callback(str(action), context)

    def setContextMenuItemEnabled(self, action, enabled):
        if self._context_menu is None:
            return False
        return self._context_menu.setActionEnabled(action, enabled)

    set_context_menu_item_enabled = setContextMenuItemEnabled

    def setContextMenuItemChecked(self, action, checked):
        if self._context_menu is None:
            return False
        return self._context_menu.setActionChecked(action, checked)

    set_context_menu_item_checked = setContextMenuItemChecked

    def _delete_context_menu(self):
        if self._context_handler_registry is not None:
            try:
                if self.backend.does_item_exist(self._context_handler_registry):
                    self.backend.delete_item(self._context_handler_registry)
            except Exception:
                pass
        self._context_handler_registry = None
        if self._context_menu is not None:
            try:
                self._context_menu.delete()
            except Exception:
                pass
        self._context_menu = None
        self._context_popup = None
        self._context_items.clear()

    def _sync_selection_visuals(self):
        visual_state = self._row_visual_state
        for key, item in tuple(self.items.items()):
            state = (key in self.selected, not bool(self.row_enabled.get(key, True)),
                     key == self.current, self._has_focus)
            if visual_state.get(key) == state:
                continue
            selected, disabled, current, active = state
            try:
                self.backend.set_value(item, selected)
                self.backend.bind_item_theme(
                    item, qt_item_row_theme(
                        self.backend,
                        selected=selected,
                        disabled=disabled,
                        current=current,
                        active=active,
                    ))
                cell_theme = qt_item_text_theme(
                    self.backend, selected=selected, disabled=disabled,
                    active=active)
                for text_item in self._cell_text_items.get(key, ()):
                    self.backend.bind_item_theme(text_item, cell_theme)
            except Exception:
                visual_state.pop(key, None)
            else:
                visual_state[key] = state

    def _focus_current(self):
        item = self.items.get(self.current)
        if item is not None:
            try:
                self.backend.focus_item(item)
            except Exception:
                pass

    def _sort_specs_changed(self, sender, app_data, user_data=None):
        specs = app_data or []
        if not specs:
            return
        # DPG currently reports [(column_id, direction), ...].  Resolve the
        # visible column index defensively because older builds use integer ids.
        spec = specs[0]
        try:
            column_id, direction = spec[0], spec[1]
        except Exception:
            return
        column_key = None
        children = list(self.backend.get_item_children(self.tag, 0) or [])
        if column_id in children:
            try:
                column_key = self.backend.get_item_user_data(column_id)
            except Exception:
                column_key = None
        if column_key is None and isinstance(column_id, int) and 0 <= column_id < len(self.columns):
            column_key = self.columns[column_id].key
        if column_key is None:
            return
        ascending = int(direction) >= 0
        self._sort_key, self._sort_ascending = column_key, ascending
        self._apply_sort_in_place()
        self.set_rows([
            QtGridRow(
                key=key,
                values=values,
                data=self.row_data.get(key),
                enabled=self.row_enabled.get(key, True),
                background=self.row_backgrounds.get(key),
            )
            for key, values in self.rows
        ])
        self.sortChanged.emit(column_key, ascending)

    def delete(self):
        # A virtual page may still be subscribed to selection and an external
        # QScrollBar. Tear both down before the native view/handlers disappear.
        controller = getattr(self, '_virtual_viewport_controller', None)
        if controller is not None:
            controller.detach()
        self._delete_context_menu()
        super().delete()



QHeaderView = ImGuiHeaderView
QTableView = QtDataGridView
ImGuiDataGridView = QtDataGridView

__all__ = ["ImGuiHeaderView", "QHeaderView", "QtDataGridView", "ImGuiDataGridView", "QTableView"]
