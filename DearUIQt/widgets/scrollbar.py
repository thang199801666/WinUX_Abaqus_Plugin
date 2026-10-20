"""Qt-style scrollbar control.

The current backend renders QScrollBar with the same native integer-slider
primitive used by QSlider.  State and signals live in QAbstractSlider, so
application code remains independent from the renderer choice.
"""
from __future__ import annotations

from ..core.object import Qt
from .sliders import QSlider


class QScrollBar(QSlider):
    def __init__(self, orientation=Qt.Vertical, *, parent=None, after=None,
                 backend=None, minimum=0, maximum=99, value=0,
                 single_step=1, page_step=10, width=None, height=None):
        super().__init__(
            orientation=orientation, parent=parent, after=after, backend=backend,
            minimum=minimum, maximum=maximum, value=value,
            single_step=single_step, page_step=page_step,
            width=(-1 if width is None else width), height=height,
        )

    def setSliderPosition(self, position):
        super().setSliderPosition(position)


__all__ = ["QScrollBar"]
