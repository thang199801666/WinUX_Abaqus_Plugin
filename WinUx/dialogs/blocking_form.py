from __future__ import annotations

from DearUIQt.backends import dpg
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.dialogs.sizing import compact_message_size
from DearUIQt.core import QEventLoop
from DearUIQt.gui import QFontMetrics
from DearUIQt.widgets import QSpacer


class BlockingDialog(QtDialog):
    REUSABLE_HOST = True
    ASYNC_RESULT_DELAY_MS = 20

    def __init__(self, view, title, message, kind="message", initial="", on_result=None,
                 primary_text=None, secondary_text=None, intent="info",
                 option_text=None, option_checked=False, parent=None):
        self.kind = str(kind)
        self.on_result = on_result
        self.result = {"done": False, "value": None}
        self._wait_loop = None
        self.intent = intent
        headings = {"Confirm Close App": "Exit WinUx?",
                    "Warning: Permanent Delete": "Delete permanently?",
                    "Overwrite?": "Replace existing item?"}
        heading = headings.get(title, title)
        # Calculate the size before creating the native window, so the first
        # presented frame is already compact (no oversized/visible resize).
        body_metrics = QFontMetrics(getattr(view, "body_qfont", None))
        heading_metrics = QFontMetrics(getattr(view, "heading_qfont", None))
        dialog_width, content_height = compact_message_size(
            message, heading=heading, kind=kind, width=None,
            body_metrics=body_metrics, heading_metrics=heading_metrics)
        if option_text:
            content_height += 30
        # Use the normal native QtDialog path, exactly like SSH Login.  An
        # embedded ImGui modal is not a substitute for a proper owned window:
        # it changes backdrop, input capture, and the message-box chrome.
        super().__init__(
            view, title, width=dialog_width, height=content_height, compact=True,
            resizable=False, parent=parent,
        )
        self.preferred_size = (dialog_width, content_height)
        # QMessageBox/QInputDialog-style surfaces are content-sized. Their body
        # must not expose a scrollbar merely because renderer row spacing is a
        # few pixels larger than the precomputed font metrics.
        dpg.configure_item(
            self.content, no_scrollbar=True, no_scroll_with_mouse=True)
        role = str(intent or ("question" if kind == "confirm" else "info"))
        self.message_box_body(heading, str(message), intent=role)
        self.entry = None
        self.option_checkbox = None
        if kind == "input":
            QSpacer(parent=self.content, height=2, backend=dpg)
            self.entry = self.line_edit(str(initial or ""), parent=self.content)
            dpg.focus_item(self.entry)
        if option_text:
            QSpacer(parent=self.content, height=3, backend=dpg)
            self.option_checkbox = self.checkbox(
                str(option_text), checked=bool(option_checked), parent=self.content)
        actions = [(primary_text or "OK", self.accept,
                    "danger" if intent in ("error", "danger", "delete") else "primary", True)]
        if kind != "message":
            actions.append((secondary_text or "Cancel", self._close_from_escape, "secondary", False))
        self.button_box(actions)
        self._compact_fit_attempts = 0
        after_render = getattr(self.view, "after_render", None)
        if callable(after_render):
            after_render(self._fit_compact_body)
        else:
            self.view.after(0, self._fit_compact_body)

    def _fit_compact_body(self):
        """Grow a compact dialog to its rendered body before allowing scrolling.

        Font metrics provide the first-frame size hint, while this post-render
        pass absorbs backend/table spacing that cannot be known before layout.
        A scrollbar is enabled only when the message is genuinely taller than
        the available viewport cap.
        """
        if not self.winfo_exists():
            return False
        self._compact_fit_attempts = int(getattr(self, "_compact_fit_attempts", 0)) + 1
        try:
            overflow = max(0.0, float(dpg.get_y_scroll_max(self.content)))
        except Exception:
            overflow = 0.0
        if overflow <= 1.0:
            try:
                dpg.configure_item(self.content, no_scrollbar=True, no_scroll_with_mouse=True)
            except Exception:
                pass
            return True
        try:
            viewport_height = int(dpg.get_viewport_client_height())
        except Exception:
            viewport_height = 700
        max_height = max(220, min(620, viewport_height - 72))
        current_height = max(1, int(getattr(self, "height", self.preferred_size[1])))
        target_height = min(max_height, current_height + int(overflow + 0.999) + 8)
        if target_height > current_height:
            self.setFixedSize(self.width, target_height)
            self.preferred_size = (self.width, target_height)
            if self._compact_fit_attempts < 3:
                after_render = getattr(self.view, "after_render", None)
                if callable(after_render):
                    after_render(self._fit_compact_body)
                else:
                    self.view.after(0, self._fit_compact_body)
            return True
        # Only truly oversized messages should scroll.
        try:
            dpg.configure_item(self.content, no_scrollbar=False, no_scroll_with_mouse=False)
        except Exception:
            pass
        return False

    def accept(self):
        if self.entry is not None:
            value = dpg.get_value(self.entry)
        elif self.option_checkbox is not None:
            value = {
                "accepted": True,
                "checked": bool(dpg.get_value(self.option_checkbox)),
            }
        else:
            value = True
        self.finish(value)

    def finish(self, value):
        if self.result["done"]:
            return
        self.result.update(done=True, value=value)
        wait_loop = self._wait_loop
        if wait_loop is not None and wait_loop.isRunning():
            wait_loop.quit()
        # In-process confirmations must commit their visual/modal teardown
        # *before* invoking application callbacks.  Confirm Exit immediately
        # tears down QApplication/the dispatcher; calling that callback while
        # this dialog is still visible leaves its native surface alive for one
        # extra turn after the main viewport disappears.  destroy() queues the
        # visual deletion first, then the result callback is queued behind it.
        # Process-isolated dialogs use ui.hosting.ResultDialog instead and keep
        # their own native-close/result ordering contract.
        callback = self.on_result if callable(self.on_result) else None
        self.destroy()
        if callback is not None:
            after_render = getattr(self.view, "after_render", None)
            if callable(after_render):
                after_render(callback, value)
            else:
                self.view.after(0, callback, value)

    _window_finished = finish

    def _close_from_escape(self):
        self.finish(False if self.kind == "confirm" else None)

    def destroy(self):
        # Programmatic shutdown also releases synchronous waiters.
        if not self.result["done"]:
            self.result.update(done=True, value=False if self.kind == "confirm" else None)
        wait_loop = self._wait_loop
        if wait_loop is not None and wait_loop.isRunning():
            wait_loop.quit()
        super().destroy()

    def wait(self):
        if self.result["done"]:
            return self.result["value"]
        loop = QEventLoop()
        self._wait_loop = loop
        try:
            loop.exec()
        finally:
            if self._wait_loop is loop:
                self._wait_loop = None
            loop.delete()
        return self.result["value"]
