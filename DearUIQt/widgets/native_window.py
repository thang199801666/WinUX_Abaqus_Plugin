"""Independent native top-levels sharing the application's renderer context."""
from __future__ import annotations

from .windows import QMainWindow
from ..core.object import QObject
from ..backends import get_backend
from ..backends.native_windows import NativeWindowBackend


class QNativeWindow(QMainWindow):
    """A real OS top-level, not a child process or a main-viewport overlay.

    Ownership and modality are native-window policy; QObject/widget lifetime
    remains in this process. Enable the runtime's native windows before use.
    """

    def __init__(self, title="", *, owner=None, modal=False, backend=None, **kwargs):
        backend = get_backend() if backend is None else backend
        native = NativeWindowBackend(backend)
        native.require()
        if not native.isEnabled():
            raise RuntimeError("Enable native windows on QGuiRuntime before constructing a QNativeWindow")
        super().__init__(title, backend=backend, **kwargs)
        self._native_window_backend = native
        self._native_owner = owner
        self._native_modal = bool(modal)
        try:
            native.configure(self, owner=owner, modal=modal)
            self.backend.configure_item(self.tag, on_close=self._native_close_requested)
            if isinstance(owner, QObject):
                self.setParent(owner)
        except Exception:
            self.delete()
            raise

    def _native_close_requested(self, *_args):
        # The platform close button changes the renderer's show flag first.
        # Route it through QWidget's close event so retained state, child
        # visibility and WA_DeleteOnClose follow the same contract as close().
        if not self.close() and not self._deleted:
            self.backend.show_item(self.tag)

    def winId(self):
        """Return this window's HWND, or zero before its first rendered frame."""
        self._require_ui()
        return self._native_window_backend.winId(self)

    def isWindowModal(self):
        return self._native_modal
