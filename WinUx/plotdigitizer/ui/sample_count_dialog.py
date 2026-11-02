"""Target sample-count prompt for Plot Digitizer Increase/Reduce commands."""
from __future__ import annotations

from DearUIQt.dialogs.qt_dialog import QtDialog


class SampleCountDialog(QtDialog):
    """Compact validated integer textbox for count-based resampling."""

    REUSABLE_HOST = True
    DIALOG_WIDTH = 420
    DIALOG_HEIGHT = 230

    def __init__(self, view, mode: str, current_count: int, on_result=None, parent=None):
        mode = str(mode or "").strip().lower()
        if mode not in ("increase", "reduce"):
            raise ValueError("mode must be 'increase' or 'reduce'")
        self.mode = mode
        self.current_count = max(1, int(current_count))
        self.on_result = on_result
        self.result = {"done": False, "value": None}

        title = "Increase Samples" if mode == "increase" else "Reduce Samples"
        description = (
            "Enter the desired total number of samples. New samples are inserted along the current curve."
            if mode == "increase" else
            "Enter the desired total number of samples. Important endpoints and curve features are preserved."
        )
        QtDialog.__init__(self, view, title, self.DIALOG_WIDTH, self.DIALOG_HEIGHT, compact=True,
                          resizable=False, parent=parent)
        self.preferred_size = (self.DIALOG_WIDTH, self.DIALOG_HEIGHT)
        self.header(title, description)

        form = self.form_layout(label_width=118)
        self.current_value = self.form_layout_row(
            form, "Current samples", lambda parent: self.note(str(self.current_count), parent=parent))
        def build_target_editor(parent):
            self.target_editor = self.line_edit_widget(
                str(self.current_count), parent=parent, width=-1,
                callback=lambda *_args: self._validate())
            return self.target_editor.tag

        self.form_layout_row(form, "Target samples", build_target_editor)

        self.error = self.status_text(error=True, wrap=self.DIALOG_WIDTH - 48)
        self.apply_button, self.cancel_button = self.button_box([
            ("Apply", self._accept, "primary", True),
            ("Cancel", lambda: self.finish(None), "secondary", False),
        ])
        self.target_editor.returnPressed.connect(self._accept)
        self._validate()
        try:
            self.target_editor.setFocus()
            self.target_editor.selectAll()
        except Exception:
            pass

    @staticmethod
    def validate_target(mode: str, current_count: int, raw_value):
        """Return ``(target, error)`` for a user-entered count."""
        mode = str(mode or "").strip().lower()
        current = max(1, int(current_count))
        text = str(raw_value if raw_value is not None else "").strip()
        if not text:
            return None, "Enter a target sample count."
        try:
            target = int(text, 10)
        except (TypeError, ValueError):
            return None, "Sample count must be a whole number."
        if target < 1:
            return None, "Sample count must be at least 1."
        if mode == "increase" and target < current:
            return None, "Increase target cannot be smaller than the current count ({}).".format(current)
        if mode == "reduce" and target > current:
            return None, "Reduce target cannot be larger than the current count ({}).".format(current)
        if mode not in ("increase", "reduce"):
            return None, "Unknown sample operation."
        return target, ""

    def _validate(self):
        target, error = self.validate_target(
            self.mode, self.current_count, self.control_value(self.target_editor, ""))
        self._validated_target = target
        self.set_status_text(self.error, error, error=True)
        if hasattr(self, "apply_button"):
            self.set_control_enabled(self.apply_button, not error)
        return not error

    def _accept(self):
        if not self._validate():
            return
        self.finish(self._validated_target)

    def finish(self, value):
        if self.result["done"]:
            return
        self.result.update(done=True, value=value)
        try:
            if callable(self.on_result):
                self.on_result(value)
        finally:
            self.destroy()

    _window_finished = finish

    def _close_from_escape(self):
        self.finish(None)
