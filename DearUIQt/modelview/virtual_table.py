"""Experimental, opt-in viewport projection for *read-only* DearUIQt tables.

The native Dear PyGui table scrollbar cannot be virtualized merely by hiding
rows: that changes native scroll extents and can invalidate hit-testing. This
controller expects a host with a **logical** scroll offset (such as an external
scrollbar). It materializes only the calculated window into a QTableView, while
its Python row source and selected keys remain logical/global. This is a pilot,
NOT a drop-in replacement for QTableView's native vertical scrollbar.

Nothing imports or instantiates this class on the normal WinUx rendering path.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Sequence

from ..core.object import Signal
from .models import QtGridRow


@dataclass(frozen=True)
class VirtualRowWindow:
    start: int
    stop: int
    total: int
    leading_pixels: float
    trailing_pixels: float

    @property
    def materialized_rows(self):
        return self.stop - self.start


def compute_virtual_window(total, row_height, scroll_y, viewport_height, *,
                           overscan=8, fallback_rows=64):
    """Map logical pixel coordinates to a bounded half-open row interval.

    Startup (zero viewport height), end-of-table and out-of-range scrolling are
    explicitly supported. A host must supply its logical scroll coordinate,
    not the native table's scrolling position after rows are materialized.
    """
    count = max(0, int(total))
    row = float(row_height)
    if not math.isfinite(row) or row <= 0:
        raise ValueError('row_height must be finite and positive')
    if count == 0:
        return VirtualRowWindow(0, 0, 0, 0.0, 0.0)
    over = max(0, int(overscan))
    height = float(viewport_height or 0)
    scroll = float(scroll_y or 0)
    if not math.isfinite(height) or not math.isfinite(scroll):
        raise ValueError('viewport coordinates must be finite')
    height = max(0, height)
    scroll = min(max(0.0, scroll), max(0.0, count * row - height))
    if height <= 1:
        start, stop = 0, min(count, max(1, int(fallback_rows)))
    else:
        first = min(count - 1, int(scroll // row))
        last = min(count, max(first + 1, int(math.ceil((scroll + height) / row))))
        start, stop = max(0, first - over), min(count, last + over)
    return VirtualRowWindow(start, stop, count, start * row, (count - stop) * row)


class ReadOnlyTableViewport:
    """Bounded native-row projection requiring an external *logical* scroll host.

    ``render(scroll_y, viewport_height)`` explicitly changes the native page.
    Subscribe to ``selectionChanged`` on this controller, not to the backing
    native view: rebuilding the projected page may emit temporary view signals.
    Sorting, model-bound tables, persistent editors and index widgets are
    intentionally rejected. This class does not own the view or native scrollbar.
    """

    def __init__(self, view, rows: Sequence, *, row_height=25, overscan=8):
        from .table import QtDataGridView
        if not isinstance(view, QtDataGridView):
            raise TypeError('view must be a DearUIQt QTableView')
        if getattr(view, '_virtual_viewport_controller', None) is not None:
            raise RuntimeError('this native table already has a virtual viewport controller')
        self.view = view
        self.row_height = float(row_height)
        self.overscan = max(0, int(overscan))
        if len({self._key(row) for row in rows}) != len(rows):
            raise ValueError('virtual table requires globally unique row keys')
        self.rows = rows
        self.window = None
        self._selected = set()
        self._current = None
        self._suspended = False
        self.selectionChanged = Signal()
        self._check_read_only()
        self._connection = view.selectionChanged.connect(self._selection_changed)
        view._virtual_viewport_controller = self
        self._last_scroll = (0.0, 0.0)
        self._logical_scroll_bridge = None

    def _check_read_only(self):
        v = self.view
        if (v.model() is not None or v._sort_key is not None or
                v.horizontalHeader().sectionsClickable() or
                v._persistent_editors or v._index_widgets):
            raise ValueError('virtual table pilot requires a read-only, unsorted, model-free table')

    @staticmethod
    def _key(row):
        return row.key if isinstance(row, QtGridRow) else row[0]

    @property
    def selectedKeys(self):
        return frozenset(self._selected)

    @property
    def currentKey(self):
        return self._current

    def _selection_changed(self, *_args):
        if self._suspended:
            return
        visible = set(self.view._row_tags)
        selection = ((self._selected - visible) | (self.view.selected & visible)
                     if self.view.multiple else (self.view.selected & visible))
        if selection != self._selected:
            self._selected = selection
            self.selectionChanged.emit(frozenset(selection))
        if self.view.current in visible:
            self._current = self.view.current

    def render(self, scroll_y, viewport_height, *, force=False):
        if self.view is None:
            raise RuntimeError('virtual viewport has been detached')
        self._check_read_only()
        plan = compute_virtual_window(
            len(self.rows), self.row_height, scroll_y, viewport_height,
            overscan=self.overscan)
        self._last_scroll = (float(scroll_y), float(viewport_height))
        if plan == self.window and not force:
            return plan
        page = self.rows[plan.start:plan.stop]
        keys = [self._key(row) for row in page]
        if len(set(keys)) != len(keys):
            raise ValueError('visible virtual table row keys must be unique')
        previous_selected = set(self._selected)
        previous_current = self._current
        self._suspended = True
        try:
            self.view.set_rows(page)
            self.view._state.selected = previous_selected.intersection(keys)
            if previous_current in keys:
                self.view._state.current = previous_current
            self.view._sync_selection_visuals()
            # The native table is a bounded page, not the logical scrollbar.
            # Preserve X scroll, but reset local Y to avoid false logical offsets.
            self.view.setVerticalScrollValue(0)
        finally:
            self._suspended = False
        self.window = plan
        return plan

    def setRows(self, rows):
        # Validate before replacing the active source: a rejected update must
        # not leave a broken logical dataset behind.
        # Intersection over the source avoids retaining keys for removed rows;
        # unlike native item count it is intentionally O(total) on data reset.
        available = {self._key(row) for row in rows}
        if len(available) != len(rows):
            raise ValueError('virtual table requires globally unique row keys')
        self.rows = rows
        old_selection = set(self._selected)
        self._selected.intersection_update(available)
        if self._current not in available:
            self._current = None
        self.window = None
        self.render(*self._last_scroll, force=True)
        if old_selection != self._selected:
            self.selectionChanged.emit(frozenset(self._selected))
        return self

    def detach(self):
        bridge = self._logical_scroll_bridge
        if bridge is not None:
            bridge.detach()
        if self._connection is not None:
            self._connection.disconnect()
            self._connection = None
        if self.view is not None:
            self.view._virtual_viewport_controller = None
        self.view = None
        self.rows = ()
        # Keep the visible page intact. Expanding to all rows during teardown
        # would cause the exact allocation spike this pilot is meant to avoid.



class LogicalTableScrollBridge:
    """Opt-in logical scrolling via an *external* QScrollBar-like control.

    The scrollbar value is a **logical top-row index**, never the projected
    native table's scroll coordinate. A host must place the slider beside the
    table, forward wheel deltas to :meth:`wheel` and disable mouse scrolling on
    the native table surface. We do not install any global pointer handlers.

    This is intentionally a standalone pilot, not a replacement for native
    QTableView scrolling, and requires no Dear PyGui-specific calls.
    """

    def __init__(self, viewport: ReadOnlyTableViewport, scrollbar, *,
                 viewport_height: float, wheel_rows: int = 3):
        if not isinstance(viewport, ReadOnlyTableViewport) or viewport.view is None:
            raise TypeError('viewport must be an attached ReadOnlyTableViewport')
        if viewport._logical_scroll_bridge is not None:
            raise RuntimeError('virtual table already has a logical scrollbar bridge')
        required = ('valueChanged', 'setRange', 'setPageStep',
                    'setSingleStep', 'setValue', 'value')
        if not all(hasattr(scrollbar, method) for method in required):
            raise TypeError('scrollbar must expose the QScrollBar value/range contract')
        height = self._height(viewport_height)
        self.viewport = viewport
        self.scrollbar = scrollbar
        self.viewport_height = height
        self.wheel_rows = max(1, int(wheel_rows))
        self._wheel_remainder = 0.0
        self._updating = False
        self._connection = None
        # First build the native page; do not keep a half-bound controller if
        # viewport.render fails during initial allocation.
        self._update_range_and_render()
        self._connection = scrollbar.valueChanged.connect(self._value_changed)
        viewport._logical_scroll_bridge = self

    @staticmethod
    def _height(height):
        height = float(height)
        if not math.isfinite(height) or height < 0:
            raise ValueError('viewport height must be finite and non-negative')
        return height

    def _ensure_attached(self):
        if self.viewport is None or self.viewport.view is None:
            raise RuntimeError('logical scrollbar bridge is detached')

    @property
    def topRow(self):
        self._ensure_attached()
        return int(self.scrollbar.value())

    @property
    def maximumTopRow(self):
        self._ensure_attached()
        total_px = len(self.viewport.rows) * self.viewport.row_height
        remaining = max(0.0, total_px - self.viewport_height)
        # ceil allows the final partial viewport to reach the last pixel.
        return min(len(self.viewport.rows) - 1, int(math.ceil(
            remaining / self.viewport.row_height))) if self.viewport.rows else 0

    def _update_range_and_render(self):
        self._ensure_attached()
        if self._updating:
            return self.viewport.window
        self._updating = True
        try:
            page = max(1, int(self.viewport_height // self.viewport.row_height))
            self.scrollbar.setSingleStep(1)
            self.scrollbar.setPageStep(page)
            self.scrollbar.setRange(0, self.maximumTopRow)
            return self.viewport.render(
                self.scrollbar.value() * self.viewport.row_height,
                self.viewport_height)
        finally:
            self._updating = False

    def _value_changed(self, _value):
        if self._updating or self.viewport is None:
            return
        self._ensure_attached()
        self.viewport.render(
            self.scrollbar.value() * self.viewport.row_height,
            self.viewport_height)

    def setViewportHeight(self, height):
        self._ensure_attached()
        self.viewport_height = self._height(height)
        return self._update_range_and_render()

    def refreshRows(self, rows):
        """Replace the logical dataset and clamp the external scroll range."""
        self._ensure_attached()
        self.viewport.setRows(rows)
        return self._update_range_and_render()

    def scrollToRow(self, row, *, alignment='nearest'):
        self._ensure_attached()
        if alignment not in ('start', 'center', 'end', 'nearest'):
            raise ValueError('alignment must be start, center, end or nearest')
        count = len(self.viewport.rows)
        if not count:
            return self._update_range_and_render()
        row = max(0, min(count - 1, int(row)))
        current = self.topRow
        visible = max(1, int(self.viewport_height // self.viewport.row_height))
        if alignment == 'center':
            top = row - visible // 2
        elif alignment == 'end':
            top = row - visible + 1
        elif alignment == 'start':
            top = row
        elif row < current:
            top = row
        elif row >= current + visible:
            top = row - visible + 1
        else:
            top = current
        self.scrollbar.setValue(max(0, min(self.maximumTopRow, top)))
        # QScrollBar emits valueChanged only if its value changes; a no-op
        # jump should not rebuild the native page.
        return self.viewport.window

    def scrollByRows(self, delta):
        self._ensure_attached()
        return self.scrollToRow(self.topRow + int(delta), alignment='start')

    def wheel(self, angle_delta_y):
        """Apply Qt-style wheel angle units (120 per notch), preserving fractions.

        Hosts should call this only when their logical table is under the
        pointer. Positive delta scrolls up; no global mouse capture is used.
        """
        self._ensure_attached()
        delta = float(angle_delta_y)
        if not math.isfinite(delta):
            raise ValueError('wheel delta must be finite')
        self._wheel_remainder += delta
        steps = math.trunc(self._wheel_remainder / 120.0)
        self._wheel_remainder -= steps * 120.0
        if steps:
            return self.scrollByRows(-steps * self.wheel_rows)
        return self.viewport.window

    def detach(self):
        if self._connection is not None:
            self._connection.disconnect()
            self._connection = None
        if self.viewport is not None and self.viewport._logical_scroll_bridge is self:
            self.viewport._logical_scroll_bridge = None
        self.scrollbar = None
        self.viewport = None
        self._wheel_remainder = 0.0


__all__ = ['VirtualRowWindow', 'compute_virtual_window', 'ReadOnlyTableViewport',
           'LogicalTableScrollBridge']
