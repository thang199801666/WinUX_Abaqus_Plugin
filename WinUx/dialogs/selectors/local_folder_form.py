from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from ...runtime.paths import safe_current_directory
from ...services.file_types import file_type_name

from DearUIQt.dialogs.qt_dialog import QtDialog
from .folder_browser_address import FolderAddressBar, set_editor_text
from .path_selection import PathSelectionOptions
from DearUIQt.modelview import (
    QtListItem, QtListView, QTreeWidget, QTreeWidgetItem,
    QTableWidget, QTableWidgetItem,
)
from DearUIQt.widgets import QLineEdit, QToolButton, QFrame, QSpacer, QLabel, QSeparator, QApplication, QImageView, QRetainedItem
from DearUIQt.layouts import QHBoxLayout, QVBoxLayout, QGridLayout
from DearUIQt.widgets import QMenu
from DearUIQt.gui import QtFusionPalette, QCursor, QKeyboard, QFontMetrics
from DearUIQt.core import Qt, QEvent, QMouseEvent, QItemInputBinding, QGlobalInputBinding
from DearUIQt import QGuiRuntime
from DearUIQt.tooltip import add_styled_tooltip
from ...models.filesystem import FileSystemModel
from ...platform.windows_icons import WindowsIconRegistry
from ...platform.folder_browser_places import quick_access_places, drive_stock_id
from .folder_browser_style import (
    METRICS, BrowserListPalette, browser_surface_theme, browser_dialog_body_theme,
    browser_layout_theme, browser_toolbar_theme, browser_workspace_theme,
    browser_field_shell_theme, browser_icon_slot_theme, browser_embedded_editor_theme,
    browser_sidebar_theme, browser_sidebar_row_theme, browser_sidebar_item_text_theme,
    browser_selected_text_theme, browser_name_item_theme,
    browser_file_editor_theme, browser_action_theme,
    browser_caption_theme,
    browser_row_cell_theme, browser_details_row_layout_theme, browser_rename_editor_theme,
    browser_sidebar_item_container_theme, browser_sidebar_header_theme,
    browser_list_viewport_theme,
    browser_details_theme, browser_list_mode_theme, browser_divider_theme, browser_selection_bar_theme,
    browser_empty_state_theme, browser_status_text_theme, browser_footer_theme,
    browser_sidebar_section_text_theme,
    browser_separator_theme, browser_toolbar_divider_theme, create_toolbar_divider,
    browser_tool_button_theme,
    browser_inline_icon_button_theme,
    navigation_button, navigation_button_theme,
    new_folder_texture, folder_item_texture, view_mode_texture, navigation_texture, navigation_disabled_texture,
    address_location_texture,
)


class FolderDetailsTable(QTableWidget):
    """Read-only cells with an Explorer-style centered Details header."""

    def setHorizontalHeaderLabels(self, labels):
        # Keep the native labels untouched.  The Details-header theme centers
        # every column title, so adding the historical Name-column icon inset
        # would make only that title visibly off-center.
        return super().setHorizontalHeaderLabels(list(labels))

    def _render_item(self, item):
        key = (item.row(), item.column())
        native = self._native_items.get(key)
        if native is not None:
            self.backend.configure_item(native, label=item.text())
            return
        native = self.backend.add_selectable(
            parent=self.nativeRow(item.row()), label=item.text(),
            width=0, height=METRICS.row_height - 2 * METRICS.table_cell_padding_y,
            enabled=bool(item.flags() & Qt.ItemIsEnabled))
        self._native_items[key] = native
        for column in range(item.column() + 1, self.columnCount()):
            before = self._native_items.get((item.row(), column))
            if before is not None:
                self.backend.move_item(native, before=before)
                break


