"""QtGui-style input event classes.

The concrete keyboard/pointer/wheel event implementations live in QtGui rather
than QtCore.  DearUIQt.core keeps compatibility aliases for existing callers.
"""
from __future__ import annotations

from enum import IntEnum

from ..core.object import QEvent, QPoint, QPointF, Qt


class QGuiEventType(IntEnum):
    FocusIn = QEvent.FocusIn
    FocusOut = QEvent.FocusOut
    WindowActivate = QEvent.WindowActivate
    WindowDeactivate = QEvent.WindowDeactivate
    KeyPress = QEvent.KeyPress
    KeyRelease = QEvent.KeyRelease
    ShortcutOverride = QEvent.ShortcutOverride
    MouseButtonPress = QEvent.MouseButtonPress
    MouseButtonRelease = QEvent.MouseButtonRelease
    MouseMove = QEvent.MouseMove
    Enter = QEvent.Enter
    Leave = QEvent.Leave
    StyleChange = QEvent.StyleChange
    PaletteChange = QEvent.PaletteChange
    ApplicationPaletteChange = QEvent.ApplicationPaletteChange
    ScreenChangeInternal = QEvent.ScreenChangeInternal
    DevicePixelRatioChange = QEvent.DevicePixelRatioChange
    Wheel = QEvent.Wheel
    Shortcut = QEvent.Shortcut
    WindowStateChange = QEvent.WindowStateChange
    Move = QEvent.Move
    Resize = QEvent.Resize
    Expose = QEvent.Expose
    ActivationChange = QEvent.ActivationChange


_GUI_EVENT_VALUES = frozenset(int(value) for value in QGuiEventType)


def isGuiEventType(value):
    if hasattr(value, "type") and callable(value.type):
        value = value.type()
    try:
        return int(value) in _GUI_EVENT_VALUES
    except (TypeError, ValueError):
        return False


class QKeyEvent(QEvent):
    """Qt-style keyboard event normalized by the application input bridge."""

    __slots__ = ("_key", "_modifiers", "_text", "_auto_repeat", "_count")

    def __init__(self, event_type, key, modifiers=Qt.NoModifier, *, text="",
                 auto_repeat=False, count=1):
        if event_type not in (QEvent.KeyPress, QEvent.KeyRelease, QEvent.ShortcutOverride):
            raise ValueError("QKeyEvent requires a keyboard QEvent type")
        super().__init__(event_type)
        self._key = key
        self._modifiers = int(modifiers)
        self._text = str(text or "")
        self._auto_repeat = bool(auto_repeat)
        self._count = max(1, int(count))

    def key(self): return self._key
    def modifiers(self): return self._modifiers
    def text(self): return self._text
    def isAutoRepeat(self): return self._auto_repeat
    def count(self): return self._count


class QMouseEvent(QEvent):
    """Qt-style pointer event retaining the host-supplied coordinate space."""

    __slots__ = ("_position", "_button", "_buttons", "_modifiers")

    def __init__(self, event_type, position=(0.0, 0.0), *,
                 button=Qt.NoButton, buttons=Qt.NoButton,
                 modifiers=Qt.NoModifier):
        if event_type not in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseMove):
            raise ValueError("QMouseEvent requires a mouse QEvent type")
        super().__init__(event_type)
        try:
            x, y = position
        except (TypeError, ValueError):
            raise TypeError("position must be a two-value sequence")
        self._position = QPointF(x, y)
        self._button = int(button)
        self._buttons = int(buttons)
        self._modifiers = int(modifiers)

    def position(self): return self._position
    def globalPosition(self): return self._position
    def button(self): return self._button
    def buttons(self): return self._buttons
    def modifiers(self): return self._modifiers


class QWheelEvent(QEvent):
    """Qt-style wheel event with pixel and 1/8-degree angle deltas."""

    __slots__ = ("_position", "_pixel_delta", "_angle_delta", "_buttons", "_modifiers")

    def __init__(self, position=(0.0, 0.0), *, pixel_delta=(0, 0),
                 angle_delta=(0, 0), buttons=Qt.NoButton, modifiers=Qt.NoModifier):
        super().__init__(QEvent.Wheel)
        try:
            x, y = position
            px, py = pixel_delta
            ax, ay = angle_delta
        except (TypeError, ValueError):
            raise TypeError("position and deltas must be two-value sequences")
        self._position = QPointF(x, y)
        self._pixel_delta = QPoint(int(px), int(py))
        self._angle_delta = QPoint(int(ax), int(ay))
        self._buttons = int(buttons)
        self._modifiers = int(modifiers)

    def position(self): return self._position
    def globalPosition(self): return self._position
    def pixelDelta(self): return self._pixel_delta
    def angleDelta(self): return self._angle_delta
    def buttons(self): return self._buttons
    def modifiers(self): return self._modifiers


__all__ = ["QGuiEventType", "isGuiEventType", "QKeyEvent", "QMouseEvent", "QWheelEvent"]
