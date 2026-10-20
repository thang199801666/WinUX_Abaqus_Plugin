"""Renderer-neutral QtGui system helpers.

These helpers keep common desktop queries (cursor, clipboard, text metrics and
screen geometry) behind DearUIQt.  Applications should not need renderer
symbols merely to measure text or inspect global pointer/viewport state.
"""
from __future__ import annotations

from ..backends import get_backend
from ..core.object import QPoint, QRect, QSize, Qt


def _backend(backend=None):
    return backend or get_backend()


class QCursor:
    """Small QCursor-compatible facade over the active GUI backend."""

    ArrowCursor = 0
    SizeHorCursor = 1
    SizeVerCursor = 2
    SizeFDiagCursor = 3
    SizeBDiagCursor = 4
    PointingHandCursor = 5
    IBeamCursor = 6

    _SHAPES = {
        ArrowCursor: ("mvMouseCursor_Arrow",),
        SizeHorCursor: ("mvMouseCursor_ResizeEW", "mvMouseCursor_ResizeAll"),
        SizeVerCursor: ("mvMouseCursor_ResizeNS", "mvMouseCursor_ResizeAll"),
        SizeFDiagCursor: ("mvMouseCursor_ResizeNWSE", "mvMouseCursor_ResizeAll"),
        SizeBDiagCursor: ("mvMouseCursor_ResizeNESW", "mvMouseCursor_ResizeAll"),
        PointingHandCursor: ("mvMouseCursor_Hand", "mvMouseCursor_Arrow"),
        IBeamCursor: ("mvMouseCursor_TextInput", "mvMouseCursor_Arrow"),
    }

    @staticmethod
    def pos(*, backend=None):
        b = _backend(backend)
        try:
            value = b.get_mouse_pos(local=False)
            return QPoint(round(float(value[0])), round(float(value[1])))
        except Exception:
            return QPoint()

    @staticmethod
    def screenPos(*, backend=None):
        """Return the physical desktop cursor position.

        Dear PyGui's ``get_mouse_pos(local=False)`` is not consistent across
        native/embedded Windows builds: some runtimes report viewport-local
        coordinates while others report desktop coordinates. Context menus
        need an unambiguous screen anchor, so use Win32 ``GetCursorPos`` when
        available and fall back to the renderer only off Windows/test backends.
        """
        try:
            import ctypes
            from ctypes import wintypes
            point = wintypes.POINT()
            user32 = ctypes.windll.user32
            user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
            user32.GetCursorPos.restype = wintypes.BOOL
            if user32.GetCursorPos(ctypes.byref(point)):
                return QPoint(int(point.x), int(point.y))
        except Exception:
            pass
        return QCursor.pos(backend=backend)

    @staticmethod
    def localPos(*, backend=None):
        """Return renderer-local cursor position for retained hit-testing."""
        b = _backend(backend)
        try:
            value = b.get_mouse_pos(local=True)
            return QPoint(round(float(value[0])), round(float(value[1])))
        except Exception:
            return QCursor.pos(backend=b)

    @staticmethod
    def dragDelta(button=Qt.LeftButton, *, backend=None):
        """Return the backend drag delta mapped from a Qt mouse button."""
        b = _backend(backend)
        getter = getattr(b, "get_mouse_drag_delta", None)
        if not callable(getter):
            return QPoint()
        native = None
        names = {
            Qt.LeftButton: "mvMouseButton_Left",
            Qt.RightButton: "mvMouseButton_Right",
            Qt.MiddleButton: "mvMouseButton_Middle",
        }
        name = names.get(int(button))
        if name is not None:
            native = getattr(b, name, None)
        try:
            value = getter(native) if native is not None else getter()
            return QPoint(round(float(value[0])), round(float(value[1])))
        except TypeError:
            try:
                value = getter()
                return QPoint(round(float(value[0])), round(float(value[1])))
            except Exception:
                return QPoint()
        except Exception:
            return QPoint()

    @staticmethod
    def buttons(*, backend=None):
        """Return currently pressed mouse buttons as :class:`Qt` flags.

        This mirrors ``QGuiApplication.mouseButtons()`` without requiring a
        process-wide QApplication instance, which is important for reusable
        floating dialog hosts that still have a renderer backend.
        """
        b = _backend(backend)
        checker = getattr(b, "is_mouse_button_down", None)
        if not callable(checker):
            return Qt.NoButton
        result = Qt.NoButton
        names = (
            (Qt.LeftButton, "mvMouseButton_Left"),
            (Qt.RightButton, "mvMouseButton_Right"),
            (Qt.MiddleButton, "mvMouseButton_Middle"),
        )
        for flag, name in names:
            native = getattr(b, name, None)
            if native is None:
                continue
            try:
                if checker(native):
                    result |= flag
            except Exception:
                continue
        return result

    @staticmethod
    def isButtonDown(button, *, backend=None):
        return bool(QCursor.buttons(backend=backend) & int(button))

    @staticmethod
    def _nativeButton(button, backend):
        names = {
            Qt.LeftButton: "mvMouseButton_Left",
            Qt.RightButton: "mvMouseButton_Right",
            Qt.MiddleButton: "mvMouseButton_Middle",
        }
        return getattr(backend, names.get(int(button), ""), None)

    @staticmethod
    def isButtonClicked(button, *, backend=None):
        b = _backend(backend)
        checker = getattr(b, "is_mouse_button_clicked", None)
        native = QCursor._nativeButton(button, b)
        if not callable(checker) or native is None:
            return False
        try:
            return bool(checker(native))
        except Exception:
            return False

    @staticmethod
    def isButtonDoubleClicked(button, *, backend=None):
        b = _backend(backend)
        checker = getattr(b, "is_mouse_button_double_clicked", None)
        native = QCursor._nativeButton(button, b)
        if not callable(checker) or native is None:
            return False
        try:
            return bool(checker(native))
        except Exception:
            return False

    @classmethod
    def setShape(cls, shape, *, backend=None):
        b = _backend(backend)
        setter = getattr(b, "set_mouse_cursor", None)
        if not callable(setter):
            return False
        names = cls._SHAPES.get(int(shape), cls._SHAPES[cls.ArrowCursor])
        for name in names:
            native = getattr(b, name, None)
            if native is None:
                continue
            try:
                setter(native)
                return True
            except Exception:
                continue
        return False