class FolderListView(QtListView):
    """Keep shared selection/keyboard behavior with compact folder-icon rows."""

    def __init__(self, *args, on_sort=None, **kwargs):
        self.details = {}
        self.entry_types = {}
        self.entry_is_dirs = {}
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
        self.view_mode_name = "Details"
        self.details_mode = True
        self.on_sort = on_sort
        self._last_click_key = None
        self._last_click_at = 0.0
        self._double_click_interval = self._system_double_click_interval()
        self._visual_hit_bindings = []
        self._visual_hit_registries = self._visual_hit_bindings  # compatibility alias
        self._row_pointer_binding = None
        self._qt_pointer_registered = False
        self._row_pointer_registry = None
        self._row_generation = 0
        self._selection_revision = 0
        self._scroll_restore_revision = 0
        self._details_table = None
        self._details_header_row = None
        self._details_header_cells = []
        self._details_header_widths = ()
        self._details_header_separators = []
        self._empty_state_frame = None
        self._last_click_frame = None
        self._qt_bridge_click = None
        self._routed_pointer_key = None
        self._hovered_row_key = None
        self._name_column_width = None
        self._visual_positions = {}
        self._visual_keys = {}
        self._visual_cells = {}
        self._list_flow_rows = 0
        self._list_flow_columns = 0
        self._rendered_details_mode = None
        self._rendered_view_mode = None
        self._list_reflow_pending = False
        self._list_reflow_serial = 0
        super().__init__(*args, **kwargs)
        self.currentChanged.connect(self._selection_state_changed)
        self.selectionChanged.connect(self._selection_state_changed)
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

    VIEW_MODES = (
        "Extra large icons", "Large icons", "Medium icons", "Small icons",
        "List", "Details", "Tiles", "Content",
    )

    _VIEW_GEOMETRY = {
        "Extra large icons": dict(cell_width=210, row_height=156, icon_size=112, flow="grid", scroll_x=False),
        "Large icons": dict(cell_width=176, row_height=126, icon_size=88, flow="grid", scroll_x=False),
        "Medium icons": dict(cell_width=146, row_height=94, icon_size=56, flow="grid", scroll_x=False),
        "Small icons": dict(cell_width=190, row_height=32, icon_size=16, flow="grid", scroll_x=False),
        "List": dict(cell_width=METRICS.list_item_width, row_height=METRICS.list_row_height, icon_size=16, flow="columns", scroll_x=True),
        "Tiles": dict(cell_width=286, row_height=66, icon_size=48, flow="grid", scroll_x=False),
        "Content": dict(cell_width=520, row_height=72, icon_size=48, flow="content", scroll_x=False),
    }

    def setViewMode(self, mode):
        mode = str(mode or "Details").strip()
        if mode not in self.VIEW_MODES:
            mode = "Details"
        self.view_mode_name = mode
        self.details_mode = mode == "Details"
        return self

    def viewMode(self):
        return self.view_mode_name

    def _mode_geometry(self):
        if self.details_mode:
            return dict(cell_width=0, row_height=METRICS.row_height,
                        icon_size=METRICS.list_icon_size, flow="details", scroll_x=False)
        return dict(self._VIEW_GEOMETRY.get(
            getattr(self, "view_mode_name", "List"), self._VIEW_GEOMETRY["List"]))

    def _mode_flow_shape(self, count=None):
        count = len(self._values) if count is None else max(0, int(count))
        if count <= 0:
            return 1, 1
        geometry = self._mode_geometry()
        flow = geometry["flow"]
        if flow == "columns":
            return self._list_flow_shape(count)
        if flow == "content":
            return count, 1
        try:
            bounds = self.globalGeometry(clipped=True)
            width = int(bounds.width())
        except Exception:
            width = 0
        if width <= 0:
            columns = 4 if self.view_mode_name in ("Small icons", "Medium icons") else 3
        else:
            columns = max(1, width // max(1, int(geometry["cell_width"])))
        rows = max(1, (count + columns - 1) // columns)
        return rows, columns

    def _mode_name_width(self):
        if self.details_mode:
            return 1
        geometry = self._mode_geometry()
        return max(32, int(geometry["cell_width"]) - int(geometry["icon_size"]) - 18)

    def _paint_row_background(self, key):
        table = self._details_table
        if table is None or getattr(table, "_deleted", False):
            return
        details_mode = bool(getattr(self, "details_mode", True))
        hovered = key == self._hovered_row_key
        selected = key in self.selected
        enabled = self._row_enabled.get(key, True)
        if selected and self._has_focus:
            color = (BrowserListPalette.SELECTED_HOVER
                     if hovered and enabled else BrowserListPalette.SELECTED)
        elif selected:
            color = (BrowserListPalette.INACTIVE_HOVER
                     if hovered and enabled else BrowserListPalette.INACTIVE)
        elif hovered and enabled:
            color = BrowserListPalette.HOVER
        else:
            if details_mode:
                index = self._row_index.get(key)
                if index is not None:
                    self.backend.unhighlight_table_row(
                        table.tag, index + int(getattr(self, "_details_header_row", None) is not None))
            else:
                position = self._visual_positions.get(key)
                if position is not None:
                    self.backend.unhighlight_table_cell(table.tag, *position)
            return
        if details_mode:
            index = self._row_index.get(key)
            if index is not None:
                # Logical data indices exclude the custom frozen header;
                # native table painting counts it as row zero.
                native_index = index + int(getattr(self, "_details_header_row", None) is not None)
                self.backend.highlight_table_row(table.tag, native_index, color)
        else:
            position = self._visual_positions.get(key)
            if position is not None:
                self.backend.highlight_table_cell(table.tag, *position, color)

    def _refresh_row_hover(self, *_args, point=None):
        if self._deleted or self._details_table is None:
            return
        self._fit_name_column()
        self._sync_details_header_geometry()
        application = QApplication.instance()
        key = None
        if application is None or application.activePopupWidget() is None:
            try:
                point = QCursor.pos(backend=self.backend) if point is None else point
                x, y = (point.x(), point.y()) if hasattr(point, "x") else point
                key = self._table_row_key_at(x, y)
            except Exception:
                pass
        previous = self._hovered_row_key
        if key == previous:
            return
        self._hovered_row_key = key
        for dirty_key in (previous, key):
            if dirty_key is not None:
                self._paint_row_background(dirty_key)

    @staticmethod
    def _list_name_width():
        """Return the usable filename width inside one Explorer List cell.

        List mode must know this width *before* the native Selectable is moved
        into the table cell.  Creating it at 1 px and widening it later works
        on some backends, but the Windows Dear ImGui renderer can retain the
        original clipping width after reparenting, leaving only a few pixels of
        the filename visible.
        """
        return max(
            32,
            METRICS.list_item_width
            - (METRICS.list_icon_size + 2)
            - METRICS.name_icon_gap
            - (2 * METRICS.list_cell_padding_x)
            - 4,
        )

    def _initial_name_width(self):
        """Width assigned while the native filename item is first parented."""
        # Details has the same cold-layout clipping hazard as List mode. Never
        # parent its filename Selectable at 1 px and hope a later resize repairs
        # the native clip rectangle. The first rendered header refines this hint.
        return 160 if self.details_mode else self._mode_name_width()

    def _fit_name_column(self):
        """Keep long names inside Name, including after native header resizing."""
        if not self._values:
            return
        if not self.details_mode:
            width = self._mode_name_width()
            if width == self._name_column_width:
                return
            self._name_column_width = width
            metrics = QFontMetrics(backend=self.backend)
            available = max(1, width - 2 * METRICS.name_text_inset)
            for item in self._values:
                label = item.text
                if metrics.horizontalAdvance(label) > available:
                    lo, hi = 0, len(label)
                    while lo < hi:
                        mid = (lo + hi + 1) // 2
                        if metrics.horizontalAdvance(label[:mid] + "…") <= available:
                            lo = mid
                        else:
                            hi = mid - 1
                    label = label[:lo] + "…"
                self.backend.configure_item(self.items[item.key], width=width, label=label)
            return
        try:
            first = self._values[0].key
            left = float(self.backend.get_item_rect_min(self.items[first])[0])
            header = self._details_header_cells[0]
            header_left = float(self.backend.get_item_rect_min(header)[0])
            header_width, header_height = self.backend.get_item_rect_size(header)
            right = header_left + float(header_width)
            # During cold construction/reflow DPG can expose zero or mixed-frame
            # item rectangles without raising. Do not turn those into a 1 px
            # width and replace every filename with an ellipsis.
            if (header_width <= 0 or header_height <= 0 or
                    self.backend.get_item_rect_size(self.items[first])[1] <= 0 or
                    not header_left <= left < right):
                return
            width = max(1, int(right - left - METRICS.details_cell_padding_x))
        except Exception:
            return  # Wait until the new table has had its first layout pass.
        if width == self._name_column_width:
            return
        self._name_column_width = width
        metrics = QFontMetrics(backend=self.backend)
        available = max(1, width - 2 * METRICS.name_text_inset)
        for item in self._values:
            label = item.text
            if metrics.horizontalAdvance(label) > available:
                lo, hi = 0, len(label)
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if metrics.horizontalAdvance(label[:mid] + "…") <= available:
                        lo = mid
                    else:
                        hi = mid - 1
                label = label[:lo] + "…"
            self.backend.configure_item(self.items[item.key], width=width, label=label)

    def _list_flow_shape(self, count=None):
        """Return Explorer List-view ``(rows, columns)`` for the viewport.

        Native Explorer fills a compact column top-to-bottom before starting
        the next column.  Basing the row count on the visible viewport keeps
        the mode visually stable while allowing horizontal scrolling when the
        directory contains many items.
        """
        count = len(self._values) if count is None else max(0, int(count))
        if count <= 0:
            return 1, 1
        try:
            height = int(self.globalGeometry(clipped=True).height())
        except Exception:
            height = 0
        # Hidden/construction-time views can briefly report zero geometry.
        # Twelve rows is close to a normal Open dialog and is replaced by the
        # actual viewport height on the next mode rebuild.
        if height <= 0:
            rows = min(count, 12)
        else:
            usable = max(METRICS.list_row_height, height - 2)
            rows = max(1, min(count, usable // METRICS.list_row_height))
        columns = max(1, (count + rows - 1) // rows)
        return int(rows), int(columns)

    def requestListReflow(self):
        """Debounce List-mode column flow while the dialog is being resized."""
        if (self._deleted or self.details_mode or not self._values
                or self._after is None):
            return
        self._list_reflow_serial += 1
        if self._list_reflow_pending:
            return
        self._list_reflow_pending = True
        serial = self._list_reflow_serial

        def commit(expected_serial):
            if self._deleted or self.details_mode:
                self._list_reflow_pending = False
                return
            if expected_serial != self._list_reflow_serial:
                # Resize is still active. Wait until one quiet interval so the
                # table is not reconstructed continuously under the pointer.
                self._after(60, commit, self._list_reflow_serial)
                return
            self._list_reflow_pending = False
            desired = self._mode_flow_shape()
            if desired == (self._list_flow_rows, self._list_flow_columns):
                return
            values = list(self._values)
            # setItems preserves current/selection by stable key. Re-selecting
            # current here collapses multi-selection and focuses an offscreen
            # native row, making a resize/reflow jump back to it.
            self.setItems(values)

        self._after(60, commit, serial)

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
        item = self.itemForKey(key)
        if item is None or not item.enabled:
            return
        def restore_native_value():
            # Selectable mutates its native bool before queuing its callback.
            # Rejecting a stale notification must also undo that stray paint,
            # not leave row zero visually selected alongside the correct row.
            try:
                self.backend.set_value(sender, key in self.selected)
            except Exception:
                pass
        if (getattr(self, "_details_table", None) is not None
                and getattr(self, "_routed_pointer_key", None) != key):
            # Only the hit-tested mouse-down router may change table selection.
            # Selectable/cell callbacks can precede that router, or arrive after
            # a new press cleared its bridge. In that gap a reused native nav
            # target (often row zero) used to overwrite current and emit a
            # filename change. Cursor/held-key checks cannot identify the press
            # that originally queued a callback. Keyboard navigation/activation
            # is already handled by the dialog's retained key event path.
            restore_native_value()
            return
        frame = self._input_frame()
        if self._last_click_frame == (sender, frame):
            restore_native_value()
            return  # visual-cell + selectable notifications from one press
        keyboard_activation = False
        try:
            keyboard_activation = any(
                self.backend.is_key_down(getattr(self.backend, name))
                for name in ("mvKey_Spacebar", "mvKey_Return")
                if getattr(self.backend, name, None) is not None)
        except Exception:
            pass
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
            if not keyboard_activation:
                restore_native_value()
                return
            self._qt_bridge_click = None
        if (not keyboard_activation and getattr(self, "_routed_pointer_key", None) != key
                and getattr(self, "_details_table", None) is not None):
            # Reused native windows can enqueue a Selectable notification for
            # their old navigation item (often row zero). A pointer callback is
            # valid only at the row currently under the real cursor. Qt's
            # captured press path is explicitly marked and need not re-query a
            # cursor that may already have moved before callbacks are drained.
            try:
                point = QCursor.pos(backend=self.backend)
                if self._table_row_key_at(point.x(), point.y()) != key:
                    restore_native_value()
                    return
            except Exception:
                restore_native_value()
                return
        # Cell/native callbacks can precede the authoritative mouse-down route.
        # They may select, but must never start/advance double-click history.
        count_press = (getattr(self, "_routed_pointer_key", None) == key
                       or getattr(self, "_details_table", None) is None)
        if count_press:
            self._last_click_frame = (sender, frame)
        # Dear PyGui's native double-click flag is not reliable on every
        # Windows/DPG build when callbacks are manually pumped by a floating
        # dialog process.  Keep the shared QtListView behavior, then provide a
        # QFileDialog-style second-click fallback for the same folder row.
        now = time.monotonic()
        repeated = (
            count_press and key == self._last_click_key
            and 0.0 <= now - self._last_click_at <= self._double_click_interval
            and not (QKeyboard.modifiers(backend=self.backend)
                     & (Qt.ControlModifier | Qt.ShiftModifier))
        )
        super()._clicked(sender, value, key)
        if repeated:
            self._last_click_key = None
            self._last_click_at = 0.0
            self.doubleClicked.emit(key)
            self.activated.emit(key)
            return
        if count_press:
            self._last_click_key = key
            self._last_click_at = now

    def _is_double_click(self, key=None):
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
        if getattr(self, "_details_table", None) is not None:
            # The single mouse-down router already hit-tests complete rows in
            # every mode. These per-cell release handlers are rejected by
            # _clicked anyway; thousands of them only bloat the callback queue.
            return
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
            application = QApplication.instance()
            if application is not None:
                application.registerPointerTarget(self)
                self._qt_pointer_registered = True
            binding = QGlobalInputBinding(backend=self.backend, parent=self)
            if not self._qt_pointer_registered:
                binding.onMouseClick(Qt.LeftButton, self._row_pointer_clicked)
            self._row_pointer_binding = binding.onMouseWheel(self._row_pointer_wheel).activate()
        except Exception:
            self._row_pointer_binding = None

    def hitTest(self, point):
        return (not self._deleted and self.isVisible() and self.isEnabled()
                and self._details_table is not None and self._point_in_view(point))

    def event(self, event):
        # Standalone/floating hosts without a modal also use QApplication's
        # single press route. A second global click callback must not replay
        # that press at a later cursor/scroll position and select another row.
        if (event.type() == QEvent.MouseButtonPress and isinstance(event, QMouseEvent)
                and event.button() == Qt.LeftButton):
            self._qt_bridge_click = None
            if self._row_pointer_clicked(point=event.globalPosition()):
                event.accept()
                return True
        return super().event(event)

    def _cancel_scroll_restore(self):
        self._scroll_restore_revision = getattr(self, "_scroll_restore_revision", 0) + 1

    def _selection_state_changed(self, *_args):
        self._selection_revision += 1
        self._cancel_scroll_restore()

    def _row_pointer_wheel(self, *_args):
        if self._deleted:
            return
        try:
            point = QCursor.pos(backend=self.backend)
            if self.globalGeometry(clipped=True).contains(point):
                owner = self.window()
                if hasattr(owner, '_initial_pointer_activity'):
                    owner._initial_pointer_activity = True
                    owner._pointer_interaction_serial = getattr(owner, '_pointer_interaction_serial', 0) + 1
                self._cancel_scroll_restore()
                self._last_click_key = None
        except Exception:
            pass

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
        self._qt_bridge_click = (key, self._input_frame(), time.monotonic())

    def _input_frame(self):
        """Standalone hosts may have a renderer but no QApplication instance."""
        application = QApplication.instance()
        if application is not None:
            return application.frameCount()
        try:
            return int(self.backend.get_frame_count())
        except (AttributeError, TypeError, ValueError):
            return 0

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
        # Qt, the global mouse handler and cell callbacks can report the SAME
        # press in different frames. Only the press entry points may clear this
        # bridge. Clearing it here turned a single click into a double click.
        if getattr(self, "_qt_bridge_click", None) is not None:
            return True
        self._routed_pointer_key = key
        try:
            # Native callbacks are suppressed by the press bridge, so this
            # authoritative route must supply Ctrl-toggle state itself.
            selected = not (key in self.selected and
                            QKeyboard.hasModifier(Qt.ControlModifier, backend=self.backend))
            self._clicked(target, selected, key)
        finally:
            self._routed_pointer_key = None
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
        self._cancel_scroll_restore()
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

    def horizontalScrollValue(self):
        """Return the horizontal scroll of the embedded table in List mode."""
        self._reset_host_scroll()
        table = getattr(self, "_details_table", None)
        if table is not None and not getattr(table, "_deleted", False):
            try:
                return float(self.backend.get_x_scroll(table.tag))
            except Exception:
                pass
        return super().horizontalScrollValue()

    def setHorizontalScrollValue(self, value):
        self._cancel_scroll_restore()
        value = max(0.0, float(value))
        self._reset_host_scroll()
        table = getattr(self, "_details_table", None)
        if table is not None and not getattr(table, "_deleted", False):
            try:
                self.backend.set_x_scroll(table.tag, value)
                return self
            except Exception:
                pass
        return self

    def _restore_table_scroll(self, table_tag, value, generation, revision=None):
        """Restore table scroll without ever reviving the outer host scroll."""
        if self._deleted or generation != self._row_generation:
            return
        if revision is not None and revision != self._scroll_restore_revision:
            return
        self._reset_host_scroll()
        table = getattr(self, "_details_table", None)
        if table is None or getattr(table, "_deleted", False) or table.tag != table_tag:
            return
        try:
            current = float(self.backend.get_y_scroll(table_tag))
            if abs(current) > 0.5:
                # A nonzero live offset belongs to the user/native renderer,
                # even if it differs from this older rebuild snapshot.
                return
            self.backend.set_y_scroll(table_tag, max(0.0, float(value)))
        except Exception:
            pass

    def _restore_table_horizontal_scroll(self, table_tag, value, generation, revision=None):
        if self._deleted or generation != self._row_generation:
            return
        if revision is not None and revision != self._scroll_restore_revision:
            return
        self._reset_host_scroll()
        table = getattr(self, "_details_table", None)
        if table is None or getattr(table, "_deleted", False) or table.tag != table_tag:
            return
        try:
            if abs(float(self.backend.get_x_scroll(table_tag))) > 0.5:
                return
            self.backend.set_x_scroll(table_tag, max(0.0, float(value)))
        except Exception:
            pass

    def _list_key_at(self, x, y, bounds):
        """Hit-test one compact Explorer List cell without scanning the folder."""
        table = getattr(self, "_details_table", None)
        if (table is None or getattr(table, "_deleted", False)
                or not self._visual_positions or not self._visual_cells):
            return None
        backend = self.backend
        try:
            geometry = self._mode_geometry()
            if (backend.get_x_scroll_max(table.tag) > 0
                    and float(y) >= float(bounds.bottom()) - METRICS.scrollbar_width):
                return None
            scroll_x = max(0.0, float(backend.get_x_scroll(table.tag)))
            if geometry["flow"] == "columns":
                visible_column = max(0, min(self._list_flow_columns - 1,
                    int(scroll_x // max(1, int(geometry["cell_width"])))))
            else:
                visible_column = 0
            first_key = self._visual_key_at(0, visible_column)
            if first_key is None:
                return None
            first_cell = self._visual_cells[first_key]
            first_rect = first_cell.globalGeometry(clipped=False)
            first_top = float(first_rect.top())
            pitch = float(geometry["row_height"])
            row = int((float(y) - first_top) // max(1.0, pitch))
            if not 0 <= row < self._list_flow_rows:
                return None
            column = visible_column + int(
                (float(x) - float(first_rect.left()))
                // max(1, int(geometry["cell_width"])))
            # DPG's cell padding can move the first fixed column by a few
            # pixels. Probe the estimated cell and its immediate neighbours,
            # keeping hit testing O(1) even for folders with thousands of files.
            for candidate_column in (column, column - 1, column + 1):
                key = self._visual_key_at(row, candidate_column)
                if key is None:
                    continue
                cell = self._visual_cells.get(key)
                if cell is None or not cell.exists():
                    continue
                rect = cell.globalGeometry(clipped=True)
                if not rect.isEmpty() and rect.contains((int(x), int(y))):
                    return key
        except Exception:
            return None
        return None

    def _visual_key_at(self, row, column):
        row, column = int(row), int(column)
        if row < 0 or column < 0:
            return None
        return self._visual_keys.get((row, column))

    def _table_row_key_at(self, x, y):
        """Hit-test submitted item rectangles, not geometry-less table rows.

        mvTableRow has no rect_min/rect_size on the native renderer. The Name
        Selectable does, including its current scroll translation. Its Y bounds
        cover the entire logical row, independent of the clicked column.
        """
        table = getattr(self, "_details_table", None)
        if table is None or getattr(table, "_deleted", False) or not self._values:
            return None
        backend = self.backend
        try:
            # mvTable itself also omits rectangle state. Its fixed child-window
            # host is the actual clipping surface and does expose geometry.
            bounds = self.globalGeometry(clipped=True)
            table_left, table_top = float(bounds.x()), float(bounds.y())
            table_width, table_height = float(bounds.width()), float(bounds.height())
            if table_width <= 0 or table_height <= 0:
                return None
            if not (table_left <= float(x) < table_left + table_width
                    and table_top <= float(y) < table_top + table_height):
                return None
            if not self.details_mode:
                return self._list_key_at(x, y, bounds)
            # The scrollbar is not row content, even when its Y overlaps a row.
            if (backend.get_y_scroll_max(table.tag) > 0
                    and float(x) >= table_left + table_width - METRICS.scrollbar_width):
                return None
            if self.details_mode:
                first = backend.get_item_state(self.items[self._values[0].key])
                body_top = (float(first["rect_min"][1]) - METRICS.table_cell_padding_y
                            + float(backend.get_y_scroll(table.tag)))
                if y < max(table_top, body_top):
                    return None  # frozen header, even when a scrolled row lies underneath
        except Exception:
            return None
        lo, hi = 0, len(self._values) - 1
        while lo <= hi:
            row_index = (lo + hi) // 2
            key = self._values[row_index].key
            try:
                state = backend.get_item_state(self.items[key])
                top = float(state["rect_min"][1]) - METRICS.table_cell_padding_y
                height = float(state["rect_size"][1]) + 2 * METRICS.table_cell_padding_y
            except Exception:
                return None
            if height <= 0:
                return None
            if y < top:
                hi = row_index - 1
            elif y >= top + height:
                lo = row_index + 1
            else:
                return key if state.get("visible", False) else None
        return None

    def _row_pointer_clicked(self, *_args, point=None):
        if self._deleted or not self.items:
            return
        if point is None and getattr(self, "_qt_pointer_registered", False):
            return False  # Never replay an unpositioned legacy/global press.
        self._reset_host_scroll()
        # The global DPG click router must not select a row behind a combo,
        # context menu or another popup. QApplication's modal dialog itself
        # is not a popup, and is intentionally excluded from this gate.
        application = QApplication.instance()
        if application is not None and application.activePopupWidget() is not None:
            return
        bridge = getattr(self, "_qt_bridge_click", None)
        if point is None and bridge is not None and bridge[1] == self._input_frame():
            return False  # Native recovery already handled this render turn.
        if point is None and application is not None and application.activeModalWidget() is not None:
            # A modal dialog owns mouse-down through event(). Do not race it
            # with a second global route, regardless of callback ordering.
            return False
        if point is None and (application is None or application.activeModalWidget() is None):
            # In a non-modal/standalone view the global mouse-down handler is
            # the primary press source. Modal dialogs begin presses in event().
            self._qt_bridge_click = None
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

        self._cancel_scroll_restore()
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
        application = QApplication.instance()
        if application is not None and self._qt_pointer_registered:
            application.unregisterPointerTarget(self)
            self._qt_pointer_registered = False
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

    def _details_header_label(self, view_column, label, width=None):
        """Center the title while keeping the sort glyph near the right divider.

        Header cells are native Dear ImGui buttons (and therefore cannot host
        separately aligned children).  Use measured space advances, rather
        than a fixed number of spaces, to place the two parts independently.
        Recompute whenever native column geometry changes.
        """
        title = str(label)
        sort_key = {0: 0, 1: 2, 3: 1}.get(int(view_column))
        if sort_key is None or self.sort_column != sort_key:
            return title
        glyph = "▲" if self.sort_ascending else "▼"
        if width is None or width < 54:
            return title + "  " + glyph
        metrics = QFontMetrics(backend=self.backend)
        space = max(1.0, float(metrics.horizontalAdvance(" ")))
        title_width = float(metrics.horizontalAdvance(title))
        glyph_width = float(metrics.horizontalAdvance(glyph))
        # Two-sided 8 px inset and the centered-button alignment make the
        # leading pad essential: without it the title moves left with the glyph.
        inset = 9.0
        leading = max(0, round(((width - title_width) / 2 - inset) / space))
        middle = max(1, round(((width - title_width) / 2 - inset - glyph_width) / space))
        # Avoid clipping when the column is narrowed below its nominal size.
        while leading + middle > 1 and (leading + middle) * space + title_width + glyph_width > width - 2 * inset:
            if middle > 1:
                middle -= 1
            else:
                leading -= 1
        return " " * leading + title + " " * middle + glyph

    def _refresh_details_header_labels(self):
        labels = ("Name", "Size", "Type", "Date modified")
        buttons = getattr(self, "_details_header_cells", ())
        for column, button in enumerate(buttons):
            try:
                width = float(self.backend.get_item_rect_size(button)[0])
            except Exception:
                width = None
            try:
                self.backend.configure_item(
                    button, label=self._details_header_label(column, labels[column], width))
            except Exception:
                pass

    def _sync_details_header_geometry(self):
        """Refresh right-edge indicators when Explorer columns are resized."""
        buttons = getattr(self, "_details_header_cells", ())
        if not self.details_mode or not buttons:
            return
        try:
            widths = tuple(round(float(self.backend.get_item_rect_size(b)[0])) for b in buttons)
        except Exception:
            return
        if widths != self._details_header_widths:
            self._details_header_widths = widths
            self._refresh_details_header_labels()

    def _details_header_clicked(self, view_column):
        """Sort from the custom centered header while preserving Explorer semantics."""
        sort_key = {0: 0, 1: 2, 3: 1}.get(int(view_column))
        if sort_key is None or self.on_sort is None:
            return
        ascending = True if self.sort_column != sort_key else not self.sort_ascending
        # The sort callback rebuilds the Details table (including its header).
        # Do not first rewrite the old button labels: doing so produces a
        # transient text re-layout/flicker immediately before that table dies.
        # The rebuilt header reads the new sort state from _filter_entries().
        self.sort_column, self.sort_ascending = sort_key, ascending
        self.on_sort([(sort_key, 1 if ascending else -1)])

    def _install_centered_details_header(self, table, labels):
        """Install a real full-width button row as the Details header.

        Dear ImGui's native table headings are hard-left aligned.  WinUx's job
        tables already solve that limitation by rendering one frozen button per
        column.  Reuse the same rendering primitive here so every title remains
        mathematically centered as columns resize, without padding labels with
        spaces or breaking DPI scaling.
        """
        labels = [str(label) for label in labels]
        self.backend.configure_item(table.tag, header_row=False)
        self._details_header_separators = []
        with self.backend.table_row(parent=table.tag) as header:
            cells = []
            for column, label in enumerate(labels):
                has_separator = column < len(labels) - 1
                # Keep each rule INSIDE the scrolling table's cell. A drawlist
                # on the outer list host is painted behind the table's child
                # window, regardless of its order among the host's children.
                with self.backend.group(horizontal=True, horizontal_spacing=0):
                    cells.append(self.backend.add_button(
                        label=self._details_header_label(column, label),
                        width=-1, height=METRICS.header_height,
                        callback=(lambda _s, _a, user_data:
                                  self._details_header_clicked(user_data)),
                        user_data=column, enabled=True))
                    if has_separator:
                        # Buttons end at the content edge, one cell-padding
                        # inset from the real resize boundary. Extend into that
                        # padding, placing the 1 px rule just inside the column
                        # clip edge without shortening/off-centering the title.
                        inset = METRICS.details_cell_padding_x
                        line = self.backend.add_drawlist(
                            width=inset + 2, height=METRICS.header_height)
                        self.backend.draw_line(
                            (inset, 3), (inset, METRICS.header_height - 3),
                            parent=line, color=BrowserListPalette.HEADER_BORDER,
                            thickness=1.0)
                        self._details_header_separators.append(line)
        first_data_row = table.nativeRow(0)
        if first_data_row is not None:
            try:
                self.backend.move_item(header, before=first_data_row)
            except Exception:
                pass
        # Paint the *cells*, not just the button content rectangles.  Dear
        # ImGui applies table CellPadding outside a button; when each button
        # carried its own background those padded strips remained white and
        # the header looked like four separated controls.  Cell highlights
        # cover the complete column rect, producing the continuous Explorer /
        # WinUx table-header band used elsewhere in the application.
        try:
            for column in range(len(labels)):
                self.backend.highlight_table_cell(
                    table.tag, 0, column, BrowserListPalette.HEADER_BACKGROUND)
        except Exception:
            try:
                self.backend.highlight_table_row(
                    table.tag, 0, BrowserListPalette.HEADER_BACKGROUND)
            except Exception:
                pass
        self._details_header_row = header
        self._details_header_cells = cells
        self._details_header_widths = ()
        return header

    def reorderDetails(self, ordered_items):
        """Sort existing Details rows without destroying/repainting the header.

        Only native table rows are moved.  Keep all retained Qt table indices,
        hit maps and list-view logical order consistent with their new positions.
        Return False if a normal structural refresh is required.
        """
        table = self._details_table
        ordered_items = list(ordered_items)
        if (not self.details_mode or self._rendered_details_mode is not True or table is None
                or getattr(table, "_deleted", False)
                or len(ordered_items) != len(self._values)
                or {item.key for item in ordered_items} != {item.key for item in self._values}):
            return False
        old_keys = [item.key for item in self._values]
        new_keys = [item.key for item in ordered_items]
        if old_keys != new_keys:
            old_by_key = {key: index for index, key in enumerate(old_keys)}
            old_rows = list(table._row_tags)
            new_to_old = [old_by_key[key] for key in new_keys]
            new_rows = [old_rows[index] for index in new_to_old]
            # Rearrange in reverse order, placing each existing row before its
            # successor.  No rows, headers, icons or text controls are recreated.
            try:
                for index in range(len(new_rows) - 1, -1, -1):
                    if index == len(new_rows) - 1:
                        self.backend.move_item(new_rows[index], parent=table.tag)
                    else:
                        self.backend.move_item(new_rows[index], before=new_rows[index + 1])
            except Exception:
                return False
            table._row_tags = new_rows
            def rekey(mapping):
                return {(index, column): mapping[(old_index, column)]
                        for index, old_index in enumerate(new_to_old)
                        for column in range(table.columnCount())
                        if (old_index, column) in mapping}
            table._items = rekey(table._items)
            table._native_items = rekey(table._native_items)
            table._cell_widgets = rekey(table._cell_widgets)
            for (index, column), item in table._items.items():
                item._row = index
            table._reindex_cell_widget_keys()
            self._row_index = {key: index for index, key in enumerate(new_keys)}
            self._visual_positions = {key: (index, 0) for index, key in enumerate(new_keys)}
            self._visual_keys = {(index, 0): key for index, key in enumerate(new_keys)}
            self._values = ordered_items
            previous_current = self.current
            previous_anchor = self.anchor
            self._state.replace(new_keys)
            # QFileDialog/QListView model reordering must not manufacture a
            # current index. QtItemViewState.replace() deliberately chooses
            # row zero for generic keyboard models when current is invalid; in
            # a file selector that synthetic current can later receive deferred
            # native focus and scroll the viewport back to the first row.
            if previous_current is None:
                self._state.current = None
                self._state.anchor = None
            elif previous_anchor is None:
                self._state.anchor = previous_current
            self._full_visual_sync = True
            self._sync_selection_visuals()
            self._last_click_key = self._last_click_frame = None
        # Update arrow only once, with the same persistent header buttons.
        self._details_header_widths = ()
        self._sync_details_header_geometry()
        return True

    def setItems(self, items):
        # Snapshot the embedded table scroll before rebuilding.  Details mode
        # owns vertical scrolling; Explorer List mode owns horizontal scrolling.
        previous_table = getattr(self, "_details_table", None)
        had_table = previous_table is not None and not getattr(previous_table, "_deleted", False)
        previous_mode = self._rendered_view_mode
        preserved_scroll_y = self.verticalScrollValue() if had_table else 0.0
        preserved_scroll_x = self.horizontalScrollValue() if had_table else 0.0

        self._full_visual_sync = True
        self._row_generation += 1
        self._name_column_width = None
        self._last_click_key = self._last_click_frame = None
        self._last_click_at = 0.0
        self._qt_bridge_click = None
        self._hovered_row_key = None
        self._visual_positions.clear()
        self._visual_keys.clear()
        self._visual_cells.clear()
        self._list_flow_rows = self._list_flow_columns = 0

        empty_state = self._empty_state_frame
        self._empty_state_frame = None
        if empty_state is not None:
            try:
                if empty_state.exists():
                    empty_state.delete()
            except Exception:
                pass

        table_before = self._details_table
        self._details_table = None
        if table_before is not None:
            try:
                if table_before.exists():
                    table_before.delete()
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

        # All visible Selectables were reparented into the old table.  Force
        # QtListView's structural path so the renderer cannot retain native ids
        # that disappeared with that table.
        if had_table:
            self._values = []
        super().setItems(items)
        self._row_enabled = {item.key: bool(item.enabled) for item in self._values}
        self.icons.clear()

        mode_geometry = self._mode_geometry()
        if self.details_mode:
            table_rows, column_count = len(self._values), 4
            item_height = METRICS.row_height - 2 * METRICS.table_cell_padding_y
        else:
            table_rows, column_count = self._mode_flow_shape(len(self._values))
            self._list_flow_rows, self._list_flow_columns = table_rows, column_count
            item_height = int(mode_geometry["row_height"]) - 2 * METRICS.list_cell_padding_y

        # Every mode needs a usable filename width before reparenting. Details
        # refines its safe initial hint once the new header has been rendered.
        item_width_hint = self._initial_name_width()
        for key in tuple(self.items):
            self.setItemSizeHint(key, width=item_width_hint, height=item_height)

        table = FolderDetailsTable(
            rows=table_rows, columns=column_count, parent=self.tag,
            header_row=False, width=-1, height=-1,
            scroll_x=(False if self.details_mode else bool(mode_geometry["scroll_x"])),
            scroll_y=(self.details_mode or not bool(mode_geometry["scroll_x"])),
            resizable=self.details_mode,
            row_background=False, grid_lines=False,
            freeze_rows=1 if self.details_mode else 0,
            sortable=False, callback=self._sorted,
            sizing_policy=(None if self.details_mode else QTableWidget.FixedFit),
            borders_outerH=False, borders_outerV=False, pad_outerX=False,
            # Explorer has separators in the header, not body grid lines.
            borders_innerV=False, borders_innerH=False,
        )
        for separator in self._details_header_separators:
            try:
                self.backend.delete_item(separator)
            except Exception:
                pass
        self._details_header_separators = []
        self._details_table = table
        self._details_header_cells = []
        self._details_header_widths = ()
        self._rendered_details_mode = self.details_mode
        self._rendered_view_mode = self.view_mode_name
        self.table = table.tag
        # Skin the table's real scroll range, using its fixed outer host only
        # for bounds. The host itself stays pinned and never owns scrolling.
        from DearUIQt.backends.shared_scrollers import register_scroll_surface
        register_scroll_surface(self.backend, table.tag, viewport=self.tag)
        self._reset_host_scroll()
        self.detail_columns = ()
        self._column_keys = {}

        if self.details_mode:
            table.setTheme(browser_details_theme())
            labels = ["Name", "Size", "Type", "Date modified"]
            table.setHorizontalHeaderLabels(labels)
            table.setColumnStretch(0, 1.0)
            table.setColumnWidth(1, METRICS.size_column_width)
            table.setColumnWidth(2, METRICS.type_column_width)
            table.setColumnWidth(3, METRICS.date_column_width)
            size_column = table.nativeColumn(1)
            type_column = table.nativeColumn(2)
            date_column = table.nativeColumn(3)
            self.detail_columns = (date_column, type_column)
            self._install_centered_details_header(table, labels)
        else:
            table.setTheme(browser_list_mode_theme())
            for column in range(column_count):
                table.setColumnWidth(column, int(mode_geometry["cell_width"]))
                table.setColumnResizable(column, False)

        row_layout_theme = browser_details_row_layout_theme()

        def build_name_cell(item, parent, content_height):
            tag = self.items[item.key]
            icon_size = METRICS.list_icon_size if self.details_mode else int(mode_geometry["icon_size"])
            layout = QHBoxLayout(parent=parent, spacing=METRICS.name_icon_gap)
            layout.setTheme(row_layout_theme)
            name = layout.tag
            # A native image widget is intentionally used instead of a draw-list
            # here.  Dear ImGui table cells clip nested draw lists at the row
            # content rect on Windows; the last 1-2 device pixels of 16 px Shell
            # icons could therefore disappear even though the logical row height
            # was sufficient.  Keeping the bitmap as a real layout item makes
            # the whole texture participate in row measurement and clipping.
            # Compact Details/List cells need one transparent guard pixel
            # around the native 16 px Shell raster. Dear ImGui table clipping
            # can shave the final device-pixel row/column of an image widget on
            # Windows. Padding the *texture* (rather than enlarging/scaling the
            # glyph) makes any clipping consume transparency instead of icon
            # pixels. Larger icon modes already have ample cell guard space.
            icon_guard = 1 if icon_size == METRICS.list_icon_size else 0
            rendered_icon_size = icon_size + 2 * icon_guard
            icon_slot_widget = QFrame(
                parent=name, width=icon_size + 4, height=content_height,
                frame_shape=QFrame.NoFrame, no_scrollbar=True,
                no_scroll_with_mouse=True)
            icon_slot_widget.setTheme(browser_row_cell_theme())
            icon_slot = icon_slot_widget.tag
            entry_type = self.entry_types.get(item.key, "Folder")
            is_dir = self.entry_is_dirs.get(item.key, True)
            if is_dir:
                texture = folder_item_texture(size=icon_size, padding=icon_guard)
            else:
                texture = WindowsIconRegistry.get_icon(
                    Path(item.key).suffix, size=icon_size, padding=icon_guard)
            icon_y = (max(0, (content_height - rendered_icon_size) // 2)
                      + METRICS.list_icon_optical_offset_y)
            icon_x = max(0, (icon_size + 4 - rendered_icon_size) // 2)
            icon_view = QImageView(
                texture, parent=icon_slot, width=rendered_icon_size,
                height=rendered_icon_size, pos=(icon_x, icon_y))
            self.icons[item.key] = icon_view.tag
            self._bind_visual_cell_hit(icon_slot, item.key)
            text_parent = name
            if not self.details_mode and self.view_mode_name in ("Tiles", "Content"):
                text_stack = QVBoxLayout(parent=name, spacing=1)
                text_stack.setTheme(row_layout_theme)
                text_parent = text_stack.tag
            QRetainedItem(tag).reparent(text_parent)
            # The safe initial width was applied before reparenting. Details
            # will derive its exact Name width from the rendered header; other
            # modes already know their fixed Explorer-style filename width.
            initial_name_width = self._initial_name_width()
            QRetainedItem(tag).configure(
                label=item.text, width=initial_name_width,
                height=(content_height if text_parent == name else max(20, content_height // 2)),
                span_columns=False)
            if not self.details_mode and self.view_mode_name in ("Tiles", "Content"):
                modified = self.details.get(item.key, 0)
                date = (datetime.fromtimestamp(modified).strftime("%m/%d/%Y %H:%M")
                        if modified else "")
                if self.view_mode_name == "Tiles":
                    meta = entry_type
                else:
                    size = "" if is_dir else self._format_size(self.entry_sizes.get(item.key))
                    meta = " • ".join(part for part in (entry_type, size, date) if part)
                QLabel(meta, parent=text_parent)
            return entry_type, is_dir

        if self.details_mode:
            content_height = METRICS.row_height - 2 * METRICS.table_cell_padding_y
            for row_index, item in enumerate(self._values):
                row = table.nativeRow(row_index)
                self._row_index[item.key] = row_index
                self._visual_positions[item.key] = (row_index, 0)
                self._visual_keys[(row_index, 0)] = item.key
                entry_type, is_dir = build_name_cell(item, row, content_height)

                modified = self.details.get(item.key, 0)
                date = (datetime.fromtimestamp(modified).strftime("%m/%d/%Y %H:%M")
                        if modified else "")
                date_item = QTableWidgetItem(date)
                date_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                type_item = QTableWidgetItem(entry_type)
                type_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                size_item = QTableWidgetItem(
                    "" if is_dir else self._format_size(self.entry_sizes.get(item.key)))
                size_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                table.setItem(row_index, 1, size_item)
                table.setItem(row_index, 2, type_item)
                table.setItem(row_index, 3, date_item)
                size_cell = table.nativeItem(row_index, 1)
                type_text = table.nativeItem(row_index, 2)
                date_text = table.nativeItem(row_index, 3)
                self._bind_visual_cell_hit(size_cell, item.key)
                self._bind_visual_cell_hit(type_text, item.key)
                self._bind_visual_cell_hit(date_text, item.key)
                self.detail_texts[item.key] = (date_text, type_text, size_cell)
        else:
            content_height = int(mode_geometry["row_height"]) - 2 * METRICS.list_cell_padding_y
            flow = mode_geometry["flow"]
            for logical_index, item in enumerate(self._values):
                if flow == "columns":
                    row_index = logical_index % table_rows
                    column = logical_index // table_rows
                elif flow == "content":
                    row_index, column = logical_index, 0
                else:
                    row_index = logical_index // column_count
                    column = logical_index % column_count
                native_row = table.nativeRow(row_index)
                cell = QFrame(
                    parent=native_row, width=-1, height=content_height,
                    frame_shape=QFrame.NoFrame, no_scrollbar=True,
                    no_scroll_with_mouse=True)
                cell.setTheme(browser_row_cell_theme())
                table.setCellWidget(row_index, column, cell)
                self._row_index[item.key] = row_index
                self._visual_positions[item.key] = (row_index, column)
                self._visual_keys[(row_index, column)] = item.key
                self._visual_cells[item.key] = cell
                self._bind_visual_cell_hit(cell.tag, item.key)
                build_name_cell(item, cell, content_height)

        if not self._values:
            self._add_empty_state()

        # Apply initial selection state once after all visual cells exist.
        self._full_visual_sync = True
        self._sync_selection_visuals()
        self._fit_name_column()

        # Preserve scroll only for same-mode refreshes. Switching Details/List
        # starts at that mode's natural origin, matching Explorer.
        if previous_mode == self.view_mode_name and self._values:
            if not bool(mode_geometry["scroll_x"]) and preserved_scroll_y > 0.0:
                self.setVerticalScrollValue(preserved_scroll_y)
                if self._after is not None:
                    try:
                        self._after(1, self._restore_table_scroll,
                                    table.tag, preserved_scroll_y, self._row_generation,
                                    self._scroll_restore_revision)
                    except Exception:
                        pass
            elif not self.details_mode and preserved_scroll_x > 0.0:
                self.setHorizontalScrollValue(preserved_scroll_x)
                if self._after is not None:
                    try:
                        self._after(1, self._restore_table_horizontal_scroll,
                                    table.tag, preserved_scroll_x, self._row_generation,
                                    self._scroll_restore_revision)
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

        # Keep every label centered in its fixed-height cell. Only text/state
        # chrome belongs to these items; the table owns the full-row fill.
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

        # One table-row background owns BOTH hover and selection. Unlike a
        # Selectable embedded in the Name group, it covers the complete row
        # pitch, including the icon and the trailing layout spacing.
        for key in dirty:
            self._paint_row_background(key)
        for key in dirty:
            cells = self.detail_texts.get(key)
            if not cells:
                continue
            for cell_index, cell in enumerate(cells):
                # Stored order is Date, Type, Size; numeric sizes align right.
                cell_state = (key in selected, active, not self._row_enabled.get(key, True), cell_index == 2)
                theme = self._qt_selection_themes.get(cell_state)
                if theme is None:
                    theme = browser_selected_text_theme(
                        active=cell_state[0] and active, disabled=cell_state[2], right_aligned=cell_state[3])
                    self._qt_selection_themes[cell_state] = theme
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
            pos=(0, (METRICS.header_height + 2 * METRICS.table_cell_padding_y)
                 if self.details_mode else 0),
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



class LocalPathDialog(QtDialog):
    """Common local file/folder browser, configured by a selection policy.

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

    def _native_row_pointer_position(self):
        """Map the physical cursor only when this enabled HWND owns foreground."""
        import ctypes
        from ctypes import wintypes
        native = getattr(self, "_native_window_backend", None)
        if native is None:
            return None
        user32 = ctypes.windll.user32
        hwnd = int(native.winId(self.tag) or 0)
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.IsWindowEnabled.argtypes = [wintypes.HWND]
        if (not hwnd or int(user32.GetForegroundWindow() or 0) != hwnd
                or not user32.IsWindowEnabled(wintypes.HWND(hwnd))):
            return None
        from DearUIQt.gui.placement import item_screen_rect
        screen = QCursor.screenPos()
        origin = item_screen_rect(self.listbox.backend, self.tag)
        retained = QRetainedItem(self.tag).globalGeometry()
        return (screen.x() - origin[0] + retained.x(), screen.y() - origin[1] + retained.y())

    def _recover_native_row_press(self):
        """Recover a missed native row press, never replay a held mouse button.

        In-process secondary HWNDs can retain valid but stale ImGui mouse state
        and deliver no QApplication mouse handler at all. Native Selectable
        callbacks cannot safely supply a row key in that case (often row 0).
        Sample only press edges while this enabled chooser owns foreground,
        using the physical cursor mapped into the retained layout coordinates.
        Normal Qt delivery wins when it already handled this physical press.
        """
        if not self.winfo_exists() or not self.isVisible() or self._finished:
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            down = bool(user32.GetAsyncKeyState(1) & 0x8000)
            previous = self._native_row_left_down
            self._native_row_left_down = down
            if not down:
                self._native_row_last_up = time.monotonic()
            if not down or previous:
                return
            self._native_row_press_recovered = False
            point = self._native_row_pointer_position()
            if point is None:
                return
            bridge = self.listbox._qt_bridge_click
            if bridge is not None and bridge[2] > self._native_row_last_up:
                return  # The QApplication route already handled this press.
            bounds = QRetainedItem(self.folder_region).globalGeometry(clipped=True)
            if bounds.isEmpty() or not bounds.contains(point):
                return
            self._native_row_press_recovered = bool(self.native_pointer_press(point))
        except (AttributeError, OSError, TypeError, ValueError):
            return  # Unsupported/custom native backends keep the normal Qt route.

    def event(self, event):
        """Deliver Qt mouse presses to the selector's retained item views.

        QApplication gives a modal QDialog first refusal of pointer events.
        That is correct for focus/ownership, but its generic QDialog handler
        does not know the browser's ImGui table cells.  Route the press to the
        visible row (or sidebar) before allowing it to fall through.  Native
        Selectable and cell callbacks remain as a compatible fallback; the
        list's per-frame guard coalesces duplicate notifications.
        """
        if event.type() == QEvent.MouseButtonPress and isinstance(event, QMouseEvent):
            # The browser consumes row/toolbar presses before QtDialog.event().
            # Record them here too: after-first-present/editor-focus callbacks
            # may still be pending when a chooser is opened during app startup.
            # Those callbacks must never take focus back after a click/scroll.
            self._initial_pointer_activity = True
            self._pointer_interaction_serial = getattr(self, '_pointer_interaction_serial', 0) + 1
        if (event.type() == QEvent.MouseButtonPress
                and isinstance(event, QMouseEvent)
                and event.button() == Qt.LeftButton):
            application = QApplication.instance()
            if application is not None and application.activeModalWidget() is self:
                point = event.globalPosition()
                if os.name == "nt":
                    import ctypes
                    if ctypes.windll.user32.GetAsyncKeyState(1) & 0x8000:
                        try:
                            native_point = self._native_row_pointer_position()
                            if native_point is not None:
                                point = native_point
                        except (AttributeError, OSError, TypeError, ValueError):
                            pass
                # Toolbar view-mode buttons must win the mouse press before
                # the retained item-view router. In List mode Dear ImGui can
                # briefly keep an oversized fixed-fit table hit rectangle
                # during reflow; routing these two controls explicitly makes
                # List <-> Details switching deterministic even in that frame.
                if self._view_mode_pointer_hit(point):
                    event.accept()
                    return True
                if getattr(self, "_native_row_press_recovered", False):
                    import ctypes
                    fresh_press = (not self._native_row_left_down and
                                   bool(ctypes.windll.user32.GetAsyncKeyState(1) & 0x8000))
                    bounds = QRetainedItem(self.folder_region).globalGeometry(clipped=True)
                    if not fresh_press and not bounds.isEmpty() and bounds.contains(point):
                        # A delayed renderer notification for a recovered press
                        # must not become a second click or restore row zero.
                        event.accept()
                        return True
                # A new press starts a new transaction, even when two genuine
                # clicks occur rapidly on the same file/folder row.
                self.listbox._qt_bridge_click = None
                if self._selector_pointer_hit(point):
                    frame = application.frameCount()
                    key = self.listbox.current
                    if key in self.listbox.selected:
                        self.listbox._qt_bridge_click = (key, frame, time.monotonic())
                    event.accept()
                    return True
        return super().event(event)

    def _view_mode_pointer_hit(self, point):
        """Give Explorer view-mode buttons priority over item-view hitboxes."""
        try:
            x, y = (float(point.x()), float(point.y())) if hasattr(point, 'x') else map(float, point)
        except Exception:
            return False
        for tag, mode in ((getattr(self, "list_view_button", None), "__menu__"),
                          (getattr(self, "details_view_button", None), "Details")):
            if tag is None:
                continue
            try:
                bounds = QRetainedItem(tag).globalGeometry(clipped=True)
                if not bounds.isEmpty() and bounds.contains((int(x), int(y))):
                    if mode == "__menu__":
                        self._show_view_options_menu()
                    else:
                        self._change_view(mode)
                    return True
            except Exception:
                continue
        return False

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
        try:
            x, y = (float(point.x()), float(point.y())) if hasattr(point, 'x') else map(float, point)
        except Exception:
            return False

        # Mouse presses are delivered to a modal QDialog before the native
        # Dear ImGui widgets.  The file-list router must therefore be clipped
        # to the *visible folder pane*, not merely to FolderListView's retained
        # host geometry.  In Explorer List mode the nested fixed-fit table can
        # temporarily report a host/clipped rectangle that reaches into the
        # toolbar while columns are being rebuilt/reflowed.  Treating that
        # rectangle as authoritative swallowed the Details/List toolbar click:
        # the dialog accepted the press as an item click before QToolButton saw
        # it.  folder_region is the stable layout boundary below the toolbar,
        # so only presses inside it may be routed to the list.
        try:
            folder_bounds = QRetainedItem(self.folder_region).globalGeometry(clipped=True)
        except Exception:
            folder_bounds = None
        if (folder_bounds is not None and not folder_bounds.isEmpty()
                and folder_bounds.contains((int(x), int(y)))):
            if self.listbox._row_pointer_clicked(point=point):
                return True

        try:
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
        # This hook is called once per captured WM_LBUTTONDOWN, and only when
        # the normal Qt/ImGui pointer position was unavailable.
        self._initial_pointer_activity = True
        self._pointer_interaction_serial = getattr(self, '_pointer_interaction_serial', 0) + 1
        self.listbox._qt_bridge_click = None
        return self._selector_pointer_hit(point)

    def __init__(self, view, initial, on_result, *, selection_kind="folder",
                 multiple=False, extensions=(), save=False, default_filename="",
                 show_hidden=False, title=None):
        self.selection_options = PathSelectionOptions(
            selection_kind, bool(multiple), tuple(extensions or ()), bool(save))
        self.multiple = self.selection_options.multiple
        self.save = self.selection_options.save
        self.extensions = self.selection_options.extensions
        self._show_all_files = not self.extensions
        self._filename = str(default_filename or "")
        self._overwrite_path = None
        is_file = selection_kind == "file"
        self.dialog_title = title or ("Save File" if self.save else
                                     "Open File" if is_file else "Open Folder")
        self.selection_caption = ("File names:" if self.multiple else "File name:") if is_file else (
            "Folders:" if self.multiple else "Folder:")
        self.accept_caption = "Save" if self.save else "Open" if is_file else (
            "Select Folders" if self.multiple else "Select Folder")
        self.context_selection_caption = "Select file" if is_file else "Select folder"
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
        self._entry_is_dirs = {}
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
        self._view_options_menu = None
        self._details_pane_enabled = False
        self._preview_pane_enabled = False
        self._show_hidden_items = bool(show_hidden)
        self._show_file_extensions = True
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
        self._list_view_control.clicked.connect(self._show_view_options_menu)
        self.list_view_button = self._list_view_control.tag
        self._details_tool_theme = browser_tool_button_theme(checked=True)
        self._list_tool_theme = browser_tool_button_theme(checked=False)
        self._details_view_control.setTheme(self._details_tool_theme)
        self._list_view_control.setTheme(self._list_tool_theme)
        add_styled_tooltip(self.details_view_button, "Details view")
        add_styled_tooltip(self.list_view_button, "View")
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
                multiple=self.multiple,
                after=self.view.after,
                on_sort=self._sort_entries,
            )
        )
        self.listbox._configure("border", False)
        self.listbox.setTheme(browser_list_viewport_theme())
        self.listbox.doubleClicked.connect(self._queue_row_activation)
        self.listbox.currentChanged.connect(self._selection_changed)
        self.listbox.selectionChanged.connect(
            lambda *_args: self._selection_changed(self.listbox.current))
        # Geometry/hover refresh is painting work, not an input handler. Native
        # visibility callbacks can be gated by modal input ownership, so use a
        # dialog-owned UI timer for resize/elision and hover reconciliation.
        self._list_paint_timer = self.create_timer(30, self.listbox._refresh_row_hover)
        if os.name == "nt":
            import ctypes
            self._native_row_left_down = bool(ctypes.windll.user32.GetAsyncKeyState(1) & 0x8000)
            self._native_row_last_up = time.monotonic()
            self._native_row_press_recovered = False
            self._native_row_input_timer = self.create_timer(16, self._recover_native_row_press)

        # Explorer-compatible optional right pane. Details pane and Preview pane
        # share the same region and are mutually exclusive, matching Explorer.
        self._right_pane_divider_frame = QFrame(
            parent=self._workspace_layout, width=METRICS.divider_width, height=-1,
            show=False, frame_shape=QFrame.NoFrame, no_scrollbar=True, no_scroll_with_mouse=True)
        self._right_pane_divider_frame.setTheme(browser_divider_theme())
        self._right_pane_frame = QFrame(
            parent=self._workspace_layout, width=224, height=-1, show=False,
            frame_shape=QFrame.NoFrame, no_scrollbar=True, no_scroll_with_mouse=True)
        self._right_pane_frame.setTheme(browser_surface_theme(padding=(12, 12)))
        self._right_pane_layout = QVBoxLayout(parent=self._right_pane_frame, spacing=6)
        self._right_pane_title = QLabel("", parent=self._right_pane_layout)
        self._right_pane_name = QLabel("", parent=self._right_pane_layout, wrap=196)
        self._right_pane_meta = QLabel("", parent=self._right_pane_layout, wrap=196)
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
        # Both selectors use the same rows and controls. Only the filter
        # choices and target-kind policy differ.
        self.file_edit = self.folder_edit
        if self.selection_options.kind == "file":
            set_editor_text(self._folder_edit_control, self._filename)
            self._supported_filter = "Supported files ({})".format(
                ", ".join("*" + ext for ext in self.extensions))
            filters = ([self._supported_filter, "All files (*.*)"] if self.extensions
                       else ["All files (*.*)"])
        else:
            filters = ["Folders"]
        self._form_labels['filter'] = self._form_caption(
            "Files of type:" if self.selection_options.kind == "file" else "Items of type:",
            self._selection_grid.cell(1, 0))
        self.file_type = self.combo(
            filters, parent=self._selection_grid.cell(1, 1).tag,
            default_value=filters[0], width=-1, callback=self._file_type_changed,
            theme_provider=self._selector_theme_provider('combo'))

    def _file_type_changed(self, _sender, value, *_args):
        self._show_all_files = value == "All files (*.*)"
        self._refresh()

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
        return {"generation": self._generation, "frame": self.listbox._input_frame(), "release_frame": None}

    def _pointer_transaction_finished(self, transaction):
        frame = self.listbox._input_frame()
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

    def _view_menu_specs(self):
        current = self.listbox.viewMode() if hasattr(self, "listbox") else "Details"
        specs = []
        for mode in FolderListView.VIEW_MODES:
            specs.append({
                "id": "view:" + mode, "action": "view:" + mode, "label": mode,
                "icon": view_mode_texture(mode),
                "checkable": True, "checked": mode == current,
            })
        specs.extend([
            {"label": "---", "separator": True, "id": "view-sep-1"},
            {"id": "details-pane", "action": "details-pane", "label": "Details pane",
             "checkable": True, "checked": self._details_pane_enabled},
            {"id": "preview-pane", "action": "preview-pane", "label": "Preview pane",
             "checkable": True, "checked": self._preview_pane_enabled},
            {"label": "---", "separator": True, "id": "view-sep-2"},
            {"id": "show", "label": "Show", "children": [
                {"id": "show-hidden", "action": "show-hidden", "label": "Hidden items",
                 "checkable": True, "checked": self._show_hidden_items},
                {"id": "show-extensions", "action": "show-extensions",
                 "label": "File name extensions", "checkable": True,
                 "checked": self._show_file_extensions},
            ]},
        ])
        return specs

    def _ensure_view_options_menu(self):
        menu = self._view_options_menu
        if menu is None or not menu.exists():
            menu = QMenu(self._view_menu_specs(), after=self.view.after,
                         min_width=190, max_width=280, parent_window=self.tag)
            menu.triggered.connect(self._view_menu_triggered)
            self._view_options_menu = menu
        else:
            menu.setActions(self._view_menu_specs())
        return menu

    def _show_view_options_menu(self, *_args):
        menu = self._ensure_view_options_menu()
        try:
            bounds = QRetainedItem(self.list_view_button).globalGeometry(clipped=True)
            menu.popup((bounds.x(), bounds.y() + bounds.height() + 1))
        except Exception:
            menu.popup()
        return True

    def _view_menu_triggered(self, action, _context=None):
        action = str(action or "")
        if action.startswith("view:"):
            self._change_view(action.split(":", 1)[1])
        elif action == "details-pane":
            self._details_pane_enabled = not self._details_pane_enabled
            if self._details_pane_enabled:
                self._preview_pane_enabled = False
            self._sync_right_pane()
        elif action == "preview-pane":
            self._preview_pane_enabled = not self._preview_pane_enabled
            if self._preview_pane_enabled:
                self._details_pane_enabled = False
            self._sync_right_pane()
        elif action == "show-hidden":
            self._show_hidden_items = not self._show_hidden_items
            self._refresh()
        elif action == "show-extensions":
            self._show_file_extensions = not self._show_file_extensions
            self._filter_entries()
        if self._view_options_menu is not None and self._view_options_menu.exists():
            self._view_options_menu.setActions(self._view_menu_specs())

    def _sync_right_pane(self):
        pane = getattr(self, "_right_pane_frame", None)
        divider = getattr(self, "_right_pane_divider_frame", None)
        if pane is None or divider is None:
            return
        visible = bool(self._details_pane_enabled or self._preview_pane_enabled)
        if visible:
            divider.show()
            pane.show()
        else:
            divider.hide()
            pane.hide()
            return
        key = getattr(self.listbox, "current", None)
        path = self._entries.get(key, key) if key else None
        title = "Preview" if self._preview_pane_enabled else "Details"
        self._right_pane_title.setText(title)
        if not path:
            self._right_pane_name.setText("Select an item to view information.")
            self._right_pane_meta.setText("")
            return
        name = Path(path).name or str(path)
        is_dir = self._entry_is_dirs.get(path)
        if is_dir is None:
            is_dir = os.path.isdir(path)
        kind = self._entry_types.get(path, "Folder" if is_dir else file_type_name(name, False))
        size = "" if is_dir else FolderListView._format_size(self._entry_sizes.get(path))
        modified = self._folder_mtimes.get(path, 0)
        date = datetime.fromtimestamp(modified).strftime("%m/%d/%Y %H:%M") if modified else ""
        self._right_pane_name.setText(name)
        if self._preview_pane_enabled:
            text = "Folder preview" if is_dir else "{} preview".format(kind)
        else:
            text = "\n".join(part for part in (kind, size, date, str(path)) if part)
        self._right_pane_meta.setText(text)

    def _change_view(self, value):
        value = str(value or "Details")
        if value not in FolderListView.VIEW_MODES:
            value = "Details"
        if self.listbox.viewMode() == value:
            return
        self.listbox.setViewMode(value)
        if hasattr(self, "details_view_button"):
            details = value == "Details"
            self._details_tool_theme = browser_tool_button_theme(checked=details)
            self._list_tool_theme = browser_tool_button_theme(checked=not details)
            self._details_view_control.setTheme(self._details_tool_theme)
            self._list_view_control.setTheme(self._list_tool_theme)
        if self._view_options_menu is not None and self._view_options_menu.exists():
            self._view_options_menu.setActions(self._view_menu_specs())
        self._filter_entries()

    def _apply_layout(self):
        super()._apply_layout()
        if hasattr(self, "address") and self.winfo_exists():
            self.address.refresh()
        if hasattr(self, "listbox") and self.winfo_exists():
            self.listbox.requestListReflow()

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
        if self.selection_options.kind == "folder" or not os.path.isdir(renamed):
            set_editor_text(self._folder_edit_control, self.selection_options.format_paths([renamed]))
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
        position = QCursor.screenPos().toTuple()
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
        menu.popupGlobal(position, context=(parent, path))

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
                if self.selection_options.kind == "file" and os.path.isdir(path):
                    self._navigate(path)
                else:
                    if path not in self.listbox.selected:
                        self.listbox.setCurrentKey(path, select=True)
                    self._selection_changed(path)
                    self._select_folder()
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
        filename = self._folder_edit_control.text() if self.save else ""
        self._current_path = candidate
        self._initial_location_pending = False
        self.set_control_enabled(self._accept_button, True)
        self._folder_context_menu.hide()
        self._select_after_load = None
        self._hide_new_folder()
        set_editor_text(self._path_edit_control, candidate)
        self.address._icon_view.setPixmap(address_location_texture(candidate, size=18))
        self._update_breadcrumbs()
        set_editor_text(self._folder_edit_control,
                        candidate if self.selection_options.kind == "folder" else filename)
        self._overwrite_path = None
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
        if self.multiple:
            paths = [key for key in self.listbox.selectedKeys()
                     if self._entry_is_dirs.get(key, True) == (self.selection_options.kind == "folder")]
            set_editor_text(self._folder_edit_control, self.selection_options.format_paths(paths))
            self._overwrite_path = None
        elif self.selection_options.kind == "file":
            # A folder click is navigation, not a replacement for a typed save
            # filename. Directory metadata is independent of localized Type.
            if key in self._entries and not self._entry_is_dirs.get(key, True):
                set_editor_text(self._folder_edit_control, Path(key).name)
                self._overwrite_path = None
        elif hasattr(self, "folder_edit"):
            set_editor_text(self._folder_edit_control, self._entries.get(key, self._current_path))
        self._sync_right_pane()

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
        self.listbox.entry_is_dirs = self._entry_is_dirs
        self.listbox.entry_sizes = self._entry_sizes
        self.listbox.sort_column, self.listbox.sort_ascending = self._sort_column, self._sort_ascending
        is_file = self.selection_options.kind == "file"
        self.listbox.empty_text = (("No files match your search." if query else "No matching files in this folder.")
                                   if is_file else
                                   ("No folders match your search." if query else "This folder is empty."))
        rendered_items = []
        for _, name, path in entries:
            display_name = name
            if (not self._show_file_extensions and not self._entry_is_dirs.get(path, True)):
                display_name = Path(name).stem or name
            rendered_items.append(QtListItem(path, display_name, path))
        if not self.listbox.reorderDetails(rendered_items):
            self.listbox.setItems(rendered_items)
        # Path editors and list rows own Enter (navigate/activate); do not
        # also run the dialog default action for that same physical keypress.
        self.enter_editors = {self.path_edit, self.folder_edit, self.filter_edit,
                              *self.listbox.items.values()}
        count = len(entries)
        self._set_status("{} item(s)".format(count) if is_file else
                         "{} folder{}".format(count, "" if count == 1 else "s"))
        if self.multiple:
            self._selection_changed(self.listbox.current)

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
        if self.selection_options.kind == "file" and os.path.isfile(value):
            return str(Path(value).parent), Path(value).name
        return (value if os.path.isdir(value) else str(safe_current_directory())), None

    def _apply_initial_filename(self, filename):
        if self.selection_options.kind == "file":
            if filename is not None:
                self._filename = filename
            set_editor_text(self._folder_edit_control, self._filename)
        else:
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
        selection_revision = getattr(getattr(self, "listbox", None), "_selection_revision", None)
        scroll_revision = getattr(getattr(self, "listbox", None), "_scroll_restore_revision", None)
        self._set_status("Loading...")

        def worker():
            entries, error, modified, kinds, sizes, is_dirs = [], None, {}, {}, {}, {}
            try:
                with os.scandir(path) as iterator:
                    for entry in iterator:
                        if (generation != self._generation or path != self._current_path
                                or getattr(self, "_finished", False)):
                            break  # A superseded scan must not occupy the worker.
                        try:
                            is_dir = entry.is_dir(follow_symlinks=True)
                            hidden = entry.name.startswith(".")
                            if os.name == "nt":
                                try:
                                    hidden = hidden or bool(entry.stat(follow_symlinks=False).st_file_attributes & 0x2)
                                except (AttributeError, OSError):
                                    pass
                            if (self._show_hidden_items or not hidden) and self._include_entry(entry, is_dir):
                                entries.append((entry.name.casefold(), entry.name, entry.path))
                                is_dirs[entry.path] = is_dir
                                kinds[entry.path] = file_type_name(entry.name, is_dir)
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
            return entries, error, modified, kinds, sizes, is_dirs

        self.runAsync(
            worker,
            on_result=lambda outcome: self._apply_entries(
                    generation, path, outcome[0], outcome[1], outcome[2], outcome[3], outcome[4], outcome[5],
                    selection_revision, scroll_revision),
        )

    def _include_entry(self, entry, is_dir):
        return self.selection_options.includes(entry, is_dir, show_all=self._show_all_files)

    def _apply_entries(self, generation, path, entries, error, modified=None, kinds=None, sizes=None,
                       is_dirs=None, selection_revision=None, scroll_revision=None):
        if not self.winfo_exists() or generation != self._generation:
            return
        if path != self._current_path:
            return
        selection_unchanged = (selection_revision is None or
                               self.listbox._selection_revision == selection_revision)
        scroll_unchanged = (scroll_revision is None or
                            getattr(self.listbox, '_scroll_restore_revision', None) == scroll_revision)
        # A directory scan can start during the selector's first visible frame
        # and finish after the user has already clicked or scrolled. Treat that
        # live interaction as authoritative. The async result may update row
        # metadata/order, but must not replace current/selection or snap the
        # visible table back to row zero.
        interaction_snapshot = None
        can_snapshot_interaction = all(hasattr(self.listbox, name) for name in (
            'current', 'selected', 'verticalScrollValue', 'horizontalScrollValue'))
        if (not selection_unchanged or not scroll_unchanged) and can_snapshot_interaction:
            interaction_snapshot = (
                self.listbox.current, set(self.listbox.selected),
                self.listbox.verticalScrollValue(), self.listbox.horizontalScrollValue(),
            )
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
        self._entry_is_dirs = is_dirs or {}
        self._entry_sizes = sizes or {}
        self._listing = entries
        self._filter_entries()
        if interaction_snapshot is not None:
            current, selected, scroll_y, scroll_x = interaction_snapshot
            valid = set(self.listbox.items)
            selected.intersection_update(valid)
            if current not in valid:
                current = None
            # Restore the already-observed user state without calling
            # setCurrentKey(): that API intentionally focuses the row and can
            # itself scroll an offscreen native item into view.
            self.listbox._state.selected = selected
            self.listbox._state.current = current
            self.listbox._state.anchor = current
            self.listbox._full_visual_sync = True
            self.listbox._sync_selection_visuals()
            self.listbox._sync_model_selection()
            if not scroll_unchanged:
                self.listbox.setVerticalScrollValue(scroll_y)
                self.listbox.setHorizontalScrollValue(scroll_x)
                table = getattr(self.listbox, '_details_table', None)
                if table is not None and not getattr(table, '_deleted', False):
                    revision = getattr(self.listbox, '_scroll_restore_revision', 0)
                    row_generation = getattr(self.listbox, '_row_generation', 0)
                    restore_y = getattr(self.listbox, '_restore_table_scroll', None)
                    restore_x = getattr(self.listbox, '_restore_table_horizontal_scroll', None)
                    if callable(restore_y):
                        self.view.after(1, restore_y,
                                        table.tag, scroll_y, row_generation, revision)
                    if callable(restore_x):
                        self.view.after(1, restore_x,
                                        table.tag, scroll_x, row_generation, revision)
        if selection_unchanged and self._select_after_load in self.listbox.items:
            self.listbox.setCurrentKey(self._select_after_load, select=True)
        self._select_after_load = None
        if not selection_unchanged:
            self._rename_after_load = None
        if self._rename_after_load in self.listbox.items:
            self.view.after(20, self._begin_folder_rename, self._rename_after_load)

    def _enter_key(self, key):
        path = self._entries.get(key) or str(key or "")
        if path and os.path.isdir(path):
            self._navigate(path)
        elif path and self.selection_options.kind == "file":
            if not self.multiple:
                set_editor_text(self._folder_edit_control, path)
            else:
                self._selection_changed(key)
            self._select_folder()

    def _select_folder(self):
        if self._rename_path is not None and not self._commit_folder_rename():
            return
        value = str(self._folder_edit_control.text() or "").strip()
        # In file mode a typed directory navigates instead of accepting it.
        if self.selection_options.kind == "file" and value and not value.startswith('"'):
            path = os.path.abspath(os.path.join(
                self._current_path, os.path.expandvars(os.path.expanduser(value))))
            if os.path.isdir(path):
                self._navigate(path)
                return
        try:
            result = self.selection_options.resolve(
                self._current_path, value, show_all=self._show_all_files)
        except ValueError as exc:
            self._set_status(str(exc), error=True)
            return
        if self.save and os.path.exists(result) and self._overwrite_path != result:
            self._overwrite_path = result
            self._set_status("File exists. Press Save again to replace it.", error=True)
            return
        self.finish(result)

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
        if self._view_options_menu is not None:
            self._view_options_menu.delete()
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


class LocalFolderDialog(LocalPathDialog):
    """Folder policy over the common local-path browser surface."""

    def __init__(self, view, initial, on_result, *, multiple=False,
                 show_hidden=False, title=None):
        super().__init__(view, initial, on_result, selection_kind="folder",
                         multiple=multiple, show_hidden=show_hidden, title=title)
