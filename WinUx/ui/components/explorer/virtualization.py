"""Pure row-window math for ExplorerListView virtualization."""
from __future__ import annotations

import math


def compute_render_window(item_count, row_height, scroll_y, viewport_height,
                          threshold=240, overscan=8, fallback_rows=64):
    """Return the half-open logical row interval that should be materialized.

    Small lists retain the historical full-render behavior.  Large lists render
    only the viewport plus an overscan margin.  During startup, before Dear
    PyGui exposes a usable viewport height, a bounded first-page fallback keeps
    native object creation deterministic.
    """
    count = max(0, int(item_count))
    if count == 0:
        return (0, 0)
    if count < max(1, int(threshold)):
        return (0, count)

    row = max(1.0, float(row_height))
    over = max(0, int(overscan))
    view = max(0.0, float(viewport_height or 0.0))
    scroll = max(0.0, float(scroll_y or 0.0))

    if view <= 1.0:
        return (0, min(count, max(1, int(fallback_rows))))

    first_visible = min(count - 1, max(0, int(math.floor(scroll / row))))
    last_visible = min(count, int(math.ceil((scroll + view) / row)))
    start = max(0, first_visible - over)
    end = min(count, max(start + 1, last_visible + over))
    return (start, end)
