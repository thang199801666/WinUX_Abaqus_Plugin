"""Immutable rows shared by the filesystem, SSH, and UI layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from ..services.file_types import file_type_name


@dataclass(frozen=True)
class FileItem:
    name: str
    path: Path
    is_dir: bool
    size: int
    modified: float
    is_hidden: bool = False
    mode: int | None = None
    uid: int | None = None
    gid: int | None = None
    accessed: float | None = None
    created: float | None = None
    attributes: int | None = None
    owner_name: str = ""
    group_name: str = ""
    is_symlink: bool = False

    @property
    def type_text(self) -> str:
        return file_type_name(self.name, self.is_dir)

    @property
    def size_text(self) -> str:
        if self.is_dir:
            return ""
        value = float(self.size)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                return (
                    "{:,} B".format(int(value))
                    if unit == "B"
                    else "{:,.1f} {}".format(value, unit)
                )
            value /= 1024
        return str(self.size)

    @property
    def modified_text(self) -> str:
        return datetime.fromtimestamp(self.modified).strftime(
            "%d/%m/%Y %H:%M")


@dataclass(frozen=True)
class JobItem:
    """A PBS job row displayed by the server job viewer."""

    job_id: str
    name: str
    user: str
    tokens: str
    status: str
    elapsed: str
