"""Unified sample count/factor and geometric simplification options."""
from __future__ import annotations

import math

from DearUIQt.dialogs.qt_dialog import QtDialog


class SamplesDialog(QtDialog):
    REUSABLE_HOST = True
    DIALOG_WIDTH = 480
    DIALOG_HEIGHT = 370
    COUNT = "Target sample count"
    SIMPLIFY = "Simplify by error"
    MAX_SAMPLES = 1_000_000

    def __init__(self, view, current_count, *, mode="count", max_error=0.5,
                 on_result=None, parent=None):
        self.current_count = int(current_count)
        self.on_result = on_result
        self.result = {"done": False, "value": None}
        self._syncing = False
        target = (self.current_count * 2 if mode == "increase" else
                  max(2, math.ceil(self.current_count / 2)) if mode == "reduce" else
                  self.current_count)
        super().__init__(view, "Resample Curve", self.DIALOG_WIDTH, self.DIALOG_HEIGHT,
                         compact=True, resizable=False, parent=parent)
        self.preferred_size = (self.DIALOG_WIDTH, self.DIALOG_HEIGHT)
        self.header("Resample Curve", "Increase, reduce or simplify the active curve's points.")
        form = self.form_layout(label_width=135)
        self.operation = self.form_layout_row(form, "Method", lambda host: self.combo(
            [self.COUNT, self.SIMPLIFY], parent=host, width=-1,
            default_value=self.SIMPLIFY if mode == "simplify" else self.COUNT,
            callback=lambda *_: self._validate()))
        self.form_layout_row(form, "Current samples", lambda host: self.note(
            str(self.current_count), parent=host))

        def editor(name, text, callback):
            def build(host):
                widget = self.line_edit_widget(str(text), parent=host, width=-1,
                                               callback=lambda *_: callback())
                setattr(self, name, widget)
                widget.returnPressed.connect(self._accept)
                return widget.tag
            return build

        self.form_layout_row(form, "Target samples", editor(
            "target_editor", target, self._target_changed))
        self.form_layout_row(form, "Count factor (x)", editor(
            "factor_editor", format(target / max(1, self.current_count), '.8g'), self._factor_changed))
        self.form_layout_row(form, "Max error (px)", editor(
            "error_editor", max_error, self._validate))
        self.note("Count and factor stay linked (2 = twice as many, 0.5 = half). "
                  "Reduction preserves endpoints and sharp corners, so the result may exceed the target. "
                  "Simplify uses the error limit instead of a target count.",
                  wrap=self.DIALOG_WIDTH - 48)
        self.error = self.status_text(error=True, wrap=self.DIALOG_WIDTH - 48)
        self.apply_button, self.cancel_button = self.button_box([
            ("Apply", self._accept, "primary", True),
            ("Cancel", lambda: self.finish(None), "secondary", False),
        ])
        self._validate()
        self.set_initial_focus(self.error_editor.tag if mode == "simplify" else self.target_editor.tag)

    @classmethod
    def validate_settings(cls, method, current, target, factor, max_error):
        if current < 2:
            return None, "At least 2 samples are required."
        if method == cls.SIMPLIFY:
            if current < 3:
                return None, "At least 3 samples are required to simplify."
            try:
                error = float(max_error)
                if not math.isfinite(error) or error < 0:
                    raise ValueError
            except (ValueError, TypeError, OverflowError):
                return None, "Max error must be a finite number greater than or equal to 0."
            return {"mode": "simplify", "max_error": error}, ""
        if method != cls.COUNT:
            return None, "Choose a sample method."
        try:
            count = int(str(target).strip(), 10)
            if not 1 <= count <= cls.MAX_SAMPLES:
                raise ValueError
        except (ValueError, TypeError):
            return None, "Target samples must be a whole number from 1 to {:,}.".format(cls.MAX_SAMPLES)
        try:
            ratio = float(factor)
            if not math.isfinite(ratio) or ratio <= 0:
                raise ValueError
        except (ValueError, TypeError, OverflowError):
            return None, "Count factor must be a finite number greater than 0."
        return {"mode": "count", "target": count}, ""

    def _target_changed(self):
        if self._syncing:
            return
        self._syncing = True
        try:
            target = int(self.target_editor.text().strip(), 10)
            self.factor_editor.setText(format(target / max(1, self.current_count), '.8g'))
        except (ValueError, OverflowError):
            pass
        finally:
            self._syncing = False
        self._validate()

    def _factor_changed(self):
        if self._syncing:
            return
        self._syncing = True
        try:
            factor = float(self.factor_editor.text())
            if math.isfinite(factor) and factor > 0:
                self.target_editor.setText(str(max(1, round(self.current_count * factor))))
        except (ValueError, OverflowError):
            pass
        finally:
            self._syncing = False
        self._validate()

    def _validate(self):
        if self._syncing or not hasattr(self, "error"):
            return False
        method = self.control_value(self.operation)
        counting = method == self.COUNT
        self.target_editor.setEnabled(counting)
        self.factor_editor.setEnabled(counting)
        self.error_editor.setEnabled(not counting)
        self._settings, error = self.validate_settings(
            method, self.current_count, self.target_editor.text(),
            self.factor_editor.text(), self.error_editor.text())
        self.set_status_text(self.error, error, error=True)
        if hasattr(self, "apply_button"):
            self.set_control_enabled(self.apply_button, not error)
        return not error

    def _accept(self):
        if self._validate():
            self.finish(self._settings)

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
