from __future__ import annotations

import dearpygui.dearpygui as dpg
from .qt_dialog import QtDialog


class BlockingDialog(QtDialog):
    ASYNC_RESULT_DELAY_MS = 20

    def __init__(self, view, title, message, kind="message", initial="", on_result=None,
                 primary_text=None, secondary_text=None, intent="info"):
        self.kind = str(kind)
        self.on_result = on_result
        self.result = {"done": False, "value": None}
        self.intent = intent
        super().__init__(view, title, width=500, height=220)
        lines = sum(max(1, (len(line) + 64)//65) for line in str(message).splitlines() or [""])
        self.preferred_size = (480, max(160, min(282, 118 + 17*lines + (36 if kind == "input" else 0))))
        headings = {"Confirm Close App": "Exit WinUx?",
                    "Warning: Permanent Delete": "Delete permanently?",
                    "Overwrite?": "Replace existing item?"}
        role = str(intent or ("question" if kind == "confirm" else "info"))
        self.message_box_body(headings.get(title, title), str(message), intent=role)
        self.entry = None
        if kind == "input":
            dpg.add_spacer(parent=self.content, height=2)
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
