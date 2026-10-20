from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from ..runtime.paths import safe_current_directory

from DearUIQt.dialogs.qt_dialog import QtDialog
from .folder_browser_address import FolderAddressBar, set_editor_text
from DearUIQt.modelview import (
    QtListItem, QtListView, QTreeWidget, QTreeWidgetItem,
    QTableWidget, QTableWidgetItem,
)
from DearUIQt.widgets import QLineEdit, QToolButton, QFrame, QSpacer, QLabel, QSeparator, QApplication, QImageView, QCanvas, QRetainedItem
from DearUIQt.layouts import QHBoxLayout, QVBoxLayout, QGridLayout
from DearUIQt.widgets import QMenu
from DearUIQt.modelview import qt_item_text_theme
from DearUIQt.gui import QtFusionPalette, QCursor, QKeyboard, QFontMetrics, QPainter
from DearUIQt.core import Qt, QEvent, QMouseEvent, QItemInputBinding, QGlobalInputBinding
from DearUIQt import QGuiRuntime
from DearUIQt.tooltip import add_styled_tooltip
from ..models.filesystem import FileSystemModel
from ..platform.windows_icons import WindowsIconRegistry
from ..platform.folder_browser_places import quick_access_places, drive_stock_id
from .folder_browser_style import (
    METRICS, browser_surface_theme, browser_dialog_body_theme,
    browser_layout_theme, browser_toolbar_theme, browser_workspace_theme,
    browser_field_shell_theme, browser_icon_slot_theme, browser_embedded_editor_theme,
    browser_sidebar_theme, browser_sidebar_row_theme, browser_sidebar_item_text_theme,
    browser_selected_text_theme, browser_name_item_theme,
    browser_file_editor_theme, browser_action_theme,
    browser_caption_theme,
    browser_row_cell_theme, browser_rename_editor_theme,
    browser_sidebar_item_container_theme, browser_sidebar_header_theme,
    browser_list_viewport_theme,
    browser_details_theme, browser_divider_theme, browser_selection_bar_theme,
    browser_empty_state_theme, browser_status_text_theme, browser_footer_theme,
    browser_sidebar_section_text_theme,
    browser_separator_theme, browser_toolbar_divider_theme, create_toolbar_divider,
    browser_tool_button_theme,
    browser_inline_icon_button_theme,
    navigation_button, navigation_button_theme,
    new_folder_texture, folder_item_texture, view_mode_texture, navigation_texture, navigation_disabled_texture,
    address_location_texture,
)


