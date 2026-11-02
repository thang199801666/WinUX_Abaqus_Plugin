"""Opt-in Excel-style interaction for QTableWidget and QtDataGridView."""
from __future__ import annotations

import threading
from time import monotonic
from ..core import QObject, Signal, Qt, QGlobalInputBinding
from ..gui import QClipboard, QCursor, QKeyboard, QtFusionPalette
from ..input_gate import popup_input_active
from ..widgets import QLineEdit, QMenu
from .spreadsheet import CellRange, SpreadsheetAdapter, SpreadsheetController
from .table_widget import QTableWidget, QTableWidgetItem


class SpreadsheetBehavior(QObject):
    """Attach to a table; keep its renderer, model and row keys intact.

    Item-owned QTableWidget values are editable by default. Data-grid views
    are read-only unless the caller supplies an atomic ``write`` callback.
    ``first_column`` excludes a row-number/gutter column from clipboard data.
    """
    def __init__(self, view, *, adapter=None, first_column=0, read_only=None,
                 write=None, editable=None, on_error=None, after=None):
        super().__init__(parent=view, after=after)
        self.view, self.backend, self.tag = view, view.backend, view.tag
        self.first_column = max(0, int(first_column))
        self.on_error = on_error or (lambda _message: None)
        self._item_table = isinstance(view, QTableWidget)
        self._keyboard_owned = False
        self._pressed = None
        self._dragging = False
        self._drag_pending = None
        self._drag_scheduled = False
        self._drag_generation = 0
        self.selectionFinished = Signal(self)
        self._painted = set()
        self._applied_selection = None
        self._editor = self._edit_position = None
        self._last_click = None
        self._rows = 0  # Geometry protocol used by QTableWidget's bounded row probe.
        if adapter is None:
            if write is None and self._item_table and read_only is not True:
                write = self._write_items
            if read_only:
                write = None
            adapter = SpreadsheetAdapter(self._shape, self._read, write=write,
                                          editable=editable or self._editable_item)
        self.controller = SpreadsheetController(adapter, QClipboard(backend=self.backend))
        self.binding = QGlobalInputBinding(parent=self, backend=self.backend)
        for key in (Qt.Key_C, Qt.Key_V, Qt.Key_X, Qt.Key_A, Qt.Key_Delete,
                    Qt.Key_Backspace, Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down,
                    Qt.Key_Tab, Qt.Key_Return, Qt.Key_Enter, Qt.Key_F2, Qt.Key_Escape,
                    Qt.Key_Home, Qt.Key_End):
            self.binding.onKeyPress(key, self._key, user_data=key)
        self.binding.onMouseClick(Qt.LeftButton, self._press)
        self.binding.onMouseRelease(Qt.LeftButton, self._release)
        self.binding.onMouseDrag(Qt.LeftButton, self._drag, threshold=4)
        self.binding.onMouseRelease(Qt.RightButton, self._context)
        self.binding.activate()
        self.menu = QMenu([
            {'action': 'copy', 'label': 'Copy', 'shortcut': 'Ctrl+C'},
            {'action': 'cut', 'label': 'Cut', 'shortcut': 'Ctrl+X'},
            {'action': 'paste', 'label': 'Paste', 'shortcut': 'Ctrl+V'},
            {'action': 'clear', 'label': 'Clear cells', 'shortcut': 'Delete'},
            {'action': 'all', 'label': 'Select all', 'shortcut': 'Ctrl+A'},
        ], parent=self, backend=self.backend, after=self._after)
        self.menu.triggered.connect(lambda action, *_: self._defer(self.command, action))

    def _defer(self, callback, *args):
        def deliver(*_ignored):
            if not self._deleted and self.backend.does_item_exist(self.tag):
                try:
                    callback(*args)
                except (ValueError, IndexError, RuntimeError) as exc:
                    self.on_error(str(exc))
        if callable(self._after):
            self._after(1, deliver)
        else:
            from ..runtime import QGuiRuntime
            QGuiRuntime(self.backend).invokeNextFrame(deliver)

    def _shape(self):
        return ((self.view.rowCount(), max(0, self.view.columnCount() - self.first_column))
                if self._item_table else
                (len(self.view.rows), max(0, len(self.view.columns) - self.first_column)))

    def columnCount(self):
        return self._shape()[1] + self.first_column

    def nativeItem(self, row, column):
        if self._item_table:
            return self.view.nativeItem(row, column)
        if not 0 <= row < len(self.view.rows):
            return None
        cells = self.view._cell_native_items.get(self.view.rows[row][0], ())
        return cells[column] if column < len(cells) else None

    def _read(self, row, column):
        column += self.first_column
        if self._item_table:
            item = self.view.item(row, column)
            return item.text() if item is not None else ''
        values = self.view.rows[row][1]
        return values[column] if column < len(values) else ''

    def _editable_item(self, row, column):
        if not self._item_table:
            return True  # Custom data-grid writers own their validation.
        item = self.view.item(row, column + self.first_column)
        return item is None or bool(item.flags() & Qt.ItemIsEditable) and bool(item.flags() & Qt.ItemIsEnabled)

    def _write_items(self, changes):
        previous = {(r, c): self._read(r, c) for r, c in changes}
        missing = {(r, c) for r, c in changes if self.view.item(r, c + self.first_column) is None}
        blocked = self.view.blockSignals(True)
        try:
            for (row, col), value in changes.items():
                item = self.view.item(row, col + self.first_column)
                if item is None:
                    self.view.setItem(row, col + self.first_column, QTableWidgetItem(value))
                else:
                    item.setText(value)
        except Exception:
            for (row, col), value in previous.items():
                if (row, col) in missing:
                    self.view.takeItem(row, col + self.first_column)
                else:
                    self.view.item(row, col + self.first_column).setText(value)
            raise
        finally:
            self.view.blockSignals(blocked)
        for row, col in changes:
            item = self.view.item(row, col + self.first_column)
            self.view.itemChanged.emit(item)
            self.view.cellChanged.emit(row, col + self.first_column)

    @property
    def selected_range(self):
        return self.controller.selection.selected_range

    def select_range(self, anchor, extent=None, *, focus=True):
        self.commit_editor()
        region = self.controller.select(anchor, extent)
        selection = (self.controller.selection.anchor, self.controller.selection.current)
        keys = (None if self._item_table else
                {self.view.rows[row][0] for row in range(region.top, region.bottom + 1)})
        changed = self._applied_selection != selection or (
            keys is not None and (keys != self.view.selected or
                                  self.view.current != self.view.rows[selection[1][0]][0]))
        if not changed:
            if focus:
                self._keyboard_owned = True
                self.view.setFocus()
            return region
        self._paint_selection()
        if self._item_table:
            row, col = self.controller.selection.current
            self.view.setCurrentCell(row, col + self.first_column)
        else:
            if keys != self.view.selected:
                self.view.selected = keys
                self.view.selectionChanged.emit(keys)
            self.view.setCurrentKey(self.view.rows[self.controller.selection.current[0]][0],
                                    select=False, focus=False)
        self._applied_selection = selection
        if focus:
            self._keyboard_owned = True
            self.view.setFocus()
        return region

    def _paint_selection(self, *, force=False):
        region = self.selected_range
        cells = set(region.cells()) if region is not None else set()
        for row, col in self._painted - cells:
            try:
                self.backend.unhighlight_table_cell(self.tag, row, col + self.first_column)
            except (RuntimeError, SystemError):
                pass
        for row, col in (cells if force else cells - self._painted):
            try:
                self.backend.highlight_table_cell(self.tag, row, col + self.first_column, QtFusionPalette.SELECTION_ACTIVE)
            except (RuntimeError, SystemError):
                pass
        self._painted = cells

    def reset_selection(self):
        self._cancel_pending_drag()
        self._dragging = False
        self._applied_selection = None
        self.cancel_editor()
        self.controller.selection.clear()
        self._paint_selection()
        self._pressed = None

    def command(self, action):
        try:
            self.commit_editor()
            if action == 'all':
                region = self.controller.select_all()
                if region is not None:
                    self.select_range((region.top, region.left), (region.bottom, region.right))
            else:
                result = {'copy': self.controller.copy, 'cut': self.controller.cut,
                          'paste': self.controller.paste, 'clear': self.controller.clear}[action]()
                if action in ('copy', 'cut') and not result:
                    self.on_error('Clipboard is busy or no cells are selected.')
                if action == 'paste' and result is not None:
                    self.select_range((result.top, result.left), (result.bottom, result.right))
                self._paint_selection()
        except (ValueError, IndexError, RuntimeError) as exc:
            self.on_error(str(exc))

    def _hit(self):
        if not self._input_available():
            return None
        point = QCursor.pos(backend=self.backend)
        x, y = point.x(), point.y()
        self._rows = self._shape()[0]
        row = (self.view.rowAtGlobal(y) if self._item_table
               else QTableWidget._painted_row_at_global(self, y))
        if row < 0:
            return None
        starts = []
        for column in range(self.columnCount()):
            item = self.nativeItem(row, column)
            if item is None and self._edit_position == (row, column - self.first_column):
                item = getattr(self._editor, 'tag', None)
            if item is None:
                return None
            starts.append(float(self.backend.get_item_rect_min(item)[0]))
        left = starts[0] - 6
        try:
            right = left + float(self.backend.get_item_rect_size(self.tag)[0])
        except (KeyError, RuntimeError):
            # Native tables can omit their own rect_min/rect_size entirely.
            # The enclosing scroll viewport still supplies a safe clip edge.
            from ..backends.dearpygui_scroller import dpg_window_rect
            parent, bounds = self.backend.get_item_parent(self.tag), None
            while parent and bounds is None:
                bounds = dpg_window_rect(self.backend, parent, clip=True)
                parent = self.backend.get_item_parent(parent)
            if bounds is None:
                return None
            right = bounds[2] - 4
        if x < left or x >= right:
            return None
        native_col = max(index for index, start in enumerate(starts) if x >= start - 6)
        return row, native_col - self.first_column

    def _press(self, *_args):
        self._cancel_pending_drag()
        self._dragging = False
        cell = self._hit()
        self._keyboard_owned = cell is not None
        self._pressed = cell
        if cell is None and self._editor is not None and not popup_input_active():
            self._defer(self.commit_editor)

    def _release(self, *_args):
        start, self._pressed = self._pressed, None
        if start is None:
            return
        end = self._hit()
        self._cancel_pending_drag()
        if end is None:
            self._dragging = False
            self.selectionFinished.emit(self.selected_range)
            return
        shift = QKeyboard.isShiftDown(backend=self.backend)
        rows, columns = self._shape()
        if not columns:
            self._dragging = False
            return
        if start[1] < 0:
            anchor = (start[0], 0)
            extent = (end[0], columns - 1)
        else:
            extent = (end[0], max(0, end[1]))
            anchor = self.controller.selection.anchor if shift and self.controller.selection.anchor is not None else start
        previous, now = self._last_click, monotonic()
        self._last_click = (end, now)
        self._defer(self._finish_pointer_selection, anchor, extent, self._drag_generation)
        if start[1] >= 0 and start == end and previous and previous[0] == end and now - previous[1] < .35:
            self._defer(self.begin_edit)
            self._last_click = None

    def _drag(self, *_args):
        if self._pressed is None or self._pressed[1] < 0:
            return
        end = self._hit()
        if end is not None and end[1] >= 0:
            target = (self._pressed, end)
            if target == self._drag_pending:
                return
            if self._drag_pending is None and target == (
                    self.controller.selection.anchor, self.controller.selection.current):
                return
            self._dragging = True
            self._drag_pending = target
            if not self._drag_scheduled:
                self._drag_scheduled = True
                self._defer(self._flush_drag_selection, self._drag_generation)

    def isDragging(self):
        return self._dragging

    def _cancel_pending_drag(self):
        self._drag_generation += 1
        self._drag_pending = None
        self._drag_scheduled = False

    def _flush_drag_selection(self, generation):
        if generation != self._drag_generation:
            return
        self._drag_scheduled = False
        target, self._drag_pending = self._drag_pending, None
        if target is not None and self._pressed is not None:
            # Extending a pointer range must not scroll native keyboard focus
            # into view or trigger editor/canvas relayout on every drag frame.
            self.select_range(*target, focus=False)

    def _finish_pointer_selection(self, anchor, extent, generation):
        if generation != self._drag_generation:
            return
        try:
            self.select_range(anchor, extent)
        finally:
            self._dragging = False
        self.selectionFinished.emit(self.selected_range)

    def _context(self, *_args):
        cell = self._hit()
        if cell is None:
            return
        point = QCursor.pos(backend=self.backend)
        self._defer(self._show_context, cell, (point.x(), point.y()))

    def _show_context(self, cell, position):
        row, col = cell
        cell = row, max(0, col)
        if self.selected_range is None or not self.selected_range.contains(cell):
            self.select_range(cell)
        for action in ('cut', 'paste', 'clear'):
            self.menu.setActionEnabled(action, not self.controller.adapter.read_only)
        self.menu.popup(position)

    def owns_keyboard(self):
        if not self._input_available():
            return False
        focused = self.backend.get_focused_item()
        if focused:
            kind = self.backend.get_item_info(focused).get('type', '')
            if (any(name in kind for name in ('Input', 'Combo', 'Slider', 'Drag'))
                    and focused != getattr(self._editor, 'tag', None)):
                return False
            while focused:
                if focused == self.tag:
                    return True
                focused = self.backend.get_item_parent(focused)
            return False
        return self._keyboard_owned

    def _input_available(self):
        # DearPyGui normally routes WinUx input through manual callback
        # management on the renderer/GUI thread.  Treat a callback delivered by
        # an older/default DPG worker as unavailable instead of querying HWNDs
        # or widget geometry from the wrong thread.  The next correctly routed
        # input event remains fully interactive.
        if threading.get_ident() != self.threadId():
            return False
        from ..input_gate import popup_input_is_blocked
        from ..core.application import QApplication
        if self._deleted or not self.view.isVisible() or not self.view.isEnabled() or popup_input_is_blocked(self):
            return False
        ancestors, item = [], self.tag
        while item:
            if not self.backend.does_item_exist(item) or not self.backend.is_item_shown(item):
                return False
            ancestors.append(item)
            item = self.backend.get_item_parent(item)
        app = QApplication.instance()
        modal = app.activeModalWidget() if app is not None else None
        if modal is not None and getattr(modal, 'tag', None) not in ancestors:
            return False
        # DPG global registries also fire for sibling native tool windows.
        import os
        if os.name == 'nt' and getattr(self.backend, '__name__', '') == 'dearpygui.dearpygui':
            import ctypes
            from ctypes import wintypes
            from ..backends.native_windows import NativeWindowBackend
            hwnd = NativeWindowBackend(self.backend).winId(ancestors[-1])
            ctypes.windll.user32.GetForegroundWindow.restype = wintypes.HWND
            if hwnd and int(ctypes.windll.user32.GetForegroundWindow() or 0) != int(hwnd):
                return False
        return True

    def _key(self, _sender=None, _data=None, user_data=None):
        if not self.owns_keyboard():
            return
        key = user_data
        ctrl = QKeyboard.isControlDown(backend=self.backend)
        shift = QKeyboard.isShiftDown(backend=self.backend)
        if self._editor is not None:
            if key == Qt.Key_Escape:
                self._defer(self.cancel_editor)
            elif key not in (Qt.Key_Tab, Qt.Key_Return, Qt.Key_Enter):
                return  # Text selection/copy/paste belongs to the native editor.
        if ctrl and key in (Qt.Key_C, Qt.Key_X, Qt.Key_V, Qt.Key_A):
            self._defer(self.command, {Qt.Key_C: 'copy', Qt.Key_X: 'cut', Qt.Key_V: 'paste', Qt.Key_A: 'all'}[key])
        elif key in (Qt.Key_Delete, Qt.Key_Backspace) and not self.controller.adapter.read_only:
            self._defer(self.command, 'clear')
        elif key == Qt.Key_F2:
            self._defer(self.begin_edit)
        elif key in (Qt.Key_Home, Qt.Key_End) and self.controller.selection.current is not None:
            rows, columns = self._shape()
            row = (0 if key == Qt.Key_Home else rows - 1) if ctrl else self.controller.selection.current[0]
            target = (row, 0 if key == Qt.Key_Home else columns - 1)
            self._defer(self.select_range, self.controller.selection.anchor if shift else target, target)
        else:
            moves = {Qt.Key_Left: (0, -1), Qt.Key_Right: (0, 1), Qt.Key_Up: (-1, 0),
                     Qt.Key_Down: (1, 0), Qt.Key_Tab: (0, -1 if shift else 1),
                     Qt.Key_Return: (-1 if shift else 1, 0), Qt.Key_Enter: (-1 if shift else 1, 0)}
            if key in moves:
                self._defer(self._move, *moves[key], shift and key not in (Qt.Key_Tab, Qt.Key_Return, Qt.Key_Enter), key == Qt.Key_Tab)

    def _move(self, dr, dc, extend, tab):
        self.commit_editor()
        region = self.controller.selection.move(dr, dc, shape=self._shape(), extend=extend, tab=tab)
        if region is not None:
            self.select_range(self.controller.selection.anchor, self.controller.selection.current)

    def begin_edit(self):
        position = self.controller.selection.current
        if not self._item_table or position is None or self.controller.adapter.read_only:
            return False
        row, col = position
        try:
            self.controller.adapter.validate_changes({position: self.controller.adapter.cell_text(row, col)})
        except ValueError as exc:
            self.on_error(str(exc))
            return False
        self.commit_editor()
        self._edit_position = position
        self._editor = QLineEdit(self.controller.adapter.cell_text(row, col),
                                 parent=self.view.nativeRow(row), backend=self.backend,
                                 width=-1, auto_select_all=True)
        self.view.setCellWidget(row, col + self.first_column, self._editor)
        self._editor.setFocus()
        return True

    def commit_editor(self):
        if self._editor is None:
            return
        position, text = self._edit_position, self._editor.text()
        self.controller.adapter.write_cells({position: text})
        self.cancel_editor()

    def cancel_editor(self):
        if self._editor is not None:
            self._editor.delete()
            row, col = self._edit_position
            self.view.removeCellWidget(row, col + self.first_column)
            self._editor = self._edit_position = None

    def delete(self):
        self.cancel_editor()
        self.reset_selection()
        super().delete()
