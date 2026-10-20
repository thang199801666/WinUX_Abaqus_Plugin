"""Layout spacer compatibility type."""
from __future__ import annotations

from ..widgets.primitives import QSpacer


class QSpacerItem(QSpacer):
    """Pragmatic retained QSpacerItem.

    DearUIQt layouts are retained native containers, so the spacer owns one
    backend item while exposing Qt's ``changeSize``/size-hint behavior.
    """


__all__ = ["QSpacerItem"]
