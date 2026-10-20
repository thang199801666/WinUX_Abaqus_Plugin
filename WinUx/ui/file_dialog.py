"""Public file-selector facade over the application's folder-browser UI."""
from __future__ import annotations

class FileSelector:
    """One-shot open/save selector, sharing the WinUx folder browser."""

    def __init__(self, *, view, accepted, cancelled=None, extensions=(),
                 directory=False, save=False, default_filename="", initial="",
                 backend=None, width=840, height=540):
        self.view = view
        self.accepted = accepted
        self.cancelled = cancelled
        self.extensions = tuple(extensions or ())
        self.directory = bool(directory)
        self.save = bool(save)
        self.default_filename = str(default_filename or "")
        self.initial = str(initial or "")
        self.width, self.height = int(width), int(height)
        self.dialog = None
        self.tag = None

    def _result(self, path):
        self.tag = None
        if path:
            if callable(self.accepted):
                self.accepted(path)
        elif callable(self.cancelled):
            self.cancelled()

    def open(self):
        self.close()
        if getattr(self.view, "use_native_file_selectors", False):
            from ..dialogs.floating_adapters import LocalFileDialog as FloatingFileDialog
            from ..dialogs.floating_adapters import LocalFolderDialog as FloatingFolderDialog
            if self.directory:
                self.dialog = FloatingFolderDialog(self.view, self.initial, self._result)
                self.dialog._notify_cancel = True
            else:
                self.dialog = FloatingFileDialog(
                    self.view, self.initial, self._result, extensions=self.extensions,
                    save=self.save, default_filename=self.default_filename,
                    width=self.width, height=self.height)
            return self.dialog
        # Normal path: one QApplication/context/event loop. DearUIQt will use a
        # native owned window when the multi-window backend is available and an
        # in-viewport modal otherwise; neither variant starts a helper process.
        from ..dialogs import inprocess_adapters
        if self.directory:
            self.dialog = inprocess_adapters.LocalFolderDialog(
                self.view, self.initial, self._result)
        else:
            self.dialog = inprocess_adapters.LocalFileDialog(
                self.view, self.initial, self._result, extensions=self.extensions,
                save=self.save, default_filename=self.default_filename,
                width=self.width, height=self.height)
        self.tag = self.dialog.tag
        self.dialog.width, self.dialog.height = self.width, self.height
        self.dialog.preferred_size = (self.width, self.height)
        self.dialog.center()
        return self.tag

    def close(self):
        if self.dialog is not None:
            self.dialog.destroy()
            self.dialog = None
        self.tag = None


FileDialog = FileSelector

__all__ = ["FileSelector", "FileDialog"]
