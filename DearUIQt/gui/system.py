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
    def viewportPos(*, backend=None):
        """Sample the live cursor in the primary viewport's client coordinates.

        Unlike renderer mouse state this can be sampled immediately before
        painting a drag overlay, without waiting for another input/render turn.
        Falls back to pos() when no native primary window is available.
        """
        b = _backend(backend)
        try:
            from ..backends.native_windows import NativeWindowBackend
            point = NativeWindowBackend(b).cursorClientPosition()
            if point is not None:
                return QPoint(*point)
        except (AttributeError, OSError, ValueError, TypeError):
            pass
        return QCursor.pos(backend=b)

    @staticmethod
    def paintPos(*, backend=None):
        """Live cursor in QViewportCanvas coordinates, including native viewports."""
        b = _backend(backend)
        try:
            from ..backends.native_windows import NativeWindowBackend
            point = NativeWindowBackend(b).cursorPaintPosition()
            if point is not None:
                return QPoint(*point)
        except (AttributeError, OSError, ValueError, TypeError):
            pass
        return QCursor.pos(backend=b)

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

    def _native_windows(self):
        import os
        return os.name == 'nt' and str(getattr(self._backend, '__name__', '')).startswith('dearpygui.')

    def text(self, mode=Clipboard):
        del mode
        if self._native_windows():
            from ..backends.native_clipboard import text
            return text()
        getter = getattr(self._backend, "get_clipboard_text", None)
        if not callable(getter):
            return ""
        try:
            return str(getter() or "")
        except Exception:
            return ""

    def setText(self, text, mode=Clipboard):
        del mode
        if self._native_windows():
            from ..backends.native_clipboard import set_text
            return set_text(str(text or ''))
        setter = getattr(self._backend, "set_clipboard_text", None)
        if not callable(setter):
            return False
        setter(str(text or ""))
        return True

    def clear(self, mode=Clipboard):
        return self.setText("", mode=mode)


