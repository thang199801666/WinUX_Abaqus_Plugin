"""Data and formatting primitives shared by the Explorer list view.

This module intentionally has no Dear PyGui dependency.  Keeping row data and
default configuration separate from rendering makes them safe to reuse in
controllers, tests, and future view implementations.
"""

from __future__ import annotations

import os


def human_size(n):
    """Format a byte count using the compact units shown by the list view."""
    if n is None or n < 0:
        return ""
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0:
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


DEFAULT_COLUMNS = [
    dict(
        key="name",
        label="Name",
        align="left",
        valign="middle",
        weight=2.6,
        visible=True,
    ),
    dict(
        key="date",
        label="Date modified",
        align="left",
        valign="middle",
        weight=1.15,
        visible=True,
    ),
    dict(
        key="type",
        label="Type",
        align="center",
        valign="middle",
        weight=0.95,
        visible=True,
    ),
    dict(
        key="size",
        label="Size",
        align="right",
        valign="middle",
        weight=0.7,
        visible=True,
    ),
]

_ALIGN_X = {"left": 0.0, "center": 0.5, "right": 1.0}
_ALIGN_Y = {"top": 0.0, "middle": 0.5, "bottom": 1.0}

DEFAULT_ITEM_MENU = [
    ("Open", "open"),
    ("---", None),
    ("Cut", "cut"),
    ("Copy", "copy"),
    ("Paste", "paste"),
    ("---", None),
    ("Rename", "rename"),
    ("Delete", "delete"),
    ("---", None),
    ("Properties", "properties"),
]


class ListViewItem:
    """Lightweight row data holder for a file, folder, or arbitrary item."""

    __slots__ = (
        "name",
        "path",
        "is_dir",
        "size",
        "mtime",
        "item_type",
        "extension",
        "data",
        "_date_text",
        "_size_text",
        "_name_sort",
        "_type_sort",
    )

    def __init__(
        self,
        name,
        path="",
        is_dir=False,
        size=0,
        mtime=0.0,
        item_type=None,
        data=None,
    ):
        self.name = name
        self.path = path
        self.is_dir = is_dir
        self.size = size
        self.mtime = mtime
        self.extension = os.path.splitext(name)[1]
        self.item_type = item_type or (
            "File folder" if is_dir else self._guess_type(name)
        )
        self.data = data or {}
        self.refresh_display_cache()


    def refresh_display_cache(self):
        """Pre-format immutable row text used by every layout pass.

        Directory refreshes and column resizing can call the renderer many
        times per second.  Date formatting and byte-unit conversion are pure
        functions of the row metadata, so compute them only when that metadata
        changes instead of once per visible cell per layout.
        """
        self._name_sort = str(self.name or "").casefold()
        self._type_sort = str(self.item_type or "").casefold()
        if self.mtime:
            from datetime import datetime
            self._date_text = datetime.fromtimestamp(self.mtime).strftime(
                "%m/%d/%Y %I:%M %p")
        else:
            self._date_text = ""
        self._size_text = "" if self.is_dir else human_size(self.size)
        return self

    @property
    def cached_date_text(self):
        return self._date_text

    @property
    def cached_size_text(self):
        return self._size_text

    @property
    def cached_name_sort(self):
        return self._name_sort

    @property
    def cached_type_sort(self):
        return self._type_sort

    @staticmethod
    def _guess_type(name):
        ext = os.path.splitext(name)[1]
        return f"{ext[1:].upper()} File" if ext else "File"

    @classmethod
    def from_path(cls, full_path):
        is_dir = os.path.isdir(full_path)
        try:
            size = 0 if is_dir else os.path.getsize(full_path)
        except OSError:
            size = 0
        try:
            mtime = os.path.getmtime(full_path)
        except OSError:
            mtime = 0.0
        return cls(os.path.basename(full_path), full_path, is_dir, size, mtime)


__all__ = [
    "DEFAULT_COLUMNS",
    "DEFAULT_ITEM_MENU",
    "ListViewItem",
    "human_size",
]
