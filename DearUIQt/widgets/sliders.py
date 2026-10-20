"""Qt-style abstract slider and slider controls backed by Dear ImGui."""
from __future__ import annotations

from ..core.object import Qt, Signal
from .widget import QWidget
from ..gui.style import bind_theme, slider_theme
from ._utils import _bind_focus_state_handlers, _delete_aux_item


class QAbstractSlider(QWidget):
    """Retained subset of Qt's QAbstractSlider contract.

    The class owns range/value/action state while concrete controls choose the
    native renderer.  Keeping this behavior in DearUIQt prevents WinUx feature
    widgets from reaching into ``dpg.get_value``/``configure_item`` directly.
    """

    SliderNoAction = 0
    SliderSingleStepAdd = 1
    SliderSingleStepSub = 2
    SliderPageStepAdd = 3
    SliderPageStepSub = 4
    SliderToMinimum = 5
    SliderToMaximum = 6
    SliderMove = 7

    def __init__(self, tag, *, orientation=Qt.Horizontal, minimum=0, maximum=99,
                 value=0, single_step=1, page_step=10, parent=None, after=None,
                 backend=None):
        super().__init__(tag, parent=parent, after=after, backend=backend)
        self.valueChanged = Signal(self)
        self.sliderPressed = Signal(self)
        self.sliderMoved = Signal(self)
        self.sliderReleased = Signal(self)
        self.rangeChanged = Signal(self)
        self.actionTriggered = Signal(self)
        self._orientation = int(orientation)
        self._minimum = int(minimum)
        self._maximum = int(maximum)
        self._single_step = max(1, int(single_step))
        self._page_step = max(1, int(page_step))
        self._tracking = True
        self._inverted_appearance = False
        self._inverted_controls = False
        self._slider_down = False
        self._slider_position = self._clamp(value)
        self._properties.update(value=self._slider_position, enabled=True)

    def _clamp(self, value):
        return max(self._minimum, min(self._maximum, int(value)))

    def orientation(self):
        return self._orientation

    def minimum(self):
        return self._minimum

    def maximum(self):
        return self._maximum

    def setMinimum(self, minimum):
        self.setRange(minimum, self._maximum)

    def setMaximum(self, maximum):
        self.setRange(self._minimum, maximum)

    def setRange(self, minimum, maximum):
        minimum, maximum = int(minimum), int(maximum)
        if maximum < minimum:
            raise ValueError("maximum must be greater than or equal to minimum")
        self._require_ui()
        changed = (minimum, maximum) != (self._minimum, self._maximum)
        self._minimum, self._maximum = minimum, maximum
        self.backend.configure_item(self.tag, min_value=minimum, max_value=maximum)
        self._slider_position = self._clamp(self._slider_position)
        self._set_value_now(self._clamp(self.value()))
        if changed:
            self.rangeChanged.emit(minimum, maximum)

    def value(self):
        self._require_ui()
        try:
            return self._clamp(self.backend.get_value(self.tag))
        except Exception:
            return self._clamp(self._properties.get("value", self._minimum))

    def setValue(self, value):
        self._on_ui("value", self._set_value_now, self._clamp(value))

    def _set_value_now(self, value):
        value = self._clamp(value)
        previous = self._properties.get("value")
        self._slider_position = value
        self._set_value(value)
        if previous != value:
            self.valueChanged.emit(value)

    def sliderPosition(self):
        return int(self._slider_position)

    def setSliderPosition(self, position):
        position = self._clamp(position)
        if position == self._slider_position and position == self.value():
            return
        self._slider_position = position
        self.sliderMoved.emit(position)
        if self._tracking:
            self.setValue(position)

    def isSliderDown(self):
        return bool(self._slider_down)

    def setSliderDown(self, down):
        down = bool(down)
        if down == self._slider_down:
            return
        self._slider_down = down
        if down:
            self.sliderPressed.emit()
        else:
            if not self._tracking:
                self.setValue(self._slider_position)
            self.sliderReleased.emit()

    def singleStep(self):
        return self._single_step

    def setSingleStep(self, step):
        self._single_step = max(1, int(step))

    def pageStep(self):
        return self._page_step

    def setPageStep(self, step):
        self._page_step = max(1, int(step))

    def setTracking(self, enabled):
        self._tracking = bool(enabled)

    def hasTracking(self):
        return self._tracking

    def setInvertedAppearance(self, inverted):
        self._inverted_appearance = bool(inverted)

    def invertedAppearance(self):
        return self._inverted_appearance

    def setInvertedControls(self, inverted):
        self._inverted_controls = bool(inverted)

    def invertedControls(self):
        return self._inverted_controls

    def triggerAction(self, action):
        """Apply a QAbstractSlider::SliderAction value."""
        legacy = {
            "single_step_add": self.SliderSingleStepAdd,
            "single_step_sub": self.SliderSingleStepSub,
            "page_step_add": self.SliderPageStepAdd,
            "page_step_sub": self.SliderPageStepSub,
            "to_minimum": self.SliderToMinimum,
            "to_maximum": self.SliderToMaximum,
        }
        action = legacy.get(action, action)
        action = int(action)
        delta = {
            self.SliderSingleStepAdd: self._single_step,
            self.SliderSingleStepSub: -self._single_step,
            self.SliderPageStepAdd: self._page_step,
            self.SliderPageStepSub: -self._page_step,
        }
        if self._inverted_controls and action in delta:
            delta[action] = -delta[action]
        if action == self.SliderNoAction:
            return
        if action == self.SliderToMinimum:
            self.setValue(self._minimum)
        elif action == self.SliderToMaximum:
            self.setValue(self._maximum)
        elif action == self.SliderMove:
            self.setValue(self._slider_position)
        elif action in delta:
            self.setValue(self.value() + delta[action])
        else:
            raise ValueError("unknown slider action")
        self.actionTriggered.emit(action)