class FolderListView(QtListView):
    """Keep shared selection/keyboard behavior with compact folder-icon rows."""

    def __init__(self, *args, on_sort=None, **kwargs):
        self.details = {}
        self.entry_types = {}
        self.entry_sizes = {}
        self.icons = {}
        self.detail_texts = {}
        self._row_index = {}
        self._row_enabled = {}
        self._visual_selected_keys = set()
        self._visual_focus_active = False
        self._full_visual_sync = True
        self._qt_selection_themes = {}
        self._name_row_themes = {}
        self.sort_column, self.sort_ascending = 0, True
        self.empty_text = "This folder is empty."
        self.details_mode = True
        self.on_sort = on_sort
        self._last_click_key = None
        self._last_click_at = 0.0
        self._double_click_interval = self._system_double_click_interval()
        self._visual_hit_bindings = []
        self._visual_hit_registries = self._visual_hit_bindings  # compatibility alias
        self._row_pointer_binding = None
        self._row_pointer_registry = None
        self._row_generation = 0
        self._details_table = None
        self._empty_state_frame = None
        self._last_click_frame = None
        self._qt_bridge_click = None
        super().__init__(*args, **kwargs)
        # FolderListView is only a retained host for the real QTableWidget
        # viewport below.  Leaving the inherited QListView child-window
        # scrollable creates two nested vertical scroll owners.  Depending on
        # which native surface receives the wheel, the outer host can move
        # while the table still reports y-scroll == 0; hit-testing then maps a
        # visible row back to the first logical row.  QFileDialog/QAbstractItemView
        # semantics require one viewport/scroll owner, so only the table may
        # scroll in this specialized view.
        self._configure_many(no_scrollbar=True, no_scroll_with_mouse=True)
        self._reset_host_scroll()
        self._install_row_pointer_router()

    @staticmethod
    def _system_double_click_interval():
        if os.name == "nt":
            try:
                import ctypes
                return max(0.20, min(0.80, ctypes.windll.user32.GetDoubleClickTime() / 1000.0))
            except Exception:
                pass
        return 0.50

    def _clicked(self, sender, value, key):
        # A directory/filter refresh can reuse the same key with a new DPG
        # selectable. A queued callback from the old one must not act on it.
        if self._deleted or self.items.get(key) != sender:
            return
        item = next((item for item in self._values if item.key == key), None)
        if item is None or not item.enabled:
            return
        frame = (QApplication.instance().frameCount() if QApplication.instance() is not None else 0)
        if self._last_click_frame == (sender, frame):
            return  # visual-cell + selectable notifications from one press
        # A modal QApplication press can be dispatched before a DPG Selectable
        # callback that is drained on the *next* frame. Treat both as one
        # physical click, never as a second (double-click) activation.
        bridge = getattr(self, "_qt_bridge_click", None)
        if bridge is not None:
            # The Qt press already chose the row for this gesture. Native
            # Selectable/cell notifications may arrive on release, arbitrarily
            # many frames later (a held click, slow render, or busy dispatcher).
            # A short time window can turn that release into a second click and
            # navigate/reset selection. The next real Qt press clears the bridge
            # in LocalFolderDialog.event(), so no timing guess is necessary.
            keyboard_activation = False
            try:
                keyboard_activation = any(
                    self.backend.is_key_down(getattr(self.backend, name))
                    for name in ("mvKey_Spacebar", "mvKey_Return")
                    if getattr(self.backend, name, None) is not None)
            except Exception:
                pass
            if not keyboard_activation:
                return
            self._qt_bridge_click = None
        self._last_click_frame = (sender, frame)
        # Dear PyGui's native double-click flag is not reliable on every
        # Windows/DPG build when callbacks are manually pumped by a floating
        # dialog process.  Keep the shared QtListView behavior, then provide a
        # QFileDialog-style second-click fallback for the same folder row.
        now = time.monotonic()
        repeated = (
            key == self._last_click_key
            and 0.0 <= now - self._last_click_at <= self._double_click_interval
        )
        super()._clicked(sender, value, key)
        if repeated:
            self._last_click_key = None
            self._last_click_at = 0.0
            self.doubleClicked.emit(key)
            self.activated.emit(key)
            return
        self._last_click_key = key
        self._last_click_at = now

    def _is_double_click(self):
        # The graphics context survives selector leases. ImGui's double-click
        # flag can describe a click in the *previous* dialog at the same pixel.
        # This browser uses the same-row, same-instance history above instead.
        return False

    def _visual_cell_clicked(self, _sender, _app_data, key):
        """Route icon/detail-cell clicks through the row's real selection logic.

        The Name-cell Selectable already fills its remaining cell width, but
        QFileDialog users reasonably expect the folder icon and the Date/Type
        cells to behave as the same row.  Those cells are separate Dear PyGui
        items, so explicitly forward their pointer hit to _clicked.
        """
        item = self.items.get(key)
        if item is None:
            return
        self._clicked(item, True, key)

    def _bind_visual_cell_hit(self, item, key):
        try:
            generation = self._row_generation

            def clicked(sender, app_data=None, *_args):
                if not self._deleted and generation == self._row_generation:
                    self._visual_cell_clicked(sender, app_data, key)

            binding = (QItemInputBinding(item, backend=self.backend, parent=self)
                       .onClick(Qt.LeftButton, clicked)
                       .activate())
            self._visual_hit_bindings.append(binding)
        except Exception:
            pass

    def _install_row_pointer_router(self):
        """Make the complete visual table row one deterministic click target.

        A QFileDialog row is conceptually one item, but Dear ImGui renders our
        Name/icon/date/type cells as independent primitives.  Relying only on
        per-item callbacks therefore leaves gaps in the visual row and is also
        sensitive to a handler registry being rebuilt between mouse-down and
        callback dispatch.  A single context-level left-click handler hit-tests
        the *current* row geometry and forwards the press to the retained list
        selection model.

        Native Selectable/cell callbacks are intentionally left in place.
        ``_last_click_frame`` coalesces those duplicate notifications when both
        routes observe the same physical press.
        """
        try:
            self._row_pointer_binding = (
                QGlobalInputBinding(backend=self.backend, parent=self)
                .onMouseClick(Qt.LeftButton, self._row_pointer_clicked)
                .activate()
            )
        except Exception:
            self._row_pointer_binding = None

    def _reset_host_scroll(self):
        """Keep the inherited QListView host fixed at scroll origin.

        The nested QTableWidget is the only scroll viewport in this browser.
        This is intentionally cheap and idempotent so native pointer recovery
        can repair a host that received a stray wheel event before the queued
        ``no_scroll_with_mouse`` configuration reached the renderer.
        """
        try:
            if abs(float(self.backend.get_y_scroll(self.tag))) > 0.01:
                self.backend.set_y_scroll(self.tag, 0.0)
        except Exception:
            pass

    def _arm_native_click_bridge(self, key):
        """Suppress delayed native callbacks from the same physical click."""
        application = QApplication.instance()
        frame = application.frameCount() if application is not None else -1
        self._qt_bridge_click = (key, frame, time.monotonic())

    def _route_pointer_key(self, key):
        """Select one hit-tested row and own the complete pointer transaction.

        Row presses can enter through QApplication, the global Dear ImGui
        binding, or the native HWND recovery hook.  Previously only the first
        route armed ``_qt_bridge_click``.  If a delayed/stale Selectable
        callback then arrived through either of the other routes, it could
        overwrite the correct selection with row 0.  Centralizing the bridge
        here makes every pointer path deterministic.
        """
        selectable = self.items.get(key)
        native_item = getattr(self, "nativeItem", None)
        target = native_item(key) if callable(native_item) else selectable
        if target is None:
            return False
        # This routed hit is a new physical press.  Clear the previous bridge
        # so a rapid genuine second click can still become a double click.
        self._qt_bridge_click = None
        self._clicked(target, True, key)
        # Arm unconditionally for this hit-tested native target.  Even if the
        # row is disabled or the same-frame duplicate was coalesced by
        # ``_clicked``, a queued Selectable callback still belongs to this
        # physical press and must not be allowed to retarget another row.
        self._arm_native_click_bridge(key)
        return True

    def verticalScrollValue(self):
        """Return the scroll position of the actual details table viewport.

        FolderListView owns an outer child-window only as a host.  The visible
        scrollbar belongs to QTableWidget, so reading the host scroll value
        returns zero even while the user is far down the directory.
        """
        self._reset_host_scroll()
        table = getattr(self, "_details_table", None)
        if table is not None and not getattr(table, "_deleted", False):
            try:
                return float(self.backend.get_y_scroll(table.tag))
            except Exception:
                pass
        return super().verticalScrollValue()

    def setVerticalScrollValue(self, value):
        """Set the real table scroll position while pinning the host at zero."""
        value = max(0.0, float(value))
        self._reset_host_scroll()
        table = getattr(self, "_details_table", None)
        if table is not None and not getattr(table, "_deleted", False):
            try:
                self.backend.set_y_scroll(table.tag, value)
                return self
            except Exception:
                pass
        return self

    def _restore_table_scroll(self, table_tag, value, generation):
        """Restore table scroll without ever reviving the outer host scroll."""
        if self._deleted or generation != self._row_generation:
            return
        self._reset_host_scroll()
        table = getattr(self, "_details_table", None)
        if table is None or getattr(table, "_deleted", False) or table.tag != table_tag:
            return
        try:
            self.backend.set_y_scroll(table_tag, max(0.0, float(value)))
        except Exception:
            pass

    def _table_row_key_at(self, x, y):
        """Return the visible details-row key at a global point.

        The selector uses compact rows that are shorter than DearUIQt's generic
        table metric.  ``QTableWidget.rowAtGlobal`` therefore becomes a poor
        estimate deep in a long, scrolled directory.  Resolve the index from
        the table's *actual native row height* and its own y-scroll instead,
        then verify only a few neighboring native rows.  This keeps hit-testing
        O(1) and prevents stale embedded Selectable geometry from mapping a
        click to row zero after scrolling.
        """
        table = getattr(self, "_details_table", None)
        if table is None or getattr(table, "_deleted", False) or not self._values:
            return None
        backend = self.backend
        try:
            table_left, table_top = map(float, backend.get_item_rect_min(table.tag))
            table_width, table_height = map(float, backend.get_item_rect_size(table.tag))
            if table_width <= 0 or table_height <= 0:
                return None
            if not (table_left <= float(x) < table_left + table_width
                    and table_top <= float(y) < table_top + table_height):
                return None
            scroll = max(0.0, float(backend.get_y_scroll(table.tag)))
            first_row = table.nativeRow(0)
            row_height = float(backend.get_item_rect_size(first_row)[1])
            if row_height <= 0:
                row_height = float(METRICS.row_height)
            header_height = float(METRICS.header_height if self.details_mode else 0)
            estimated = int((float(y) - table_top - header_height + scroll) // row_height)
        except Exception:
            return None

        if not 0 <= estimated < len(self._values):
            return None

        # Theme padding can shift the arithmetic estimate by one row. Probe a
        # tiny fixed neighborhood, never the whole directory.
        candidates = [estimated]
        for distance in range(1, 5):
            candidates.extend((estimated - distance, estimated + distance))
        for row_index in candidates:
            if not 0 <= row_index < len(self._values):
                continue
            try:
                row_tag = table.nativeRow(row_index)
                rect = QRetainedItem(row_tag).globalGeometry(clipped=True)
                if not rect.isEmpty() and rect.contains((int(x), int(y))):
                    return self._values[row_index].key
            except Exception:
                continue
        return None

    def _row_pointer_clicked(self, *_args, point=None):
        if self._deleted or not self.items:
            return
        self._reset_host_scroll()
        # The global DPG click router must not select a row behind a combo,
        # context menu or another popup. QApplication's modal dialog itself
        # is not a popup, and is intentionally excluded from this gate.
        application = QApplication.instance()
        if application is not None and application.activePopupWidget() is not None:
            return
        backend = getattr(self, "backend", None)
        if backend is not None and QGuiRuntime(backend).hasActivePopupSurface(include_modals=False):
            return
        visible = getattr(self, "isVisible", None)
        if callable(visible) and not visible():
            return
        try:
            if point is None:
                current = QCursor.pos(backend=getattr(self, "backend", None))
            else:
                current = point
            if hasattr(current, "x"):
                x, y = float(current.x()), float(current.y())
            else:
                x, y = map(float, current)

            geometry = getattr(self, "globalGeometry", None)
            if callable(geometry):
                bounds = geometry(clipped=True)
                if bounds.isEmpty() or not bounds.contains((int(x), int(y))):
                    return
            else:
                # Compatibility for isolated legacy harnesses. Real
                # FolderListView instances use QWidget.globalGeometry above.
                table = getattr(self, "table", None)
                retained = QRetainedItem(table) if table is not None else None
                if retained is None or not retained.exists() or not retained.isVisible():
                    return
                bounds = retained.globalGeometry(clipped=True)
                if not bounds.contains((int(x), int(y))):
                    return
        except Exception:
            return

        # The QTableWidget owns the actual vertical scrollbar. Resolve the
        # visible row from the table itself before touching embedded Selectable
        # geometry; rowAtGlobal() includes the table's current y-scroll offset.
        details_table = getattr(self, "_details_table", None)
        table_available = details_table is not None and not getattr(details_table, "_deleted", False)
        table_key = self._table_row_key_at(x, y) if table_available else None
        if table_key is not None and self._route_pointer_key(table_key):
            return True
        if table_available:
            # Never fall back to stale embedded Selectable geometry while the
            # details table exists. If the table has not produced valid row
            # geometry yet, leave the press to its native cell callbacks.
            return False

        # Compatibility fallback for list mode / isolated harnesses where the
        # details table is unavailable. Rows are inserted in visual order.
        rows = tuple(self.items.items())
        item_geometry = getattr(self, "itemGeometry", None)
        if callable(item_geometry) and len(rows) > 8:
            lo, hi = 0, len(rows) - 1
            geometry_unavailable = False
            while lo <= hi:
                mid = (lo + hi) // 2
                key, selectable = rows[mid]
                try:
                    rect = item_geometry(key, include_check_indicator=False)
                    if rect.isEmpty():
                        geometry_unavailable = True
                        break
                    top = float(rect.top())
                    # Unrendered rows can report zero origin even when the
                    # scrolling viewport is nowhere near (0, 0).
                    if top == 0 and bounds.top() > 0:
                        geometry_unavailable = True
                        break
                    height = max(float(METRICS.row_height), float(rect.height()))
                except Exception:
                    geometry_unavailable = True
                    break
                if top <= y < top + height:
                    return self._route_pointer_key(key)
                if y < top:
                    hi = mid - 1
                else:
                    lo = mid + 1
            if not geometry_unavailable:
                return False

        for key, selectable in rows:
            try:
                if callable(item_geometry):
                    rect = item_geometry(key, include_check_indicator=False)
                    if rect.isEmpty():
                        continue
                    row_top, row_height = float(rect.top()), float(rect.height())
                else:
                    retained = QRetainedItem(selectable)
                    if not retained.exists() or not retained.isVisible():
                        continue
                    row_rect = retained.globalGeometry()
                    row_top, row_height = float(row_rect.y()), float(row_rect.height())
                row_height = max(float(METRICS.row_height), row_height)
            except Exception:
                continue
            if row_top <= y < row_top + row_height:
                if self._route_pointer_key(key):
                    return True

    def delete(self):
        empty_state = self._empty_state_frame
        self._empty_state_frame = None
        if empty_state is not None:
            try:
                if empty_state.exists():
                    empty_state.delete()
            except Exception:
                pass
        details_table = self._details_table
        self._details_table = None
        if details_table is not None:
            try:
                if details_table.exists():
                    details_table.delete()
            except Exception:
                pass
        binding, self._row_pointer_binding = self._row_pointer_binding, None
        if binding is not None:
            try:
                binding.delete()
            except Exception:
                pass
        self._row_pointer_registry = None
        for binding in self._visual_hit_bindings:
            try:
                binding.delete()
            except Exception:
                pass
        self._visual_hit_bindings.clear()
        super().delete()

    def setItems(self, items):
        # Snapshot the *table* scroll before destroying it. The outer
        # QtListView host does not own the visible scrollbar.
        previous_table = getattr(self, "_details_table", None)
        had_details_table = previous_table is not None and not getattr(previous_table, "_deleted", False)
        preserved_scroll = self.verticalScrollValue() if had_details_table else 0.0

        self._full_visual_sync = True
        self._row_generation += 1
        self._last_click_key = self._last_click_frame = None
        self._last_click_at = 0.0
        self._qt_bridge_click = None
        # Dispose any prior transient/empty overlay before rebuilding. Loading
        # and empty-folder states are mutually exclusive retained surfaces;
        # keeping the old loading frame alive is what made an empty directory
        # continue to say "Loading..." after enumeration completed.
        empty_state = self._empty_state_frame
        self._empty_state_frame = None
        if empty_state is not None:
            try:
                if empty_state.exists():
                    empty_state.delete()
            except Exception:
                pass

        # Dispose the retained table wrapper before QtListView rebuilds the
        # viewport children.  This keeps QObject/native ownership in sync across
        # asynchronous directory refreshes.
        details_table = self._details_table
        self._details_table = None
        if details_table is not None:
            try:
                if details_table.exists():
                    details_table.delete()
            except Exception:
                pass
        for binding in self._visual_hit_bindings:
            try:
                binding.delete()
            except Exception:
                pass
        self._visual_hit_bindings.clear()
        self.detail_texts.clear()
        self._row_index.clear()
        # The embedded Selectables were children of the deleted table. Force
        # QtListView through its structural rebuild path even when the logical
        # rows are identical; otherwise its no-op fast path can retain native
        # ids that were destroyed together with the previous table.
        if had_details_table:
            self._values = []
        super().setItems(items)
        self._row_enabled = {item.key: bool(item.enabled) for item in self._values}
        for key in tuple(self.items):
            self.setItemSizeHint(key, width=0, height=METRICS.row_height)
        self.icons.clear()

        column_count = 4 if self.details_mode else 1
        table = QTableWidget(
            rows=len(self._values), columns=column_count, parent=self.tag,
            header_row=self.details_mode, width=-1, height=-1,
            row_background=True, grid_lines=False, freeze_rows=1 if self.details_mode else 0,
            sortable=self.details_mode, callback=self._sorted,
            borders_outerH=False, borders_outerV=False, pad_outerX=False,
        )
        self._details_table = table
        self.table = table.tag
        self._reset_host_scroll()
        table.setTheme(browser_details_theme())
        table.setHorizontalHeaderLabels(["Name", "Size", "Type", "Date Modified"][:column_count])
        table.setColumnStretch(0, 1.0)
        name_column = table.nativeColumn(0)
        table.setColumnSortIndicator(0, self.sort_ascending, default=self.sort_column == 0)
        self.detail_columns = ()
        self._column_keys = {name_column: 0}
        if self.details_mode:
            table.setColumnWidth(1, 74)
            table.setColumnWidth(2, 96)
            table.setColumnWidth(3, 145)
            size_column = table.nativeColumn(1)
            date_column, type_column = table.nativeColumn(3), table.nativeColumn(2)
            table.setColumnSortIndicator(1, self.sort_ascending, default=self.sort_column == 2)
            table.setColumnSortIndicator(3, self.sort_ascending, default=self.sort_column == 1)
            table.setColumnSortable(2, False)
            self.detail_columns = (date_column, type_column)
            self._column_keys[date_column] = 1
            self._column_keys[size_column] = 2

        for row_index, item in enumerate(self._values):
            tag = self.items[item.key]
            row = table.nativeRow(row_index)
            self._row_index[item.key] = row_index
            name = QHBoxLayout(parent=row, spacing=4).tag
            icon_canvas = QCanvas(parent=name, width=18, height=METRICS.row_height)
            icon_slot = icon_canvas.tag
            entry_type = self.entry_types.get(item.key, "Folder")
            texture = folder_item_texture() if entry_type == "Folder" else WindowsIconRegistry.get_icon(Path(item.key).suffix)
            icon_y = max(0, (METRICS.row_height - 16) // 2)
            self.icons[item.key] = QPainter(icon_canvas).drawImage(
                texture,
                (1, icon_y),
                (17, icon_y + 16),
                uv_min=(0, 0), uv_max=(1, 1))
            self._bind_visual_cell_hit(icon_slot, item.key)
            QRetainedItem(tag).reparent(name)
            QRetainedItem(tag).configure(label=item.text, width=0, height=METRICS.row_height, span_columns=True)
            if self.details_mode:
                modified = self.details.get(item.key, 0)
                date = datetime.fromtimestamp(modified).strftime("%m/%d/%Y %H:%M") if modified else ""
                date_item = QTableWidgetItem(date)
                date_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                type_item = QTableWidgetItem(entry_type)
                type_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                size_text = self._format_size(self.entry_sizes.get(item.key)) if entry_type != "Folder" else ""
                size_item = QTableWidgetItem(size_text)
                size_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                table.setItem(row_index, 1, size_item)
                table.setItem(row_index, 3, date_item)
                table.setItem(row_index, 2, type_item)
                date_text = table.nativeItem(row_index, 3)
                type_text = table.nativeItem(row_index, 2)
                size_cell = table.nativeItem(row_index, 1)
                self._bind_visual_cell_hit(size_cell, item.key)
                self._bind_visual_cell_hit(date_text, item.key)
                self._bind_visual_cell_hit(type_text, item.key)
                self.detail_texts[item.key] = (date_text, type_text, size_cell)
        if not self._values:
            self._add_empty_state()
        # Table cells were created after QtListView's model reset; apply their
        # initial (unselected/selected) palette just once, not per click.
        self._full_visual_sync = True
        self._sync_selection_visuals()
        if preserved_scroll > 0.0 and self._values:
            # Set once immediately and once after the renderer has calculated
            # the new table's scroll maximum. The second write is generation-
            # guarded so it cannot pull a newly navigated directory backwards.
            self.setVerticalScrollValue(preserved_scroll)
            if self._after is not None:
                try:
                    self._after(1, self._restore_table_scroll,
                                table.tag, preserved_scroll, self._row_generation)
                except Exception:
                    pass
        return self

    @staticmethod
    def _format_size(value):
        if value is None:
            return ""
        size = float(value)
        for unit in ("bytes", "KiB", "MiB", "GiB", "TiB"):
            if size < 1024 or unit == "TiB":
                return "{} {}".format(int(size), unit) if unit == "bytes" else "{:.2f} {}".format(size, unit)
            size /= 1024.0

    def _sync_selection_visuals(self):
        """Update only changed rows; do not re-theme the entire directory.

        A folder with thousands of files previously sent a renderer call for
        *every* Name/Date/Type/Size cell on each mouse click. This blocks the
        UI thread and makes the selector appear to ignore input. A full paint
        is required only after replacing the directory model. Ordinary
        SingleSelection clicks touch at most the old and new selected rows.
        """
        selected = set(self.selected)
        active = bool(getattr(self, "_has_focus", False))
        previous = getattr(self, "_visual_selected_keys", set())
        full = getattr(self, "_full_visual_sync", True)
        dirty = set(self.items) if full else (selected ^ previous)
        if active != getattr(self, "_visual_focus_active", False):
            dirty.update(selected | previous)

        # The Name column is an embedded Selectable while the detail columns
        # are table text cells. Bind one browser-specific row theme to every
        # dirty Name item so its vertical baseline stays aligned with the
        # table cells in normal, selected and focused states alike.
        for key in dirty:
            native = self.items.get(key)
            if native is None:
                continue
            chosen = key in selected
            disabled = not self._row_enabled.get(key, True)
            current = (key == self.current)
            state = (chosen, disabled, current, active)
            theme = self._name_row_themes.get(state)
            if theme is None:
                theme = browser_name_item_theme(
                    selected=chosen, disabled=disabled,
                    current=current, active=active)
                self._name_row_themes[state] = theme
            try:
                self.backend.set_value(native, chosen)
                self.backend.bind_item_theme(native, theme)
            except Exception:
                pass

        # The Name Selectable spans all table columns, so it owns both hover
        # and selected backgrounds.  Do not add a second native table-row
        # highlight: its row geometry is slightly taller than the Selectable
        # and makes selection appear larger than hover.
        if active not in self._qt_selection_themes:
            self._qt_selection_themes[active] = browser_selected_text_theme(active=active)
        selected_text_theme = self._qt_selection_themes[active]
        for key in dirty:
            cells = self.detail_texts.get(key)
            if not cells:
                continue
            theme = (selected_text_theme if key in selected else qt_item_text_theme(
                self.backend, selected=False,
                disabled=not self._row_enabled.get(key, True), active=active))
            for cell in cells:
                try:
                    self.backend.bind_item_theme(cell, theme)
                except Exception:
                    pass
        self._visual_selected_keys = selected
        self._visual_focus_active = active
        self._full_visual_sync = False

    def _sorted(self, _sender, specs, _user_data):
        # DPG sort specs contain column item IDs, not positional indices.
        if specs and self.on_sort:
            self.on_sort([(self._column_keys[column], direction)
                          for column, direction in specs if column in self._column_keys])

    def _add_empty_state(self):
        """Render transient/empty content inside the details viewport body.

        The frame is positioned absolutely below the table header so it behaves
        like Explorer's empty-folder message rather than becoming another
        vertical layout item above the header.  It is retained and explicitly
        destroyed on every model rebuild.
        """
        old_state = self._empty_state_frame
        self._empty_state_frame = None
        if old_state is not None:
            try:
                if old_state.exists():
                    old_state.delete()
            except Exception:
                pass

        state_frame = QFrame(
            parent=self.tag, width=-1, height=76, frame_shape=QFrame.NoFrame,
            no_scrollbar=True, no_scroll_with_mouse=True,
            pos=(0, METRICS.header_height),
        )
        self._empty_state_frame = state_frame
        state = state_frame.tag
        state_frame.setTheme(browser_empty_state_theme())
        QSpacer(parent=state, height=18)
        empty_layout = QGridLayout(
            3, column_widths=(None, 280, None), parent=state_frame, height=0)
        QRetainedItem(empty_layout.tag).setTheme(
            browser_layout_theme(cell_padding=(0, 0)))
        QSpacer(width=1, parent=empty_layout.cell(0, 0))
        message_cell = empty_layout.cell(0, 1)
        QLabel(self.empty_text, parent=message_cell)
        if self.empty_text == "Loading...":
            QLabel("Reading folders in this location...", parent=message_cell)
        elif self.empty_text.startswith("No folders match"):
            QLabel("Try a different search term.", parent=message_cell)
        QSpacer(width=1, parent=empty_layout.cell(0, 2))



class LocalFolderDialog(QtDialog):
    """Dear ImGui/Dear PyGui local-folder browser.

    This replaces the historical external native folder-picker helper. Directory I/O
    is performed on a small worker thread owned by the dialog process while all
    widgets and selection state stay on the Dear PyGui UI thread.
    """

    dialog_title = "Open Folder"
    REUSABLE_HOST = True
    selection_caption = "Folder:"
    accept_caption = "Select Folder"
    context_selection_caption = "Select folder"
    selection_height = METRICS.selection_height

    def event(self, event):
        """Deliver Qt mouse presses to the selector's retained item views.

        QApplication gives a modal QDialog first refusal of pointer events.
        That is correct for focus/ownership, but its generic QDialog handler
        does not know the browser's ImGui table cells.  Route the press to the
        visible row (or sidebar) before allowing it to fall through.  Native
        Selectable and cell callbacks remain as a compatible fallback; the
        list's per-frame guard coalesces duplicate notifications.
        """
        if (event.type() == QEvent.MouseButtonPress
                and isinstance(event, QMouseEvent)
                and event.button() == Qt.LeftButton):
            application = QApplication.instance()
            if application is not None and application.activeModalWidget() is self:
                # A new press starts a new transaction, even when two genuine
                # clicks occur rapidly on the same file/folder row.
                self.listbox._qt_bridge_click = None
                if self._selector_pointer_hit(event.globalPosition()):
                    frame = application.frameCount()
                    key = self.listbox.current
                    if key in self.listbox.selected:
                        self.listbox._qt_bridge_click = (key, frame, time.monotonic())
                    event.accept()
                    return True
        return super().event(event)

    def _selector_pointer_hit(self, point):
        """Select only browser content, never popup/editor/overlay pixels."""
        if (not self.winfo_exists() or not self.isVisible()
                or self._folder_menu_is_open() or self._folder_menu_action_pending
                or self._rename_path is not None or self._rename_after_load is not None):
            return False
        application = QApplication.instance()
        if application is not None:
            if application.activePopupWidget() is not None:
                return False
            active_modal = application.activeModalWidget()
            if active_modal is not None and active_modal is not self:
                return False
        if QGuiRuntime().hasActivePopupSurface(exclude=self.tag, include_modals=False):
            return False
        if self.listbox._row_pointer_clicked(point=point):
            return True
        try:
            x, y = (float(point.x()), float(point.y())) if hasattr(point, 'x') else map(float, point)
            bounds = QRetainedItem(self.places).globalGeometry(clipped=True)
            if bounds.isEmpty() or not bounds.contains((int(x), int(y))):
                return False
            for path, (item, _is_drive) in tuple(self._place_items.items()):
                button = self._places_tree.nativeItem(item)
                if button is None:
                    continue
                button_item = QRetainedItem(button)
                if not button_item.exists() or not button_item.isVisible():
                    continue
                row = self._places_tree.nativeRow(item)
                bounds = QRetainedItem(row).globalGeometry(clipped=True)
                if not bounds.isEmpty() and bounds.contains((int(x), int(y))):
                    self._place_clicked(button, True, path)
                    return True
        except Exception:
            return False
        return False

    def native_pointer_press(self, point):
        """Recover a foreground native press missed by the ImGui hit target.

        The floating host validates foreground/disabled HWNDs before calling
        this method. A registered QApplication modal is *our own* selector,
        not a reason to reject its own item presses.
        """
        from DearUIQt.input_gate import native_background_input_blocked, native_modal_input_active
        application = QApplication.instance()
        active_modal = application.activeModalWidget() if application is not None else None
        if (native_modal_input_active() or
                (active_modal is not None and active_modal is not self)):
            return False
        # When this selector itself owns QApplication modality, its native HWND
        # can appear in the global background-input gate. Only a *different*
        # modal must block the selector. Standalone recovery still honors the
        # global native gate unconditionally.
        if native_background_input_blocked() and active_modal is not self:
            return False
        return self._selector_pointer_hit(point)

    def __init__(self, view, initial, on_result):
        self.on_result = on_result
        self._finished = False
        self._generation = 0
        self._initial_location_pending = True
        self._current_path = self._normalize_initial(initial)
        self._entries = {}
        self._back_paths, self._forward_paths = [], []
        self._listing = []
        self._folder_mtimes = {}
        self._entry_types = {}
        self._entry_sizes = {}
        self._sort_column, self._sort_ascending = 0, True
        self._place_items, self.place_buttons = {}, {}
        self._pending_place_path = None
        self._place_navigation_scheduled = False
        self._place_transaction = None
        self._pending_row_activation = None
        self._row_activation_scheduled = False
        self._creating_folder = False
        self._select_after_load = None
        self._rename_after_load = None
        self._rename_path = None
        self._rename_editor = None
        self._rename_editor_control = None
        self._rename_source = None
        self._folder_context_menu = None
        self._folder_menu_action_pending = False
        super().__init__(view, self.dialog_title, 680, 420, footer=False)
        self._font_metrics = QFontMetrics()
        self._selector_themes = {}
        self._form_labels = {}
        self._caption_theme = browser_caption_theme()
        QRetainedItem(self.tag).configure(on_close=lambda *_args: self._close_from_native())
        self.preferred_size = (680, 420)
        self.contentWidget()._configure_many(no_scrollbar=True, no_scroll_with_mouse=True)
        self.contentWidget().setTheme(browser_dialog_body_theme())
        # Toolbar icons are generated geometry/textures; avoid font-dependent glyph metrics.
        self._navigation_font = None
        self._navigation_theme = navigation_button_theme()
        self._location_toolbar_frame = QFrame(
            parent=self.content, width=-1, height=METRICS.toolbar_height,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True)
        self.location_toolbar = self._location_toolbar_frame.tag
        self._location_toolbar_frame.setTheme(browser_toolbar_theme())
        self._location_grid = self.own_widget(QGridLayout(
            6, column_widths=(METRICS.label_width, None, 3 * METRICS.tool_button_size + 2,
                              METRICS.tool_button_size, METRICS.tool_button_size, METRICS.tool_button_size),
            parent=self._location_toolbar_frame, height=0))
        self._location_grid.setTheme(browser_layout_theme(cell_padding=(METRICS.form_gap // 2, 0)))

        self._form_labels['location'] = self._form_caption("Look in:", self._location_grid.cell(0, 0))
        nav_cell = self._location_grid.cell(0, 2)
        self._nav_layout = QHBoxLayout(parent=nav_cell, spacing=1)
        nav = self._nav_layout.tag
        self.back_button = self._nav_button(nav, "Back", self._go_back)
        self.forward_button = self._nav_button(nav, "Forward", self._go_forward)
        self.up_button = self._nav_button(nav, "Up", self._go_up)

        self._address_grid = self.own_widget(QGridLayout(
            1, column_widths=(None,), parent=self._location_grid.cell(0, 1),
            height=0))
        self._address_grid.setTheme(browser_layout_theme(cell_padding=(0, 0)))
        address_host = self._address_grid.cell(0, 0)
        self.address = FolderAddressBar(self, address_host.tag)
        self.address_icon = self.address.icon
        self._path_edit_control = self.address._editor_control
        self.path_edit = self.address.editor
        self.breadcrumbs = self.address.breadcrumbs

        self._search_shell_frame = QFrame(
            parent=self.content, width=-1, height=METRICS.location_height, show=False,
            frame_shape=QFrame.StyledPanel, no_scrollbar=True,
            no_scroll_with_mouse=True)
        self.search_shell = self._search_shell_frame.tag
        self._search_normal_theme = browser_field_shell_theme()
        self._search_focus_theme = browser_field_shell_theme(focused=True)
        self._search_clear_theme = browser_inline_icon_button_theme()
        self._search_shell_frame.setTheme(self._search_normal_theme)
        self._search_grid = self.own_widget(QGridLayout(
            3, column_widths=(21, None, 20), parent=self._search_shell_frame, height=0))
        self._search_grid.setTheme(browser_layout_theme(cell_padding=(1, 0)))
        search_icon_frame = QFrame(
            parent=self._search_grid.cell(0, 0), width=21, height=METRICS.location_height - 2,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True)
        search_icon_slot = search_icon_frame.tag
        search_icon_frame.setTheme(browser_icon_slot_theme())
        self._search_icon_view = QImageView(
            navigation_texture("search"), parent=search_icon_frame, width=20, height=20,
            pos=(2, max(0, (METRICS.location_height - 18) // 2)))
        self._filter_edit_control = self.line_edit_widget(
            "", parent=self._search_grid.cell(0, 1), width=-1, hint="Search this folder",
            callback=lambda *_args: self._search_changed())
        self._filter_edit_control.setTheme(browser_embedded_editor_theme(self._font_metrics.height()))
        self.filter_edit = self._filter_edit_control.tag
        clear_slot_frame = QFrame(
            parent=self._search_grid.cell(0, 2), width=20, height=METRICS.location_height - 2,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True)
        clear_slot = clear_slot_frame.tag
        clear_slot_frame.setTheme(browser_icon_slot_theme())
        self._clear_search_control = QToolButton(
            "", parent=clear_slot, icon=navigation_texture("clear"),
            icon_size=(12, 12))
        self._clear_search_control.clicked.connect(self._clear_search)
        self._clear_search_control.hide()
        self.clear_search_button = self._clear_search_control.tag
        self._clear_search_control.move(2, 5)
        self._clear_search_control.setTheme(self._search_clear_theme)
        add_styled_tooltip(self.clear_search_button, "Clear search")
        self._bind_search_focus()

        self._new_folder_control = QToolButton(
            "", parent=self._location_grid.cell(0, 3), icon=new_folder_texture(), icon_size=(16, 16),
            width=METRICS.tool_button_size, height=METRICS.tool_button_size)
        self._new_folder_control.clicked.connect(self._show_new_folder)
        self.new_folder_button = self._new_folder_control.tag
        self._new_folder_control.setTheme(self._navigation_theme)
        add_styled_tooltip(self.new_folder_button, "New folder (Ctrl+Shift+N)")
        self._details_view_control = QToolButton(
            "", parent=self._location_grid.cell(0, 5), icon=view_mode_texture("details"), icon_size=(16, 16),
            width=METRICS.tool_button_size, height=METRICS.tool_button_size)
        self._details_view_control.clicked.connect(lambda: self._change_view("Details"))
        self.details_view_button = self._details_view_control.tag
        self._list_view_control = QToolButton(
            "", parent=self._location_grid.cell(0, 4), icon=view_mode_texture("list"), icon_size=(16, 16),
            width=METRICS.tool_button_size, height=METRICS.tool_button_size)
        self._list_view_control.clicked.connect(lambda: self._change_view("List"))
        self.list_view_button = self._list_view_control.tag
        self._details_tool_theme = browser_tool_button_theme(checked=True)
        self._list_tool_theme = browser_tool_button_theme(checked=False)
        self._details_view_control.setTheme(self._details_tool_theme)
        self._list_view_control.setTheme(self._list_tool_theme)
        add_styled_tooltip(self.details_view_button, "Details view")
        add_styled_tooltip(self.list_view_button, "List view")
        # Compatibility alias for code that treated the old combo as the view control.
        self.view_mode = self.details_view_button
        self._toolbar_separator_control = QSeparator(parent=self.content)
        toolbar_separator = self._toolbar_separator_control.tag
        self._toolbar_separator_control.setTheme(browser_separator_theme())
        self._workspace_frame = QFrame(
            parent=self.content, width=-1, height=-self.selection_height,
            frame_shape=QFrame.StyledPanel, no_scrollbar=True,
            no_scroll_with_mouse=True)
        self.workspace = self._workspace_frame.tag
        self._workspace_frame.setTheme(browser_workspace_theme())
        self._workspace_layout = QHBoxLayout(parent=self._workspace_frame, spacing=0)
        self._places_tree = self.own_widget(QTreeWidget(
            parent=self._workspace_layout, width=METRICS.sidebar_width, height=-1,
            row_height=METRICS.sidebar_row_height, indentation=18,
            icon_size=(16, 16), root_spacing=METRICS.sidebar_section_gap,
            ))
        self.places = self._places_tree.tag
        self._places_tree.setExpandOnItemClick(True)
        self._places_tree.setIndentation(0)
        self._places_tree.setRootSectionsVisible(False)
        self._places_tree.itemClicked.connect(self._place_tree_clicked, receiver=self)
        self._places_tree.layoutChanged.connect(
            self._refresh_place_button_aliases, receiver=self)
        self._places_tree.setTheme(browser_sidebar_theme())
        # Preserve the 0.0.5 QFileDialog/Fusion presentation: 13 px labels,
        # native 16 px icons, explicit branch/text alignment (not spaces).
        self._places_tree.setItemTextOverlay(size=13, color=QtFusionPalette.TEXT)
        self.quick_group = self._place_section("Quick access")
        for label, path in quick_access_places():
            self._add_place(label, path, WindowsIconRegistry.get_icon(is_dir=True),
                            parent=self.quick_group)
        self.drive_group = self._place_section(
            "This PC", WindowsIconRegistry.get_stock_icon(94))
        for drive in self._drives():
            self._add_place(drive, drive, WindowsIconRegistry.get_stock_icon(drive_stock_id(drive)),
                            is_drive=True, parent=self.drive_group)
        self._refresh_place_button_aliases()
        divider_frame = QFrame(
            parent=self._workspace_layout, width=METRICS.divider_width, height=-1,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True)
        divider = divider_frame.tag
        divider_frame.setTheme(browser_divider_theme())
        self._folder_region_frame = QFrame(
            parent=self._workspace_layout, width=-1, height=-1, frame_shape=QFrame.NoFrame,
            no_scrollbar=True, no_scroll_with_mouse=True)
        self.folder_region = self._folder_region_frame.tag
        self._folder_region_frame.setTheme(browser_surface_theme())
        self.listbox = self.own_widget(
            FolderListView(
                self.folder_region,
                [],
                width=-1,
                height=-1,
                multiple=False,
                after=self.view.after,
                on_sort=self._sort_entries,
            )
        )
        self.listbox._configure("border", False)
        self.listbox.setTheme(browser_list_viewport_theme())
        self.listbox.doubleClicked.connect(self._queue_row_activation)
        self.listbox.currentChanged.connect(self._selection_changed)
        self.active_table = self.listbox
        self._selection_separator_control = QSeparator(parent=self.content)
        selection_separator = self._selection_separator_control.tag
        self._selection_separator_control.setTheme(browser_separator_theme())
        self._selection_bar_frame = QFrame(
            parent=self.content, width=-1, height=self.selection_height,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True)
        self.selection_bar = self._selection_bar_frame.tag
        self._selection_bar_frame.setTheme(browser_selection_bar_theme())
        self._build_selection_fields()
        self.enter_editors.update((self.path_edit, self.folder_edit, self.filter_edit))
        self.status = self.status_text("", parent=self._selection_grid.cell(2, 1).tag)
        self.set_control_visible(self.status, False)
        self._status_normal_theme = browser_status_text_theme(error=False)
        self._status_error_theme = browser_status_text_theme(error=True)
        self.set_control_theme(self.status, self._status_normal_theme)
        self._accept_button = self.action(
            self.accept_caption, self._select_folder, role="primary", default=True,
            parent=self._selection_grid.cell(0, 2), width=METRICS.action_width, height=METRICS.control_height)
        cancel_button = self.action("Cancel", lambda: self.finish(None),
                                  parent=self._selection_grid.cell(1, 2), width=METRICS.action_width,
                                  height=METRICS.control_height)
        self.control_wrapper(self._accept_button).setThemeProvider(self._selector_theme_provider('accept'))
        self.control_wrapper(cancel_button).setThemeProvider(self._selector_theme_provider('cancel'))
        self.set_control_enabled(self._accept_button, False)
        if self.footer_shell is not None:
            self.set_control_theme(self.footer_shell, browser_footer_theme())
        self.setMinimumSize(560, 340)
        self._create_folder_context_menu()
        self._update_navigation()
        self._set_status("Loading...")
        self.after_first_present(self._load_initial_contents)
        self._install_browser_keys()
        self.view.after(0, self._apply_layout)

    def _build_selection_fields(self):
        self._selection_grid = self.own_widget(QGridLayout(
            3, column_widths=(METRICS.label_width, None, METRICS.action_width), parent=self._selection_bar_frame))
        self._selection_grid.setTheme(browser_layout_theme(
            cell_padding=(METRICS.form_gap // 2, METRICS.form_gap // 2)))
        self._form_labels['filename'] = self._form_caption(self.selection_caption, self._selection_grid.cell(0, 0))
        self._folder_edit_control = self.line_edit_widget(
            self._current_path, parent=self._selection_grid.cell(0, 1),
            width=-1, on_enter=True, callback=lambda *_args: self._select_folder())
        self.folder_edit = self._folder_edit_control.tag
        self._folder_edit_control.setThemeProvider(self._selector_theme_provider('editor'))

    def _form_caption(self, text, parent):
        frame = QFrame(parent=parent, width=-1, height=METRICS.control_height,
                       frame_shape=QFrame.NoFrame, no_scrollbar=True, no_scroll_with_mouse=True)
        frame.setTheme(self._caption_theme)
        label = QLabel(text, parent=frame)
        label.move(0, max(0, (METRICS.control_height - self._font_metrics.height()) // 2))
        return label

    def _selector_theme_provider(self, kind):
        def theme(*, focused=False, disabled=False):
            key = (kind, bool(focused), bool(disabled))
            if key not in self._selector_themes:
                if kind in ('accept', 'cancel'):
                    result = browser_action_theme(default=kind == 'accept', focused=focused, disabled=disabled)
                else:
                    result = browser_file_editor_theme(
                        focused=focused, disabled=disabled, combo=kind == 'combo',
                        font_height=self._font_metrics.height())
                self._selector_themes[key] = result
            return self._selector_themes[key]
        return theme

    def _nav_button(self, parent, name, callback):
        return navigation_button(parent, name, callback,
                                 self._navigation_font, self._navigation_theme)

    def _refresh_search_focus(self):
        control = getattr(self, "_filter_edit_control", None)
        if control is None or not control.exists():
            return
        try:
            focused = bool(control.hasFocus() or control.isActive())
            self._search_shell_frame.setTheme(
                self._search_focus_theme if focused else self._search_normal_theme)
        except Exception:
            pass

    def _bind_search_focus(self):
        """Mirror QLineEdit focus-frame behavior without exposing item registries."""
        try:
            callback = lambda *_args: self._refresh_search_focus()
            self._search_focus_binding = (
                QItemInputBinding(self._filter_edit_control, parent=self)
                .onFocus(callback)
                .onActivated(callback)
                .onDeactivated(callback)
                .activate()
            )
        except Exception:
            self._search_focus_binding = None

    def _search_changed(self):
        query = self._filter_edit_control.text()
        control = getattr(self, "_clear_search_control", None)
        if control is not None and not getattr(control, "_deleted", False):
            control.setVisible(bool(query))
        self._filter_entries()

    def _clear_search(self):
        set_editor_text(self._filter_edit_control, "")
        control = getattr(self, "_clear_search_control", None)
        if control is not None and not getattr(control, "_deleted", False):
            control.hide()
        self._filter_entries()
        self.focus_editor(self.filter_edit)
        self.view.after(0, self._refresh_search_focus)

    def _place_section(self, title, texture=None):
        item = QTreeWidgetItem([str(title)])
        if texture:
            item.setIcon(0, texture)
        item.setExpanded(True)
        item.setContainerTheme(browser_sidebar_item_container_theme())
        item.setRowTheme(browser_sidebar_header_theme())
        self._places_tree.addTopLevelItem(item)
        return item

    def _refresh_place_button_aliases(self):
        """Keep historical native-tag aliases synchronized after tree rebuilds."""
        if not hasattr(self, "_places_tree"):
            return
        aliases = {}
        for path, (item, _is_drive) in tuple(self._place_items.items()):
            label = item.data(0, Qt.UserRole + 1) or item.text(0)
            native = self._places_tree.nativeItem(item)
            if native is not None:
                aliases[str(label)] = native
        self.place_buttons = aliases

    def _place_tree_clicked(self, item, _column=0):
        if item is None or item.childCount():
            return
        path = item.data(0, Qt.UserRole)
        if path:
            self._place_clicked(self._places_tree.nativeItem(item), True, path)

    @staticmethod
    def _text_width(text):
        try:
            measured = (self._font_metrics.horizontalAdvance(str(text or "")), self._font_metrics.height())
            if isinstance(measured, (tuple, list)) and measured:
                return float(measured[0] or 0.0)
        except Exception:
            pass
        return float(len(str(text or "")) * 7)

    def _sidebar_draw_text_y(self, sample="Ag"):
        """Pixel-position draw_text so sidebar labels share the icon coordinate system."""
        try:
            measured = (self._font_metrics.horizontalAdvance(str(sample or "Ag")), self._font_metrics.height())
            if isinstance(measured, (tuple, list)) and len(measured) >= 2:
                height = float(measured[1] or 0.0)
                if height > 0:
                    return max(0, int(round((METRICS.sidebar_row_height - height) * 0.5)))
        except Exception:
            pass
        return 4

    def _elide_sidebar_label(self, text, max_width=None):
        """QFontMetrics::elidedText-like right elision for the Places tree."""
        text = str(text or "")
        budget = float(max_width or (METRICS.sidebar_width - 36))
        if self._text_width(text) <= budget:
            return text
        ellipsis = "..."
        ellipsis_width = self._text_width(ellipsis)
        if budget <= ellipsis_width:
            return ellipsis
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            candidate = text[:mid] + ellipsis
            if self._text_width(candidate) <= budget:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo] + ellipsis

    def _set_place_label(self, item, text):
        if isinstance(item, QTreeWidgetItem):
            item.setText(0, self._elide_sidebar_label(text))

    def _add_place(self, label, path, texture, is_drive=False, parent=None):
        item = QTreeWidgetItem([self._elide_sidebar_label(label)])
        item.setData(0, Qt.UserRole, str(path))
        # Preserve the original caption independently from drive display-name
        # refreshes so the historical place_buttons alias remains stable.
        item.setData(0, Qt.UserRole + 1, str(label))
        item.setToolTip(0, str(path))
        if texture:
            item.setIcon(0, texture)
        item.setContainerTheme(browser_sidebar_item_container_theme())
        item.setRowTheme(browser_sidebar_row_theme())
        if isinstance(parent, QTreeWidgetItem):
            parent.addChild(item)
        else:
            self._places_tree.addTopLevelItem(item)
        self._place_items[str(path)] = (item, bool(is_drive))
        self._refresh_place_button_aliases()
        return item


    def _place_clicked(self, _sender, _app_data, path):
        """Queue sidebar navigation after the current pointer transaction.

        Dear ImGui keeps the clicked Selectable active until the current frame
        commits. Rebuilding the browser synchronously from this callback can
        leave the active item/mouse ownership stale, which makes the whole
        floating dialog appear unclickable after switching drives.
        """
        if not path:
            return
        self._pending_place_path = str(path)
        self._place_transaction = self._new_pointer_transaction()
        if self._place_navigation_scheduled:
            return
        self._place_navigation_scheduled = True
        # Yield first; the commit additionally verifies a real release/render
        # boundary, rather than assuming a timer implies a rendered frame.
        self.view.after(1, self._commit_place_navigation)

    def _commit_place_navigation(self):
        path = self._pending_place_path
        transaction = self._place_transaction
        if (not path or not self.winfo_exists() or transaction is None
                or transaction["generation"] != self._generation):
            self._place_navigation_scheduled = False
            self._pending_place_path = self._place_transaction = None
            return
        if not self._pointer_transaction_finished(transaction):
            self.view.after(16, self._commit_place_navigation)
            return
        self._place_navigation_scheduled = False
        self._pending_place_path = self._place_transaction = None
        self._navigate(path)

    def _new_pointer_transaction(self):
        return {"generation": self._generation, "frame": (QApplication.instance().frameCount() if QApplication.instance() is not None else 0), "release_frame": None}

    @staticmethod
    def _pointer_transaction_finished(transaction):
        frame = (QApplication.instance().frameCount() if QApplication.instance() is not None else 0)
        # When an owned native window receives the release, DearPyGui's button
        # cache may lag the physical state. Use Win32 for the actual release
        # boundary; keep the portable Qt facade for other renderers/platforms.
        buttons = QCursor.buttons()
        if os.name == "nt":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
                user32.GetAsyncKeyState.restype = ctypes.c_short
                buttons = (Qt.LeftButton if (user32.GetAsyncKeyState(0x01) & 0x8000) else Qt.NoButton)
                if user32.GetAsyncKeyState(0x02) & 0x8000:
                    buttons |= Qt.RightButton
                if user32.GetAsyncKeyState(0x04) & 0x8000:
                    buttons |= Qt.MiddleButton
            except Exception:
                pass
        if buttons != Qt.NoButton:
            transaction["release_frame"] = None
            return False
        # A millisecond delay does not imply a rendered frame. Let ImGui see
        # mouse-up before deleting its active row/sidebar item, even when many
        # callbacks are drained together or the renderer is temporarily slow.
        if transaction["release_frame"] is None:
            transaction["release_frame"] = frame
        return frame > max(transaction["frame"], transaction["release_frame"])

    def _queue_row_activation(self, key):
        if not self.winfo_exists() or key not in self.listbox.items:
            return
        self._pending_row_activation = (key, self._new_pointer_transaction(), self.listbox._row_generation)
        if not self._row_activation_scheduled:
            self._row_activation_scheduled = True
            self.view.after(1, self._commit_row_activation)

    def _commit_row_activation(self):
        pending = self._pending_row_activation
        if pending is None:
            self._row_activation_scheduled = False
            return
        key, transaction, row_generation = pending
        if (not self.winfo_exists() or transaction["generation"] != self._generation
                or row_generation != self.listbox._row_generation or key not in self.listbox.items
                or self.listbox.current != key):
            self._pending_row_activation = None
            self._row_activation_scheduled = False
            return
        if not self._pointer_transaction_finished(transaction):
            self.view.after(16, self._commit_row_activation)
            return
        self._pending_row_activation = None
        self._row_activation_scheduled = False
        self._enter_key(key)

    def _change_view(self, value):
        details = value == "Details"
        if self.listbox.details_mode == details:
            return
        self.listbox.details_mode = details
        if hasattr(self, "details_view_button"):
            self._details_tool_theme = browser_tool_button_theme(checked=details)
            self._list_tool_theme = browser_tool_button_theme(checked=not details)
            self._details_view_control.setTheme(self._details_tool_theme)
            self._list_view_control.setTheme(self._list_tool_theme)
        self._filter_entries()

    def _apply_layout(self):
        super()._apply_layout()
        if hasattr(self, "address") and self.winfo_exists():
            self.address.refresh()

    def _install_browser_keys(self):
        binding = QGlobalInputBinding(parent=self)
        for key in (Qt.Key_L, Qt.Key_F, Qt.Key_F4, Qt.Key_F5, Qt.Key_N,
                    Qt.Key_Left, Qt.Key_Right, Qt.Key_Up,
                    Qt.Key_Return, Qt.Key_Backspace, Qt.Key_F2):
            binding.onKeyPress(key, self._browser_key, user_data=key)
        binding.onMouseClick(Qt.LeftButton, self._rename_outside_click)
        binding.onMouseClick(Qt.LeftButton, self._folder_menu_outside_click)
        binding.onMouseRelease(Qt.RightButton, self._folder_right_release)
        self._browser_input_binding = binding.activate()

    def _browser_key(self, _sender, _app_data=None, key=None):
        if key is None:
            key = QGlobalInputBinding.qtKeyForNative(_app_data)
        if not self.winfo_exists() or not self.isVisible():
            return
        if self._folder_menu_is_open() or self._folder_menu_action_pending:
            return
        if self._rename_path is not None or self._rename_after_load is not None:
            if key == Qt.Key_Return and self._rename_path is not None:
                self.view.after(1, self._commit_folder_rename, self._rename_path,
                                self._rename_editor_control.text())
            return
        modifiers = QKeyboard.modifiers()
        ctrl = bool(modifiers & Qt.ControlModifier)
        shift = bool(modifiers & Qt.ShiftModifier)
        alt = bool(modifiers & Qt.AltModifier)
        if (key == Qt.Key_L and ctrl) or key == Qt.Key_F4:
            self.address.begin_edit()
        elif key == Qt.Key_F and ctrl:
            self._search_shell_frame.show()
            self.focus_editor(self.filter_edit)
            self.view.after(0, self._refresh_search_focus)
        elif key == Qt.Key_F5:
            self._refresh()
        elif key == Qt.Key_N and ctrl and shift:
            self._show_new_folder()
        elif key == Qt.Key_F2 and self._list_keyboard_active():
            self._request_folder_rename(self.listbox.currentData())
        elif key == Qt.Key_Left and alt:
            self._go_back()
        elif key == Qt.Key_Right and alt:
            self._go_forward()
        elif key == Qt.Key_Up and alt:
            self._go_up()
        elif key == Qt.Key_Return and self._list_keyboard_active():
            path = self.listbox.currentData()
            if path:
                self._enter_key(path)
        elif key == Qt.Key_Backspace and self._list_keyboard_active():
            if self._back_paths:
                self._go_back()
            else:
                self._go_up()

    def _list_keyboard_active(self):
        # Text editors own Return/Backspace.  Once a folder row has focus, the
        # view behaves like QFileDialog/QListView: arrows move current, Return
        # opens it, and Backspace navigates back/up.
        if self._rename_path is not None:
            return False
        for control in (getattr(self, "_path_edit_control", None),
                        getattr(self, "_folder_edit_control", None),
                        getattr(self, "_filter_edit_control", None)):
            if control is not None and control.exists() and (control.hasFocus() or control.isActive()):
                return False
        return bool(self.listbox.hasFocus() and self.listbox.currentData())

    def _set_status(self, message, *, error=False):
        """Update footer text with the same information/error hierarchy as Qt."""
        if not hasattr(self, "status"):
            return
        self.set_control_value(self.status, str(message or ""))
        theme = self._status_error_theme if error else self._status_normal_theme
        self.set_control_theme(self.status, theme)
        # Qt does not reserve a whole extra footer for an item-count label.
        # Keep status data available to accessibility/tests, showing only errors.
        self.set_control_visible(self.status, bool(error))
        reserve = self.selection_height + (20 if error else 0)
        if hasattr(self, '_selection_bar_frame'):
            self._selection_bar_frame._configure('height', reserve)
            self._workspace_frame._configure('height', -reserve)

    def _show_new_folder(self):
        if self._creating_folder:
            return
        if self._rename_path is not None and not self._commit_folder_rename():
            return
        self.address.end_edit()
        self._create_folder()

    def _hide_new_folder(self):
        self._rename_after_load = None
        self._rename_path = None
        editor, self._rename_editor = self._rename_editor, None
        editor_control, self._rename_editor_control = self._rename_editor_control, None
        source, self._rename_source = self._rename_source, None
        if editor is not None:
            self.enter_editors.discard(editor)
            if editor_control is not None and not getattr(editor_control, "_deleted", False):
                editor_control.delete()
            elif QRetainedItem(editor).exists():
                QRetainedItem(editor).deleteNative()
        if source is not None and QRetainedItem(source).exists():
            QRetainedItem(source).show()

    def _create_folder(self):
        if self._creating_folder:
            return
        parent = self._current_path
        self._creating_folder = True
        self._new_folder_control.setEnabled(False)
        self._set_status("Creating folder...")

        def worker():
            path, error = None, None
            try:
                path = str(FileSystemModel.new_folder(Path(parent)))
            except (OSError, ValueError) as exc:
                error = str(exc)
            return path, error
        self.runAsync(
            worker,
            on_result=lambda outcome: self._folder_created(
                parent, outcome[0], outcome[1]),
        )

    def _folder_created(self, parent, path, error):
        if not self.winfo_exists():
            return
        self._creating_folder = False
        self._new_folder_control.setEnabled(True)
        if parent != self._current_path:
            return
        if error:
            self._set_status("Could not create folder: {}".format(error), error=True)
            return
        self._hide_new_folder()
        set_editor_text(self._filter_edit_control, "")
        control = getattr(self, "_clear_search_control", None)
        if control is not None and not getattr(control, "_deleted", False):
            control.hide()
        self._select_after_load = path
        self._rename_after_load = path
        self._refresh()

    def _begin_folder_rename(self, path):
        if (not self.winfo_exists() or self._rename_after_load != path
                or path not in self.listbox.items):
            return
        tag = self.listbox.items[path]
        row_rect = QRetainedItem(tag).globalGeometry()
        y = row_rect.y()
        bounds = QRetainedItem(self.listbox.tag).globalGeometry(clipped=True)
        if bounds.isEmpty():
            self.view.after(20, self._begin_folder_rename, path)
            return
        top, right, bottom = bounds.top(), bounds.right(), bounds.bottom() + 1
        # Scroll the new row into view before positioning the shared editor.
        header = METRICS.header_height if self.listbox.details_mode else 0
        if y < top + header or y + METRICS.row_height > bottom:
            offset = y - top - header if y < top + header else y + METRICS.row_height - bottom
            self.listbox.scrollBy(dy=offset)
            self.view.after(20, self._begin_folder_rename, path)
            return
        name = os.path.basename(path)
        # A span-columns Selectable reports the full row rect, including the
        # icon. Use the icon slot to place the editor exactly over the label.
        icon_slot = QRetainedItem(self.listbox.icons[path]).parentItem()
        icon_rect = QRetainedItem(icon_slot).globalGeometry()
        x = icon_rect.right() + 1 + 4
        if self.listbox.details_mode:
            date_text = self.listbox.detail_texts[path][0]
            right = min(right, QRetainedItem(date_text).globalGeometry().left() - 6)
        max_width = max(24, int(right - x - 4))
        editor_width = min(max_width, max(120, int(self._font_metrics.horizontalAdvance(name) + 12)))
        self._rename_editor_control = QLineEdit(
            name, parent=QRetainedItem(tag).parentItem(), before=tag,
            width=editor_width, height=METRICS.row_height,
            auto_select_all=True, on_enter=True,
            callback=lambda _sender, value, _user_data=None: self.view.after(
                1, self._commit_folder_rename, path, value))
        self._rename_editor = self._rename_editor_control.tag
        if not hasattr(self, "_rename_editor_theme"):
            self._rename_editor_theme = browser_rename_editor_theme()
        self._rename_editor_control.setTheme(self._rename_editor_theme)
        self._rename_source = tag
        QRetainedItem(tag).hide()
        self._rename_after_load = None
        self._rename_path = path
        self.enter_editors.add(self._rename_editor)
        self._focus_folder_rename(path, retries=4)

    def _focus_folder_rename(self, path, retries=4):
        if self.winfo_exists() and self._rename_path == path:
            if self._rename_editor_control is not None and self._rename_editor_control.isActive():
                return
            # The toolbar/address field may still own its child window's focus.
            # Focus the list window before requesting its newly rendered input.
            self.listbox.setFocus()
            self._rename_editor_control.setFocus()
            if retries:
                self.view.after(16, self._focus_folder_rename, path, retries - 1)

    def _rename_outside_click(self, *_args):
        if self._rename_path is None:
            return
        if self._rename_editor_control is not None and not self._rename_editor_control.underMouse():
            self.view.after(1, self._commit_folder_rename, self._rename_path,
                            self._rename_editor_control.text())

    def _commit_folder_rename(self, path=None, new_name=None):
        current = self._rename_path
        if current is None or (path is not None and current != path):
            return False
        if new_name is None:
            new_name = self._rename_editor_control.text()
        try:
            renamed = str(FileSystemModel().rename(
                Path(current), str(new_name or "")))
        except (OSError, ValueError) as exc:
            self._set_status("Could not rename folder: {}".format(exc), error=True)
            self.view.after(20, self._focus_folder_rename, current)
            return False
        self._hide_new_folder()
        self._select_after_load = renamed
        set_editor_text(self._folder_edit_control, renamed)
        self._refresh()
        return True

    def invoke_default(self):
        # Enter belongs to the inline editor, not Select Folder.
        if (self._rename_path is None and self._rename_after_load is None
                and not self._folder_menu_is_open() and not self._folder_menu_action_pending):
            super().invoke_default()

    def _create_folder_context_menu(self):
        menu = QMenu([
            {"label": "Open", "action": "open"},
            {"label": self.context_selection_caption, "action": "select"},
            {"label": "Rename", "action": "rename", "shortcut": "F2"},
            {"label": "Copy path", "action": "copy_path"},
            {"label": "Open in File Explorer", "action": "explorer"},
            {"label": "---"},
            {"label": "New folder", "action": "new_folder", "shortcut": "Ctrl+Shift+N"},
            {"label": "Refresh", "action": "refresh", "shortcut": "F5"},
        ], after=self.view.after, parent_window=self.tag)
        menu.triggered.connect(self._folder_menu_triggered)
        menu.aboutToShow.connect(lambda *_args: setattr(self, "active_table", None))
        menu.aboutToHide.connect(lambda *_args: setattr(self, "active_table", self.listbox))
        self._folder_context_menu = menu

    def _folder_menu_is_open(self):
        menu = self._folder_context_menu
        return bool(menu is not None and menu.exists() and menu.isVisible())

    def _folder_menu_outside_click(self, *_args):
        if not self._folder_menu_is_open():
            return
        bounds = self._folder_context_menu.globalGeometry()
        if bounds.isEmpty():
            return
        point = QCursor.pos()
        if not bounds.contains(point):
            self.view.after(1, self._folder_context_menu.hide)

    def _folder_right_release(self, *_args):
        if not self.winfo_exists() or not self.isVisible():
            return
        point = QCursor.pos()
        position = tuple(point.toTuple())
        bounds = QRetainedItem(self.listbox.tag).globalGeometry(clipped=True)
        if bounds.isEmpty() or not bounds.contains(point):
            return
        if self._folder_menu_is_open():
            return
        path = None
        for key, tag in self.listbox.items.items():
            retained = QRetainedItem(tag)
            if not retained.isVisible():
                continue
            row_rect = retained.globalGeometry()
            if row_rect.top() <= point.y() < row_rect.bottom() + 1:
                path = key
                break
        # Freeze the target while processing this release. Popup mutation and
        # selection run after the physical gesture has finished.
        self.view.after(1, self._show_folder_context_menu,
                        path, position, self._current_path)

    def _show_folder_context_menu(self, path, position, parent):
        if not self.winfo_exists() or parent != self._current_path:
            return
        if self._rename_path is not None and not self._commit_folder_rename():
            return
        if path is not None and path not in self.listbox.items:
            return
        if path is not None:
            self.listbox.setCurrentKey(path, select=True)
        menu = self._folder_context_menu
        for action in ("open", "select", "rename", "copy_path", "explorer"):
            menu.setActionEnabled(action, path is not None)
        menu.setActionEnabled("new_folder", not self._creating_folder)
        menu.popup(position, context=(parent, path))

    def _folder_menu_triggered(self, action, context):
        # Menu signals may originate from a physical mouse-down callback. Hide
        # first and defer operations until its popup input transaction ends.
        self._folder_menu_action_pending = True
        self._folder_context_menu.hide()
        self.view.after(1, self._run_folder_menu_action, action, context)

    def _run_folder_menu_action(self, action, context):
        self._folder_menu_action_pending = False
        if not self.winfo_exists() or not context:
            return
        parent, path = context
        if parent != self._current_path or (path is not None and path not in self._entries):
            return
        if action == "new_folder":
            self._show_new_folder()
        elif action == "refresh":
            self._refresh()
        elif path is not None:
            if action == "open":
                self._enter_key(path)
            elif action == "select":
                self.finish(path)
            elif action == "rename":
                self._request_folder_rename(path)
            elif action == "copy_path":
                (QApplication.instance().clipboard().setText(path) if QApplication.instance() is not None else False)
            elif action == "explorer":
                try:
                    os.startfile(path)
                except OSError as exc:
                    self._set_status("Could not open folder: {}".format(exc), error=True)

    def _request_folder_rename(self, path):
        if path not in self.listbox.items:
            return
        self._hide_new_folder()
        self.listbox.setCurrentKey(path, select=True)
        self._rename_after_load = path
        self.view.after(1, self._begin_folder_rename, path)

    def _load_place_icons(self):
        def worker():
            result = []
            for path, items in tuple(self._place_items.items()):
                if self._finished:
                    break
                image, name = WindowsIconRegistry.read_path_info(path)
                result.append((path, items, image, name))
            return result

        def apply_icons(result):
            for path, items, image, name in result:
                if not self.winfo_exists():
                    break
                self._apply_place_icon(path, items, image, name)

        self.runAsync(worker, on_result=apply_icons)

    def _apply_place_icon(self, path, items, image, name):
        if not self.winfo_exists():
            return
        item, is_drive = items
        if image is not None:
            texture = WindowsIconRegistry.get_path_icon(path, image)
            item.setIcon(0, texture)
            list_icon = self.listbox.icons.get(path)
            if list_icon:
                QRetainedItem(list_icon).setTexture(texture)
            if os.path.normcase(path) == os.path.normcase(self._current_path):
                QRetainedItem(self.address_icon).setTexture(
                    address_location_texture(self._current_path, size=18))
        if is_drive and name:
            self._set_place_label(item, name)

    def _update_breadcrumbs(self):
        self.address.end_edit()

    def _sort_entries(self, specs):
        if not specs:
            return
        column, direction = specs[0]
        ascending = direction > 0
        if (column, ascending) != (self._sort_column, self._sort_ascending):
            self._sort_column, self._sort_ascending = column, ascending
            self._filter_entries()

    @staticmethod
    def _drives():
        if os.name == "nt":
            import ctypes
            mask = ctypes.windll.kernel32.GetLogicalDrives()
            return [chr(65 + index) + ":\\" for index in range(26) if mask & (1 << index)]
        return [os.path.abspath(os.sep)]

    def _update_navigation(self):
        back_enabled = bool(self._back_paths)
        forward_enabled = bool(self._forward_paths)
        up_enabled = os.path.dirname(self._current_path) != self._current_path
        QRetainedItem(self.back_button).configure(
            enabled=back_enabled, texture_tag=navigation_texture("Back") if back_enabled else navigation_disabled_texture("Back"))
        QRetainedItem(self.forward_button).configure(
            enabled=forward_enabled, texture_tag=navigation_texture("Forward") if forward_enabled else navigation_disabled_texture("Forward"))
        QRetainedItem(self.up_button).configure(
            enabled=up_enabled, texture_tag=navigation_texture("Up") if up_enabled else navigation_disabled_texture("Up"))
        current = os.path.normcase(self._current_path)
        parents = [path for path in self._place_items
                   if current == os.path.normcase(path) or
                   current.startswith(os.path.normcase(path).rstrip("\\/") + os.sep)]
        active = max(parents, key=len) if parents else None
        selected_item = self._place_items.get(active, (None, False))[0] if active else None
        self._places_tree.setCurrentItem(selected_item)

    def _navigate(self, value, remember=True):
        value = os.path.expandvars(os.path.expanduser(str(value).strip()))
        candidate = os.path.abspath(os.path.join(self._current_path, value))
        if not os.path.isdir(candidate):
            self._set_status("Folder does not exist: {}".format(candidate), error=True)
            self._update_navigation()
            return False
        if remember and candidate != self._current_path:
            self._back_paths.append(self._current_path)
            self._forward_paths.clear()
        self._current_path = candidate
        self._initial_location_pending = False
        self.set_control_enabled(self._accept_button, True)
        self._folder_context_menu.hide()
        self._select_after_load = None
        self._hide_new_folder()
        set_editor_text(self._path_edit_control, candidate)
        self.address._icon_view.setPixmap(address_location_texture(candidate, size=18))
        self._update_breadcrumbs()
        set_editor_text(self._folder_edit_control, candidate)
        set_editor_text(self._filter_edit_control, "")
        control = getattr(self, "_clear_search_control", None)
        if control is not None and not getattr(control, "_deleted", False):
            control.hide()
        self._entries.clear()
        self._listing = []
        self.listbox.empty_text = "Loading..."
        self.listbox.setItems([])
        self._update_navigation()
        self._refresh()
        return True

    def _go_back(self):
        if self._back_paths:
            previous = self._current_path
            if self._navigate(self._back_paths[-1], remember=False):
                self._back_paths.pop()
                self._forward_paths.append(previous)
                self._update_navigation()

    def _go_forward(self):
        if self._forward_paths:
            previous = self._current_path
            if self._navigate(self._forward_paths[-1], remember=False):
                self._forward_paths.pop()
                self._back_paths.append(previous)
                self._update_navigation()

    def _selection_changed(self, key):
        if hasattr(self, "folder_edit"):
            set_editor_text(self._folder_edit_control, self._entries.get(key, self._current_path))

    def _filter_entries(self):
        if self._rename_path is not None:
            self._hide_new_folder()
        query = self._filter_edit_control.text().casefold().strip()
        entries = [item for item in self._listing if query in item[1].casefold()]
        entries.sort(key=lambda item: (
            (self._folder_mtimes.get(item[2], 0), item[0], item[1])
            if self._sort_column == 1 else
            (self._entry_sizes.get(item[2], 0) or 0, item[0], item[1])
            if self._sort_column == 2 else (item[0], item[1])),
            reverse=not self._sort_ascending)
        self.listbox.details = self._folder_mtimes
        self.listbox.entry_types = getattr(self, "_entry_types", {})
        self.listbox.entry_sizes = self._entry_sizes
        self.listbox.sort_column, self.listbox.sort_ascending = self._sort_column, self._sort_ascending
        self.listbox.empty_text = "No folders match your search." if query else "This folder is empty."
        self.listbox.setItems([QtListItem(path, name, path) for _, name, path in entries])
        # Path editors and list rows own Enter (navigate/activate); do not
        # also run the dialog default action for that same physical keypress.
        self.enter_editors = {self.path_edit, self.folder_edit, self.filter_edit,
                              *self.listbox.items.values()}
        count = len(entries)
        self._set_status("{} folder{}".format(count, "" if count == 1 else "s"))

    @staticmethod
    def _normalize_initial(initial):
        # Lexical normalization only: isdir/stat on a disconnected share can
        # stall for seconds before the user has even seen the selector.
        value = str(initial or safe_current_directory())
        try:
            value = os.path.abspath(os.path.normpath(value))
        except Exception:
            value = str(safe_current_directory())
        return value

    def _resolve_initial_location(self, value):
        return (value if os.path.isdir(value) else str(safe_current_directory())), None

    def _apply_initial_filename(self, filename):
        set_editor_text(self._folder_edit_control, self._current_path)

    def _load_initial_contents(self):
        generation, requested = self._generation, self._current_path
        editor_text = self._folder_edit_control.text()

        def resolved(location):
            if (not self.winfo_exists() or generation != self._generation
                    or requested != self._current_path):
                return
            directory, filename = location
            self._current_path = directory
            self._initial_location_pending = False
            self.set_control_enabled(self._accept_button, True)
            # Do not erase something typed while the initial path was resolving.
            if self._path_edit_control.text() == requested:
                set_editor_text(self._path_edit_control, directory)
            if self._folder_edit_control.text() == editor_text:
                self._apply_initial_filename(filename)
            if not self.address.editing:
                self.address.refresh(force=True)
            self._update_navigation()
            self._refresh()

        self.runAsync(lambda: self._resolve_initial_location(requested), on_result=resolved,
                      on_error=lambda error: self._set_status(str(error), error=True))
        self._load_place_icons()

    def _navigate_typed(self):
        value = str(self._path_edit_control.text() or "").strip()
        if value:
            self._navigate(value)

    def _go_up(self):
        parent = os.path.dirname(self._current_path)
        if parent != self._current_path:
            self._navigate(parent)

    def _refresh(self):
        if not self.winfo_exists():
            return
        self._generation += 1
        generation = self._generation
        path = self._current_path
        self._set_status("Loading...")

        def worker():
            entries, error, modified, kinds, sizes = [], None, {}, {}, {}
            try:
                with os.scandir(path) as iterator:
                    for entry in iterator:
                        try:
                            is_dir = entry.is_dir(follow_symlinks=True)
                            if self._include_entry(entry, is_dir):
                                entries.append((entry.name.casefold(), entry.name, entry.path))
                                kinds[entry.path] = ("Folder" if is_dir else
                                    "{} File".format(Path(entry.name).suffix[1:].upper())
                                    if Path(entry.name).suffix else "File")
                                try:
                                    info = entry.stat(follow_symlinks=True)
                                    modified[entry.path] = info.st_mtime
                                    sizes[entry.path] = None if is_dir else info.st_size
                                except OSError:
                                    modified[entry.path] = 0
                        except OSError:
                            continue
                entries.sort(key=lambda item: (item[0], item[1]))
            except (OSError, ValueError) as exc:
                error = str(exc)
            return entries, error, modified, kinds, sizes

        self.runAsync(
            worker,
            on_result=lambda outcome: self._apply_entries(
                generation, path, outcome[0], outcome[1], outcome[2], outcome[3], outcome[4]),
        )

    def _include_entry(self, entry, is_dir):
        return is_dir

    def _apply_entries(self, generation, path, entries, error, modified=None, kinds=None, sizes=None):
        if not self.winfo_exists() or generation != self._generation:
            return
        if path != self._current_path:
            return
        if error:
            self._hide_new_folder()
            self._entries.clear()
            self._listing = []
            self.listbox.setItems([])
            self._set_status(error, error=True)
            return
        self._entries = {full_path: full_path for _, _, full_path in entries}
        self._folder_mtimes = modified or {}
        self._entry_types = kinds or {}
        self._entry_sizes = sizes or {}
        self._listing = entries
        self._filter_entries()
        if self._select_after_load in self.listbox.items:
            self.listbox.setCurrentKey(self._select_after_load, select=True)
        self._select_after_load = None
        if self._rename_after_load in self.listbox.items:
            self.view.after(20, self._begin_folder_rename, self._rename_after_load)

    def _enter_key(self, key):
        path = self._entries.get(key) or str(key or "")
        if path and os.path.isdir(path):
            self._navigate(path)

    def _select_folder(self):
        if self._rename_path is not None and not self._commit_folder_rename():
            return
        value = str(self._folder_edit_control.text() or "").strip()
        path = os.path.abspath(os.path.join(
            self._current_path, os.path.expandvars(os.path.expanduser(value))))
        if not os.path.isdir(path):
            self._set_status("Folder does not exist: {}".format(path), error=True)
            return
        self.finish(path)

    def finish(self, value):
        if self._finished:
            return
        self._finished = True
        self._hide_new_folder()
        self._folder_context_menu.delete()
        self._generation += 1
        try:
            if callable(self.on_result):
                self.on_result(value)
        finally:
            self.destroy()

    def destroy(self):
        self._hide_new_folder()
        if self._folder_context_menu is not None:
            self._folder_context_menu.delete()
        super().destroy()

    def _close_from_escape(self):
        if self._folder_menu_is_open():
            self._folder_context_menu.hide()
        elif self._rename_path is not None or self._rename_after_load is not None:
            self._hide_new_folder()
        elif self.address.editing:
            self.address.end_edit()
        else:
            self.finish(None)

    def _close_from_native(self):
        self.finish(None)
