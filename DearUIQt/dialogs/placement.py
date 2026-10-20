"""Backend-independent dialog placement primitives.

Coordinates are expressed in the owning backend's window coordinate system.
No desktop/global foreground lookup is allowed: a modal is placed relative to
its *logical* owner, not whichever unrelated application currently has focus.
"""
from __future__ import annotations


def centered_over(owner_rect, child_size, bounds=None):
    """Top-left of *child_size* centered in (x, y, width, height).

    ``bounds`` optionally keeps embedded overlays reachable in their viewport.
    Oversized children still start at the near edge and rely on their scrollable
    body; no child is shrunk or truncated by this placement helper.
    """
    x, y, width, height = (int(value) for value in owner_rect)
    child_width, child_height = (max(1, int(value)) for value in child_size)
    left = x + (width - child_width) // 2
    top = y + (height - child_height) // 2
    if bounds is not None:
        bx, by, bw, bh = (int(value) for value in bounds)
        left = max(bx, min(left, bx + max(0, bw - child_width)))
        top = max(by, min(top, by + max(0, bh - child_height)))
    return left, top
