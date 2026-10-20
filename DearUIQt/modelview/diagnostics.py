"""Opt-in native-resource diagnostics for retained Qt-style list/table views.

This module does not allocate native items or install handlers. Snapshotting is
explicit so normal rendering and polling remain free of profiling overhead.
On a Windows runtime, verify_native=True performs actual backend existence and
child-list queries, which are deliberately not used in per-frame paths.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ViewResourceSnapshot:
    view_kind: str
    logical_rows: int
    tracked_native_rows: int
    tracked_controls: int
    checked_controls: int
    persistent_editors: int
    index_widgets: int
    native_children: int | None = None
    missing_native_items: int | None = None

    @property
    def row_overhead(self):
        """How many retained row records exist above the logical row count."""
        return self.tracked_native_rows - self.logical_rows


def capture_view_resources(view, *, verify_native=False):
    """Return a read-only summary of a QListView or QTableView.

    This is a diagnostic, not a global Dear PyGui resource census. Backends
    differ in their native child-slot representations; ``native_children``
    counts direct slot-1 rows only when verification is requested. No widget
    content, userdata or opaque metadata is retained in the result.
    """
    from .list import QtListView
    from .table import QtDataGridView

    if isinstance(view, QtDataGridView):
        row_ids = tuple(view._row_tags.values())
        control_ids = tuple(
            tag for cells in view._cell_native_items.values() for tag in cells)
        kind = 'table'
        controller = getattr(view, '_virtual_viewport_controller', None)
        logical_rows = len(controller.rows) if controller is not None else len(view.rows)
        checked = 0
    elif isinstance(view, QtListView):
        row_ids = tuple(view.items.values())
        control_ids = row_ids + tuple(view.checkboxes.values())
        kind = 'list'
        logical_rows = len(view._values)
        checked = len(view.checkboxes)
    else:
        raise TypeError('expected a DearUIQt QListView or QTableView')

    child_count = None
    missing = None
    if verify_native:
        backend = view.backend
        children = backend.get_item_children(view.tag, 1)
        child_count = len(children or ())
        # Query only the IDs this view claims to own. A deleted widget should
        # disappear from the renderer; a missing ID reveals a stale map.
        missing = sum(not backend.does_item_exist(tag)
                      for tag in dict.fromkeys(row_ids + control_ids))
    return ViewResourceSnapshot(
        view_kind=kind,
        logical_rows=logical_rows,
        tracked_native_rows=len(row_ids),
        tracked_controls=len(control_ids),
        checked_controls=checked,
        persistent_editors=len(view._persistent_editors),
        index_widgets=len(view._index_widgets),
        native_children=child_count,
        missing_native_items=missing,
    )


__all__ = ['ViewResourceSnapshot', 'capture_view_resources']


@dataclass(frozen=True)
class ViewMemorySample:
    """Opt-in snapshot; RSS includes *all* process memory, not just the view."""
    resources: ViewResourceSnapshot
    process_rss_bytes: int | None
    sample_time_ns: int


def capture_view_memory(view, *, verify_native=False):
    """Sample retained handles plus process RSS only when explicitly called.

    Process RSS is a coarse upper-level indicator: other windows, the Python
    heap, backend textures and OS allocations contribute.  It must not be
    interpreted as per-widget native memory.  psutil is optional.
    """
    import time
    snapshot = capture_view_resources(view, verify_native=verify_native)
    rss = None
    try:
        import psutil
        rss = int(psutil.Process().memory_info().rss)
    except (ImportError, OSError, RuntimeError, AttributeError):
        pass
    return ViewMemorySample(snapshot, rss, time.monotonic_ns())


@dataclass(frozen=True)
class ViewMemoryDelta:
    logical_rows: int
    native_rows: int
    native_controls: int
    process_rss_bytes: int | None


def compare_view_memory(before: ViewMemorySample, after: ViewMemorySample):
    """Compute simple deltas without retaining or querying native item IDs."""
    a, b = before.resources, after.resources
    rss_delta = (after.process_rss_bytes - before.process_rss_bytes
                 if before.process_rss_bytes is not None and after.process_rss_bytes is not None
                 else None)
    return ViewMemoryDelta(
        b.logical_rows - a.logical_rows,
        b.tracked_native_rows - a.tracked_native_rows,
        b.tracked_controls - a.tracked_controls,
        rss_delta,
    )


__all__ += ['ViewMemorySample', 'ViewMemoryDelta', 'capture_view_memory', 'compare_view_memory']