class QFontMetrics:
    """Backend-neutral text metrics for the active GUI font.

    Besides the basic Qt metrics surface, DearUIQt provides deterministic
    wrapping/elision helpers so retained layouts can negotiate text geometry
    without asking the renderer to perform an invisible measurement pass.
    """

    __slots__ = ("_font", "_backend", "_advance_cache", "_height_cache")

    def __init__(self, font=None, *, backend=None):
        self._font = font
        self._backend = _backend(backend)
        self._advance_cache = {}
        self._height_cache = None

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

    @staticmethod
    def _prepared_text(text, flags=0):
        value = str(text or "")
        if int(flags) & Qt.TextExpandTabs:
            value = value.expandtabs(8)
        if int(flags) & Qt.TextSingleLine:
            value = " ".join(value.splitlines())
        return value

    def horizontalAdvance(self, text):
        value = str(text or "")
        cached = self._advance_cache.get(value)
        if cached is not None:
            return cached
        measured = self._measure(value)
        if measured is not None and measured[0] > 0:
            width = int(round(measured[0]))
        else:
            width = int(round(len(value) * 7.0))
        if len(self._advance_cache) >= 512:
            self._advance_cache.clear()
        self._advance_cache[value] = width
        return width

    def width(self, text):
        return self.horizontalAdvance(text)

    def height(self):
        if self._height_cache is not None:
            return self._height_cache
        measured = self._measure("Ag")
        self._height_cache = (int(round(measured[1]))
                              if measured is not None and measured[1] > 0 else 14)
        return self._height_cache

    def lineSpacing(self):
        """Return one backend text-line advance in device-independent pixels."""
        return self.height()

    def leading(self):
        # Dear ImGui exposes glyph/text bounds rather than font ascent tables.
        # Keep line spacing deterministic and report no synthetic extra leading.
        return 0

    def descent(self):
        # A backend may expose exact metrics later.  Until then derive a stable
        # baseline split from the measured line box instead of a hard-coded px.
        return max(1, int(round(self.height() * .20)))

    def ascent(self):
        return max(0, self.height() - self.descent())

    def capHeight(self):
        measured = self._measure("H")
        return max(1, int(round(measured[1]))) if measured and measured[1] > 0 else self.ascent()

    def xHeight(self):
        measured = self._measure("x")
        if measured is not None and measured[1] > 0:
            return max(1, int(round(measured[1])))
        return max(1, int(round(self.ascent() * .70)))

    def averageCharWidth(self):
        sample = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        measured = self._measure(sample)
        if measured is not None and measured[0] > 0:
            return max(1, int(round(measured[0] / len(sample))))
        return max(1, self.horizontalAdvance("n"))

    def elidedText(self, text, mode, width, flags=0):
        """Return *text* elided to *width* using Qt-compatible modes.

        The implementation is measurement-driven (not character-count driven),
        which keeps mixed-width fonts and DPI-scaled backends deterministic.
        """
        value = self._prepared_text(text, flags)
        width = max(0, int(width))
        mode = int(mode)
        if mode == Qt.ElideNone or self.horizontalAdvance(value) <= width:
            return value
        ellipsis = "…"
        ellipsis_width = self.horizontalAdvance(ellipsis)
        if width <= 0 or ellipsis_width > width:
            return ""

        def fits(candidate):
            return self.horizontalAdvance(candidate) <= width

        if mode == Qt.ElideLeft:
            lo, hi = 0, len(value)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if fits(ellipsis + value[len(value) - mid:]):
                    lo = mid
                else:
                    hi = mid - 1
            return ellipsis + value[len(value) - lo:]
        if mode == Qt.ElideMiddle:
            lo, hi = 0, len(value)
            while lo < hi:
                kept = (lo + hi + 1) // 2
                left = (kept + 1) // 2
                right = kept // 2
                candidate = value[:left] + ellipsis + (value[len(value) - right:] if right else "")
                if fits(candidate):
                    lo = kept
                else:
                    hi = kept - 1
            left = (lo + 1) // 2
            right = lo // 2
            return value[:left] + ellipsis + (value[len(value) - right:] if right else "")

        # Qt.ElideRight and unknown modes use the common right-elide behavior.
        lo, hi = 0, len(value)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if fits(value[:mid] + ellipsis):
                lo = mid
            else:
                hi = mid - 1
        return value[:lo] + ellipsis

    def _break_token(self, token, width):
        """Split one over-wide token into measured fragments."""
        if not token:
            return [""]
        fragments = []
        remaining = token
        while remaining:
            lo, hi = 1, len(remaining)
            best = 0
            while lo <= hi:
                mid = (lo + hi) // 2
                if self.horizontalAdvance(remaining[:mid]) <= width:
                    best = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            best = max(1, best)
            fragments.append(remaining[:best])
            remaining = remaining[best:]
        return fragments

    def wrappedLines(self, text, width, flags=Qt.TextWordWrap):
        """Return measured wrapped lines for a logical text width.

        This helper intentionally returns strings instead of renderer objects so
        widgets, model delegates and tests can share the same typography rules.
        """
        value = self._prepared_text(text, flags)
        width = max(0, int(width))
        if int(flags) & Qt.TextSingleLine:
            return (value,)
        paragraphs = value.split("\n")
        if width <= 0:
            return tuple(paragraphs or [""])
        wrap_anywhere = bool(int(flags) & Qt.TextWrapAnywhere)
        lines = []
        for paragraph in paragraphs:
            if paragraph == "":
                lines.append("")
                continue
            if wrap_anywhere:
                lines.extend(self._break_token(paragraph, width))
                continue
            words = paragraph.split()
            if not words:
                lines.append("")
                continue
            current = ""
            for word in words:
                candidate = word if not current else current + " " + word
                if self.horizontalAdvance(candidate) <= width:
                    current = candidate
                    continue
                if current:
                    lines.append(current)
                    current = ""
                if self.horizontalAdvance(word) <= width:
                    current = word
                else:
                    fragments = self._break_token(word, width)
                    lines.extend(fragments[:-1])
                    current = fragments[-1]
            lines.append(current)
        return tuple(lines or [""])

    def wrappedText(self, text, width, flags=Qt.TextWordWrap):
        return "\n".join(self.wrappedLines(text, width, flags))

    def size(self, text, flags=0, width=None):
        value = self._prepared_text(text, flags)
        if width is not None and int(flags) & (Qt.TextWordWrap | Qt.TextWrapAnywhere):
            lines = self.wrappedLines(value, width, flags)
            measured_width = max((self.horizontalAdvance(line) for line in lines), default=0)
            return QSize(measured_width, max(1, len(lines)) * self.lineSpacing())
        measured = self._measure(value)
        if measured is None:
            return QSize(self.horizontalAdvance(value), self.height())
        return QSize(round(measured[0]), round(measured[1]))

    def boundingRect(self, *args):
        """Qt-like boundingRect overload for text or constrained rectangles."""
        if len(args) == 1:
            size = self.size(args[0])
            return QRect(0, 0, size.width(), size.height())
        if len(args) == 3 and isinstance(args[0], QRect):
            rect, flags, text = args
        elif len(args) == 6:
            rect = QRect(args[0], args[1], args[2], args[3])
            flags, text = args[4], args[5]
        else:
            raise TypeError("boundingRect expects text, (QRect, flags, text), or (x, y, w, h, flags, text)")
        flags = int(flags)
        size = self.size(text, flags, rect.width())
        width = min(rect.width(), size.width()) if rect.width() >= 0 else size.width()
        height = size.height()
        x, y = rect.x(), rect.y()
        if flags & Qt.AlignRight:
            x += max(0, rect.width() - width)
        elif flags & Qt.AlignHCenter:
            x += max(0, (rect.width() - width) // 2)
        if flags & Qt.AlignBottom:
            y += max(0, rect.height() - height)
        elif flags & Qt.AlignVCenter:
            y += max(0, (rect.height() - height) // 2)
        return QRect(x, y, width, height)


class QScreen:
    """Primary-screen/viewport facade used by retained desktop applications."""

    __slots__ = ("_backend",)

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

    def _dpi(self, axis=None, physical=False):
        b = self._backend
        names = (("get_physical_dpi", "physical_dpi") if physical else
                 ("get_logical_dpi", "logical_dpi"))
        # Preserve renderer-provided X/Y DPI asymmetry when available.  The
        # native GetDpiForWindow fallback is scalar and is used only after the
        # renderer contract has had a chance to answer this axis-specific query.
        for name in names:
            getter = getattr(b, name, None)
            if not callable(getter):
                continue
            try:
                value = getter()
                if isinstance(value, (tuple, list)):
                    value = value[0 if axis != "y" else 1]
                value = float(value)
                if value > 0:
                    return value
            except Exception:
                pass
        if not physical:
            try:
                from .dpi import logical_dpi_for_backend
                return logical_dpi_for_backend(b)
            except Exception:
                pass
        return 96.0

    def logicalDotsPerInch(self):
        return self._dpi()

    def logicalDotsPerInchX(self):
        return self._dpi("x")

    def logicalDotsPerInchY(self):
        return self._dpi("y")

    def physicalDotsPerInch(self):
        return self._dpi(physical=True)

    def physicalDotsPerInchX(self):
        return self._dpi("x", physical=True)

    def physicalDotsPerInchY(self):
        return self._dpi("y", physical=True)

    def devicePixelRatio(self):
        getter = getattr(self._backend, "get_device_pixel_ratio", None)
        if callable(getter):
            try:
                value = float(getter())
                if value > 0:
                    return value
            except Exception:
                pass
        return max(.25, self.logicalDotsPerInch() / 96.0)

    def devicePixelRatioF(self):
        return float(self.devicePixelRatio())

    def dpiScale(self, base_dpi=96.0):
        """Return logical UI scale relative to *base_dpi* (DearUIQt extension).

        Qt applications normally receive logical coordinates after high-DPI
        scaling. DearUIQt backends are not all DPI-virtualized, so reusable
        widgets can use this explicit factor when materializing pixel metrics.
        """
        try:
            base = float(base_dpi)
        except (TypeError, ValueError, OverflowError):
            base = 96.0
        if base <= 0:
            base = 96.0
        return max(.25, self.logicalDotsPerInch() / base)

    def size(self):
        return self.geometry().size()


__all__ = ["QCursor", "QKeyboard", "QClipboard", "QFontMetrics", "QScreen"]