class QKeyboard:
    """Renderer-neutral keyboard modifier query similar to QGuiApplication."""

    @staticmethod
    def modifiers(*, backend=None):
        b = _backend(backend)
        checker = getattr(b, "is_key_down", None)
        if not callable(checker):
            return Qt.NoModifier
        value = Qt.NoModifier
        groups = (
            (Qt.ShiftModifier, ("mvKey_LShift", "mvKey_RShift")),
            (Qt.ControlModifier, ("mvKey_LControl", "mvKey_RControl")),
            (Qt.AltModifier, ("mvKey_LAlt", "mvKey_RAlt")),
            (Qt.MetaModifier, ("mvKey_LWin", "mvKey_RWin")),
        )
        for flag, names in groups:
            for name in names:
                native = getattr(b, name, None)
                if native is None:
                    continue
                try:
                    if checker(native):
                        value |= flag
                        break
                except Exception:
                    continue
        return value

    @classmethod
    def hasModifier(cls, modifier, *, backend=None):
        """Return whether every requested Qt keyboard modifier is held."""
        modifier = int(modifier)
        return (int(cls.modifiers(backend=backend)) & modifier) == modifier

    @classmethod
    def isShiftDown(cls, *, backend=None):
        return cls.hasModifier(Qt.ShiftModifier, backend=backend)

    @classmethod
    def isControlDown(cls, *, backend=None):
        return cls.hasModifier(Qt.ControlModifier, backend=backend)

    @classmethod
    def isAltDown(cls, *, backend=None):
        return cls.hasModifier(Qt.AltModifier, backend=backend)

    @staticmethod
    def isKeyPressed(key, *, backend=None):
        """Return whether a Qt key was pressed during the current frame."""
        b = _backend(backend)
        checker = getattr(b, "is_key_pressed", None)
        if not callable(checker):
            return False
        try:
            from ..core.input import QGlobalInputBinding
            native = QGlobalInputBinding.nativeKeyFor(int(key), b)
            if native is None:
                return False
            return bool(checker(native))
        except Exception:
            return False


class QClipboard:
    """QClipboard-like text clipboard bound to one renderer backend."""

    Clipboard = 0

    def __init__(self, *, backend=None):
        self._backend = _backend(backend)

    def text(self, mode=Clipboard):
        del mode
        getter = getattr(self._backend, "get_clipboard_text", None)
        if not callable(getter):
            return ""
        try:
            return str(getter() or "")
        except Exception:
            return ""

    def setText(self, text, mode=Clipboard):
        del mode
        setter = getattr(self._backend, "set_clipboard_text", None)
        if not callable(setter):
            return False
        setter(str(text or ""))
        return True

    def clear(self, mode=Clipboard):
        return self.setText("", mode=mode)


