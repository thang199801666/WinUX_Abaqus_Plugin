"""Top-level reusable tool-window facade for retained Dear ImGui UI."""
from __future__ import annotations

from .backends import dpg
from contextlib import contextmanager

from .dialogs.qt_dialog import QtDialog, _DIALOGS
from .core.object import QEvent
from .dialogs.base import register_escape_target, unregister_escape_target


class ToolWindow(QtDialog):
    """Reusable Qt-style tool surface.

    Embedded tools retain the normal ``QtDialog`` lifecycle.  Detached
    tools running in their own DearPyGui context use a standalone lifecycle
    that deliberately does *not* enter the shared modal/input registry.  This is
    essential: that registry exists to block click-through into a host application
    viewport and must never gate the only window in an independent process.
    """

    def __init__(self, view, title, width=900, height=640, *, footer=True):
        self._standalone_surface = bool(getattr(view, "is_standalone_ui_host", False))
        super().__init__(view, title, width, height, modal=False, footer=footer)

    def show(self):
        if not getattr(self, "_standalone_surface", False):
            return super().show()
        if not self.winfo_exists():
            return False
        # No register_modal_window() here. The root tool surface is the sole
        # interactive content of its own native viewport/process.
        register_escape_target(self.tag, self.reject)
        if self in _DIALOGS:
            _DIALOGS.remove(self)
            _DIALOGS.append(self)
        try:
            already_visible = bool(dpg.is_item_shown(self.tag))
        except Exception:
            already_visible = False
        if not already_visible:
            dpg.show_item(self.tag)
            self.sendEvent(QEvent(QEvent.Show))
        try:
            dpg.focus_item(self.tag)
        except Exception:
            pass
        self.view.after(0, self._focus_initial)
        return True

    def raise_(self):
        return self.show()

    lift = raise_

    def activateWindow(self):
        if not getattr(self, "_standalone_surface", False):
            return super().activateWindow()
        if not self.winfo_exists():
            return False
        register_escape_target(self.tag, self.reject)
        try:
            dpg.focus_item(self.tag)
            return True
        except Exception:
            return False

    activate = activateWindow
    focus = activateWindow
    setFocus = activateWindow

    def hide(self):
        if not getattr(self, "_standalone_surface", False):
            return super().hide()
        if not self.winfo_exists():
            return False
        try:
            if not dpg.is_item_shown(self.tag):
                return False
        except Exception:
            pass
        dpg.hide_item(self.tag)
        unregister_escape_target(self.tag)
        self.sendEvent(QEvent(QEvent.Hide))
        return True

    @contextmanager
    def disclosure(self, title, parent=None, *, open=False):
        """Shared compact expandable area for less frequently used controls."""
        with dpg.collapsing_header(label=title, parent=parent or self.content,
                                   default_open=bool(open)) as section:
            with dpg.group(parent=section) as content:
                yield content


QToolWindow = ToolWindow

__all__ = ["ToolWindow", "QToolWindow"]
