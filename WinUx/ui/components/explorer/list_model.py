"""Data and formatting primitives shared by the Explorer list view.

This module intentionally has no Dear PyGui dependency.  Keeping row data and
default configuration separate from rendering makes them safe to reuse in
controllers, tests, and future view implementations.
"""

from __future__ import annotations

import os
import stat
from datetime import datetime
from ....services.file_types import file_type_name


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

# Optional file details share the existing header column chooser. Keep the
# familiar four-column view unchanged until the user explicitly enables them.
EXTRA_FILE_COLUMNS = (
    ("permissions", "Permissions", 1.4),
    ("owner", "Owner", 0.8),
    ("group", "Group", 0.8),
    ("extension", "Extension", 0.7),
    ("created", "Date created", 1.15),
    ("accessed", "Date accessed", 1.15),
    ("attributes", "Attributes", 1.1),
    ("path", "Full path", 2.0),
)
DEFAULT_COLUMNS += [dict(key=key, label=label, weight=weight, align="left",
                         valign="middle", visible=False)
                    for key, label, weight in EXTRA_FILE_COLUMNS]

FILE_METADATA_KEYS = ("mode", "uid", "gid", "accessed", "created", "attributes", "owner_name", "group_name", "is_symlink")


def file_detail_value(item, key):
    """Format listing metadata only; never probe a file or SSH from paint."""
    if item._detail_text is None:
        item._detail_text = {}
    if key not in item._detail_text:
        item._detail_text[key] = _format_file_detail(item, key)
    return item._detail_text[key]


def _format_file_detail(item, key):
    if item.data.get("parent"):
        return ""
    if key == "extension":
        return "" if item.is_dir else item.extension
    if key == "path":
        return str(item.data.get("path") or item.path or "")
    if key in ("owner", "group"):
        name = item.data.get('owner_name' if key == 'owner' else 'group_name')
        if name:
            return str(name)
        value = item.data.get("uid" if key == "owner" else "gid")
        return str(value) if value is not None else ""
    if key == "permissions":
        mode = item.data.get("mode")
        return "{} ({:04o})".format(stat.filemode(mode), stat.S_IMODE(mode)) if mode is not None else ""
    if key in ("created", "accessed"):
        value = item.data.get(key)
        if value is None:
            return ""
        try:
            return datetime.fromtimestamp(value).strftime("%m/%d/%Y %I:%M %p")
        except (OSError, OverflowError, ValueError):
            return ""
    if key == "attributes":
        value = item.data.get("attributes")
        if value is None:
            return ""
        flags = ((0x01, "Read-only"), (0x02, "Hidden"), (0x04, "System"),
                 (0x20, "Archive"), (0x100, "Temporary"), (0x200, "Sparse"),
                 (0x400, "Reparse point"), (0x800, "Compressed"),
                 (0x1000, "Offline"), (0x2000, "Not indexed"), (0x4000, "Encrypted"))
        return ", ".join(label for mask, label in flags if value & mask)
    return ""


def file_detail_sort_value(item, key):
    if key in ('owner', 'group') and item.data.get('owner_name' if key == 'owner' else 'group_name'):
        return (2, file_detail_value(item, key).casefold())
    if key in ("owner", "group", "created", "accessed", "permissions", "attributes"):
        field = {"owner": "uid", "group": "gid", "permissions": "mode"}.get(key, key)
        value = item.data.get(field)
        return (value is not None, value if value is not None else 0)
    return file_detail_value(item, key).casefold()

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
        "_detail_text",
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
        self.item_type = item_type or file_type_name(name, is_dir)
        self.data = data or {}
        self.refresh_display_cache()


    def refresh_display_cache(self):
        """Pre-format immutable row text used by every layout pass.

        Directory refreshes and column resizing can call the renderer many
        times per second.  Date formatting and byte-unit conversion are pure
        functions of the row metadata, so compute them only when that metadata
        changes instead of once per visible cell per layout.
        """
        self._detail_text = None
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
        return file_type_name(name)

    @classmethod
    def from_path(cls, full_path):
        is_dir = os.path.isdir(full_path)
        try:
            info = os.stat(full_path, follow_symlinks=False)
            size = 0 if is_dir else info.st_size
            mtime = info.st_mtime
            metadata = dict(
                mode=info.st_mode if os.name != "nt" else None,
                uid=getattr(info, "st_uid", None) if os.name != "nt" else None,
                gid=getattr(info, "st_gid", None) if os.name != "nt" else None,
                accessed=info.st_atime,
                created=getattr(info, "st_birthtime", info.st_ctime if os.name == "nt" else None),
                attributes=getattr(info, "st_file_attributes", None))
            metadata['is_symlink'] = stat.S_ISLNK(info.st_mode)
        except OSError:
            size, mtime, metadata = 0, 0.0, {}
        return cls(os.path.basename(full_path), full_path, is_dir, size, mtime, data=metadata)


__all__ = [
    "DEFAULT_COLUMNS",
    "DEFAULT_ITEM_MENU",
    "ListViewItem",
    "human_size",
]
