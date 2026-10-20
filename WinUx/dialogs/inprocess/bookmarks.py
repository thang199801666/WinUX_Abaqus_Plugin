from __future__ import annotations

from ..bookmarks_form import BookmarksDialog as BookmarksForm
from .common import RetainedTool


class BookmarksDialog(RetainedTool, BookmarksForm):
    def __init__(self, view, entries, on_open, on_remove, on_rename):
        BookmarksForm.__init__(self, view, entries, on_open, on_remove, on_rename)
        self._init_inprocess_lifetime(view)

    def refresh(self, entries, on_open=None, on_remove=None, on_rename=None):
        if on_open is not None:
            self._on_open = on_open
        if on_remove is not None:
            self._on_remove = on_remove
        if on_rename is not None:
            self._on_rename = on_rename
        return BookmarksForm.refresh(self, entries)
