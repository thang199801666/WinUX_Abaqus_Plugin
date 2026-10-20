"""Reusable popup color picker with a Qt-style hexadecimal editor."""
from ..backends import dpg

from .widget import QWidget
from ..layouts.box import QHBoxLayout
from .editors import QLineEdit
from ..core.object import Signal
from ..dialogs.theme import DialogMetrics


class ColorField(QWidget):
    def __init__(self, parent, *, after=None, backend=dpg):
        backend, options = self._construction(parent, backend)
        tag = backend.add_group(**options)
        super().__init__(tag, parent=parent, after=after, backend=backend)
        self.box_layout = QHBoxLayout(parent=self, after=after, backend=backend, spacing=6)
        self.setLayout(self.box_layout)
        self.changed = Signal(self)
        self._value = None
        self._enabled = True
        self.swatch = backend.add_color_edit(
            parent=self.box_layout.tag, default_value=(180, 180, 180, 255), no_alpha=True,
            no_inputs=True, no_label=True, no_options=True, no_picker=False,
            display_mode=backend.mvColorEdit_hex, display_type=backend.mvColorEdit_uint8,
            width=DialogMetrics.CONTROL_HEIGHT, height=DialogMetrics.CONTROL_HEIGHT,
            callback=self._picked)
        self.editor = QLineEdit("", parent=self.box_layout, after=after, backend=backend,
                                width=100, hint="#RRGGBB", on_enter=True,
                                callback=self._edited)

    def _edited(self, _sender, value, *_args):
        if self._enabled:
            self.changed.emit(str(value).strip())

    def _picked(self, _sender, value, *_args):
        if not self._enabled:
            return
        rgb = tuple(max(0, min(255, round(float(channel)))) for channel in value[:3])
        self.setColor(rgb)
        self.changed.emit("#{:02X}{:02X}{:02X}".format(*rgb))

    def setEnabled(self, enabled=True):
        self._enabled = bool(enabled)
        self.editor.setEnabled(self._enabled)
        self.backend.configure_item(self.swatch, enabled=self._enabled)
        return self

    def setColor(self, rgb):
        self._value = rgb
        self.backend.set_value(self.swatch, (*rgb, 255) if rgb is not None else (180, 180, 180, 255))
        self.editor.setText("#{:02X}{:02X}{:02X}".format(*rgb) if rgb is not None else "")



QColorField = ColorField

__all__ = ["ColorField", "QColorField"]
