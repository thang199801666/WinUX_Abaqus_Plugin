"""Immutable rows shared by the filesystem, SSH, and UI layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class FileItem:
    name: str
    path: Path
    is_dir: bool
    size: int
    modified: float

    @property
    def type_text(self) -> str:
        if self.is_dir:
            return "File folder"
        suffix = self.path.suffix.lstrip(".").upper()
        return (suffix + " file") if suffix else "File"

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
