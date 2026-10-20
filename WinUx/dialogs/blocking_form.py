from __future__ import annotations

from DearUIQt.backends import dpg
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.dialogs.sizing import compact_message_size
from DearUIQt.widgets import QSpacer


class BlockingDialog(QtDialog):
    REUSABLE_HOST = True
    ASYNC_RESULT_DELAY_MS = 20

    def __init__(self, view, title, message, kind="message", initial="", on_result=None,
                 primary_text=None, secondary_text=None, intent="info"):
        self.kind = str(kind)
        self.on_result = on_result
        self.result = {"done": False, "value": None}
        self.intent = intent
        headings = {"Confirm Close App": "Exit WinUx?",
                    "Warning: Permanent Delete": "Delete permanently?",
                    "Overwrite?": "Replace existing item?"}
        heading = headings.get(title, title)
        # Calculate the size before creating the native window, so the first
        # presented frame is already compact (no oversized/visible resize).
        _, content_height = compact_message_size(
            message, heading=heading, kind=kind, width=480)
        super().__init__(view, title, width=480, height=content_height, compact=True)
        self.preferred_size = (480, content_height)
        role = str(intent or ("question" if kind == "confirm" else "info"))
        self.message_box_body(heading, str(message), intent=role)
        self.entry = None
        if kind == "input":
            QSpacer(parent=self.content, height=2, backend=dpg)
            self.entry = self.line_edit(str(initial or ""), parent=self.content)
            dpg.focus_item(self.entry)
        actions = [(primary_text or "OK", self.accept,
                    "danger" if intent in ("error", "danger", "delete") else "primary", True)]
        if kind != "message":
            actions.append((secondary_text or "Cancel", self._close_from_escape, "secondary", False))
        self.button_box(actions)

    def accept(self):
        self.finish(dpg.get_value(self.entry) if self.entry is not None else True)

    def finish(self, value):
        if self.result["done"]:
            return
        self.result.update(done=True, value=value)
        # Floating root forms stop their child render/event loop as soon as
        # destroy() marks the form closed.  Publish the semantic result first;
        # the parent-side ResultDialog deliberately waits for the later native
        # ``closed`` event before invoking application callbacks.  Scheduling
        # this emit after destroy loses it entirely and, for Confirm Exit,
        # leaves WinUx alive with only a hidden/ghost viewport.
        try:
            if callable(self.on_result):
                self.on_result(value)
        finally:
            self.destroy()

    _window_finished = finish

    def _close_from_escape(self):
        self.finish(False if self.kind == "confirm" else None)

    def destroy(self):
        # Programmatic shutdown also releases synchronous waiters.
        if not self.result["done"]:
            self.result.update(done=True, value=False if self.kind == "confirm" else None)
        super().destroy()

    def wait(self):
        while not self.result["done"] and dpg.is_dearpygui_running() and self.view.winfo_exists():
            self.view.update()
        return self.result["value"]