class QFontMetrics:
    """Backend-neutral text metrics for the active GUI font."""

    def __init__(self, font=None, *, backend=None):
        self._font = font
        self._backend = _backend(backend)

    def _measure(self, text):
        getter = getattr(self._backend, "get_text_size", None)
        if not callable(getter):
            return None
        kwargs = {}
        if self._font is not None:
            kwargs["font"] = self._font.nativeId() if hasattr(self._font, "nativeId") else self._font
        try:
            value = getter(str(text or ""), **kwargs)
        except TypeError:
            try:
                value = getter(str(text or ""))
            except Exception:
                return None
        except Exception:
            return None
        if not isinstance(value, (tuple, list)) or len(value) < 2:
            return None
        try:
            return float(value[0] or 0.0), float(value[1] or 0.0)
        except (TypeError, ValueError, IndexError, OverflowError):
            return None

    def horizontalAdvance(self, text):
        measured = self._measure(text)
        if measured is not None and measured[0] > 0:
            return int(round(measured[0]))
        return int(round(len(str(text or "")) * 7.0))

    def width(self, text):
        return self.horizontalAdvance(text)

    def height(self):
        measured = self._measure("Ag")
        if measured is not None and measured[1] > 0:
            return int(round(measured[1]))
        return 14

    def size(self, text):
        measured = self._measure(text)
        if measured is None:
            return QSize(self.horizontalAdvance(text), self.height())
        return QSize(round(measured[0]), round(measured[1]))

    def boundingRect(self, text):
        size = self.size(text)
        return QRect(0, 0, size.width(), size.height())


class QScreen:
    """Primary-screen/viewport facade used by retained desktop applications."""

    def __init__(self, *, backend=None):
        self._backend = _backend(backend)

    def geometry(self):
        b = self._backend
        try:
            pos_getter = getattr(b, "get_viewport_pos", None)
            pos = pos_getter() if callable(pos_getter) else (0, 0)
        except Exception:
            pos = (0, 0)
        width_getter = getattr(b, "get_viewport_client_width", None) or getattr(b, "get_viewport_width", None)
        height_getter = getattr(b, "get_viewport_client_height", None) or getattr(b, "get_viewport_height", None)
        try:
            width = max(0, int(width_getter())) if callable(width_getter) else 0
        except Exception:
            width = 0
        try:
            height = max(0, int(height_getter())) if callable(height_getter) else 0
        except Exception:
            height = 0
        try:
            x, y = int(pos[0]), int(pos[1])
        except Exception:
            x, y = 0, 0
        return QRect(x, y, width, height)

    def resizeWindow(self, width, height):
        """Resize the renderer's primary top-level viewport/window."""
        configure = getattr(self._backend, "configure_viewport", None)
        if not callable(configure):
            return False
        try:
            configure(0, width=max(1, int(width)), height=max(1, int(height)))
            return True
        except Exception:
            return False

    def availableGeometry(self):
        return self.geometry()

    def windowGeometry(self):
        """Return the outer native viewport geometry when the backend exposes it.

        ``geometry()`` intentionally models the client area used for Qt-style
        widget layout.  Applications that persist the native top-level window
        size can use this method without reaching into renderer APIs.
        """
        b = self._backend
        try:
            pos_getter = getattr(b, "get_viewport_pos", None)
            pos = pos_getter() if callable(pos_getter) else (0, 0)
        except Exception:
            pos = (0, 0)
        width_getter = getattr(b, "get_viewport_width", None)
        height_getter = getattr(b, "get_viewport_height", None)
        try:
            width = max(0, int(width_getter())) if callable(width_getter) else self.geometry().width()
        except Exception:
            width = self.geometry().width()
        try:
            height = max(0, int(height_getter())) if callable(height_getter) else self.geometry().height()
        except Exception:
            height = self.geometry().height()
        try:
            x, y = int(pos[0]), int(pos[1])
        except Exception:
            x, y = 0, 0
        return QRect(x, y, width, height)

    def size(self):
        return self.geometry().size()


__all__ = ["QCursor", "QKeyboard", "QClipboard", "QFontMetrics", "QScreen"]
