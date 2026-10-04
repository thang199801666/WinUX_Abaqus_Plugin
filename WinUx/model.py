"""Backward-compatible model imports.

New code should import from :mod:`WinUx.models`.  This module remains because
existing plug-ins and tests import ``WinUx.model`` directly.
"""

from .models import FileItem, FileSystemModel, JobItem

__all__ = ["FileItem", "FileSystemModel", "JobItem"]
