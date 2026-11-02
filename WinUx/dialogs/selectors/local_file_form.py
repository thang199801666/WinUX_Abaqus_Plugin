"""File policy over the same local-path browser used by folder selection."""
from __future__ import annotations

from .local_folder_form import LocalPathDialog


class LocalFileDialog(LocalPathDialog):
    """Open one/many files, or save one file, using the shared browser."""

    def __init__(self, view, initial, on_result, *, extensions=(), save=False,
                 default_filename="", multiple=False, show_hidden=False, title=None):
        super().__init__(
            view, initial, on_result, selection_kind="file", multiple=multiple,
            extensions=extensions, save=save, default_filename=default_filename,
            show_hidden=show_hidden, title=title)