class QSlider(QAbstractSlider):
    """Integer QSlider-like wrapper.

    Dear ImGui owns native pointer/keyboard interaction; DearUIQt owns the Qt
    state/signals so application code no longer has to manipulate DPG items.
    Vertical sliders are supported when the backend exposes ``add_vslider_int``.
    """

    def __init__(self, orientation=Qt.Horizontal, *, minimum=0, maximum=99,
                 value=0, single_step=1, page_step=10, parent=None, after=None,
                 backend=None, width=-1, height=None):
        orientation = int(orientation)
        if orientation not in (Qt.Horizontal, Qt.Vertical):
            raise ValueError("orientation must be Qt.Horizontal or Qt.Vertical")
        minimum, maximum = int(minimum), int(maximum)
        if maximum < minimum:
            raise ValueError("maximum must be greater than or equal to minimum")
        backend, options = self._construction(parent, backend)
        value = max(minimum, min(maximum, int(value)))
        options.update(
            default_value=value,
            min_value=minimum,
            max_value=maximum,
            callback=self._changed,
            width=int(width),
        )
        if height is not None:
            options["height"] = int(height)
        if orientation == Qt.Vertical:
            creator = getattr(backend, "add_vslider_int", None)
            if creator is None:
                raise RuntimeError("backend does not provide vertical integer sliders")
        else:
            creator = backend.add_slider_int
        tag = creator(**options)
        self._focus_handlers = None
        super().__init__(
            tag,
            orientation=orientation,
            minimum=minimum,
            maximum=maximum,
            value=value,
            single_step=single_step,
            page_step=page_step,
            parent=parent,
            after=after,
            backend=backend,
        )
        self._focus_handlers = _bind_focus_state_handlers(
            backend, self.tag, self._refresh_style)
        self._refresh_style()

    def _changed(self, sender, value, *_args):
        if self._deleted:
            return
        value = self._clamp(value)
        previous = self._properties.get("value")
        self._slider_position = value
        self._user_value(value)
        if previous != value:
            self.sliderMoved.emit(value)
            # Dear ImGui reports the interactive value continuously. This maps
            # naturally to Qt tracking=True; tracking=False still retains the
            # position until setSliderDown(False) commits it.
            if self._tracking:
                self.valueChanged.emit(value)
            else:
                self._properties["value"] = previous

    def _refresh_style(self, *_args):
        enabled = bool(self._properties.get("enabled", True))
        focused = False
        try:
            state = self.backend.get_item_state(self.tag) or {}
            focused = bool(state.get("active", False) or state.get("focused", False))
        except Exception:
            pass
        bind_theme(self.backend, self.tag, slider_theme,
                   disabled=not enabled, focused=enabled and focused)

    def delete(self):
        handlers = self._focus_handlers
        super().delete()
        _delete_aux_item(self.backend, handlers)


__all__ = ["QAbstractSlider", "QSlider"]
