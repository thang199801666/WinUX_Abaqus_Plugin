"""Container, frame and progress controls."""
from __future__ import annotations

from ..gui.style import bind_theme, group_box_theme, progress_theme, panel_surface_theme
from .widget import QWidget


class QFrame(QWidget):
    """Small QFrame-like container for application panels.

    Dear PyGui child windows already provide the clipping, background and
    border behavior WinUx previously implemented with ad-hoc ``add_child_window``
    calls.  QFrame centralizes that native item behind DearUIQt so feature code
    can use Qt-style visibility/geometry/lifecycle APIs.
    """

    NoFrame = 0
    Box = 1
    Panel = 2
    StyledPanel = 6
    HLine = 4
    VLine = 5

    Plain = 0x10
    Raised = 0x20
    Sunken = 0x30

    def __init__(self, *, parent=None, after=None, backend=None, width=-1,
                 height=-1, frame_shape=StyledPanel, auto_resize_y=False,
                 no_scrollbar=True, no_scroll_with_mouse=True,
                 horizontal_scrollbar=False, pos=None, show=True, tag=None):
        backend, options = self._construction(parent, backend)
        self._frame_shape = int(frame_shape)
        self._vertical_sizing_host = True
        # Retain the native vertical sizing contract so child layouts can
        # distinguish intrinsic-height hosts from fixed/viewport-height hosts.
        self._auto_resize_y = bool(auto_resize_y)
        self._frame_shadow = self.Plain
        self._line_width = 1
        native_options = dict(
            width=int(width), height=int(height),
            border=self._frame_shape != self.NoFrame,
            auto_resize_y=bool(auto_resize_y),
            always_auto_resize=bool(auto_resize_y),
            no_scrollbar=bool(no_scrollbar),
            no_scroll_with_mouse=bool(no_scroll_with_mouse),
            horizontal_scrollbar=bool(horizontal_scrollbar),
            show=bool(show),
        )
        if pos is not None:
            native_options["pos"] = tuple(pos)
        if tag is not None:
            native_options["tag"] = tag
        native_options.update(options)
        native = backend.add_child_window(**native_options)
        super().__init__(native, parent=parent, after=after, backend=backend)
        if not show:
            self._explicit_visible = False
            self._effective_visible = False
            self._properties["show"] = False
        self._refresh_style()

    def frameShape(self):
        return self._frame_shape

    def setFrameShape(self, shape):
        self._frame_shape = int(shape)
        self._configure("border", self._frame_shape != self.NoFrame)
        self._refresh_style()

    def frameShadow(self):
        return self._frame_shadow

    def setFrameShadow(self, shadow):
        self._frame_shadow = int(shadow)
        self._refresh_style()

    def frameStyle(self):
        return int(self._frame_shape | self._frame_shadow)

    def setFrameStyle(self, style):
        style = int(style)
        self._frame_shape = style & 0x0F
        self._frame_shadow = style & 0xF0
        self._configure("border", self._frame_shape != self.NoFrame)
        self._refresh_style()

    def lineWidth(self):
        return self._line_width

    def setLineWidth(self, width):
        self._line_width = max(0, int(width))
        self._refresh_style()

    def _refresh_style(self, *_args):
        bind_theme(
            self.backend, self.tag, panel_surface_theme,
            bordered=self._frame_shape != self.NoFrame,
            compact=True,
        )

class ImGuiGroupBox(QWidget):
    """Compact Dear ImGui group container with QGroupBox-like properties."""

    def __init__(self, title="", *, parent=None, after=None, backend=None,
                 width=-1, auto_resize_y=True):
        backend, options = self._construction(parent, backend)
        # Group boxes also own a native child window.  Nested form tables must
        # recognize its intrinsic height just like they recognize QFrame.
        self._vertical_sizing_host = True
        self._auto_resize_y = bool(auto_resize_y)
        shell = backend.add_child_window(
            width=width,
            auto_resize_y=bool(auto_resize_y),
            always_auto_resize=bool(auto_resize_y),
            border=True,
            no_scrollbar=True,
            **options,
        )
        super().__init__(shell, parent=parent, after=after, backend=backend)
        self._title = str(title or "")
        self.title_label = backend.add_text(self._title, parent=self.tag)
        self.content = backend.add_group(parent=self.tag)
        bind_theme(backend, self.tag, group_box_theme)

    def title(self):
        return self._title

    def setTitle(self, title):
        self._title = str(title or "")
        self._on_ui("title", self.backend.set_value, self.title_label, self._title)

    def __enter__(self):
        self._require_ui()
        self.backend.push_container_stack(self.content)
        return self.content

    def __exit__(self, exc_type, exc, tb):
        self.backend.pop_container_stack()
        return False


class ImGuiProgressBar(QWidget):
    """Use normalized values (0..1), matching Dear ImGui progress semantics."""

    def __init__(self, *, parent=None, after=None, backend=None):
        backend, options = self._construction(parent, backend)
        super().__init__(backend.add_progress_bar(width=-1, overlay="0%", **options),
                         parent=parent, after=after, backend=backend)
        bind_theme(self.backend, self.tag, progress_theme)

    def setValue(self, value):
        self._on_ui("value", self._set_value, max(0.0, min(1.0, float(value))))

    def setFormat(self, text):
        self._on_ui("overlay", self._configure, "overlay", str(text))

    def setState(self, state="normal"):
        """Apply a semantic Qt-style progress state without changing value."""
        self._on_ui("state", self._set_state, str(state or "normal"))

    def _set_state(self, state):
        self._properties["state"] = str(state or "normal")
        bind_theme(self.backend, self.tag, progress_theme, state=self._properties["state"])



QGroupBox = ImGuiGroupBox
QProgressBar = ImGuiProgressBar
__all__ = [
    "QFrame", "ImGuiGroupBox", "ImGuiProgressBar", "QGroupBox", "QProgressBar",
]
