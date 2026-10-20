"""Text and numeric editor controls."""
from __future__ import annotations

import inspect

from ..core.object import Signal
from ..gui.style import (
    bind_theme, line_edit_theme, spin_editor_theme, spin_shell_theme,
    spin_button_theme, spin_button_stack_theme, METRICS,
)
from .widget import QWidget
from ._utils import _bind_focus_state_handlers, _delete_aux_item

class ImGuiLineEdit(QWidget):
    """Single Dear ImGui InputText with QLineEdit-like retained properties.

    No click overlay or shell receives mouse input, so Dear ImGui owns the text
    cursor, selection and caret blinking directly.  A passive focus handler
    only swaps the 1 px border from Fusion gray to focus blue.
    """

    Normal = "normal"
    Password = "password"

    def __init__(self, text="", *, parent=None, after=None, backend=None, width=None,
                 password=False, readonly=False, placeholder="", callback=None, **kwargs):
        backend, options = self._construction(parent, backend)
        self.textChanged = Signal()
        self.textEdited = Signal()
        self.returnPressed = Signal()
        self.editingFinished = Signal()
        self._modified = False
        self._editing_dirty = False
        self._key_handlers = None
        self._external_callback = callback
        self._focus_handlers = None
        if width is not None:
            options["width"] = width
        options.update(kwargs)
        self._external_user_data = options.get("user_data")
        options.setdefault("default_value", str(text))
        options.setdefault("callback", self._changed)
        options.setdefault("auto_select_all", False)
        options.setdefault("readonly", bool(readonly))
        if password:
            options["password"] = True
        if placeholder:
            options["hint"] = str(placeholder)
        super().__init__(backend.add_input_text(**options), parent=parent, after=after, backend=backend)
        self.textChanged.owner = self
        self.textEdited.owner = self
        self.returnPressed.owner = self
        self.editingFinished.owner = self
        self._properties.update(value=str(options["default_value"]), enabled=bool(options.get("enabled", True)),
                                readonly=bool(options["readonly"]),
                                placeholder=str(options.get("hint", "")),
                                password=bool(options.get("password", False)))
        self._focus_handlers = _bind_focus_state_handlers(
            backend, self.tag, self._refresh_style)
        self._install_editing_handlers()
        self._refresh_style()

    def _install_editing_handlers(self):
        # Add to the existing registry; binding another registry would replace
        # the passive style handlers and disturb the native editor contract.
        try:
            if self._focus_handlers is not None:
                self.backend.add_item_deactivated_handler(
                    parent=self._focus_handlers, callback=self._finish_editing)
            if not self.backend.get_item_configuration(self.tag).get("multiline", False):
                with self.backend.handler_registry() as self._key_handlers:
                    self.backend.add_key_press_handler(
                        key=self.backend.mvKey_Return, callback=self._return_pressed)
                    numpad = getattr(self.backend, "mvKey_NumPadEnter", None)
                    if numpad is not None:
                        self.backend.add_key_press_handler(key=numpad, callback=self._return_pressed)
        except (AttributeError, TypeError, RuntimeError):
            pass

    def _return_pressed(self, *_args):
        if self._deleted or not self.hasFocus() or not self.isEnabled():
            return
        value = self.text()
        if value != self._properties.get("value"):
            self._changed(self.tag, value)
        self._editing_dirty = False
        self.returnPressed.emit()
        self.editingFinished.emit()

    def _finish_editing(self, *_args):
        if self._deleted or not self._editing_dirty:
            return
        self._editing_dirty = False
        self.editingFinished.emit()

    def isModified(self):
        self._require_ui()
        return self._modified

    def setModified(self, modified):
        self._on_ui("modified", self._set_modified_now, bool(modified))

    def _set_modified_now(self, modified):
        self._modified = modified

    def _changed(self, sender, value, *_args):
        if not self._deleted:
            value = str(value)
            changed = self._properties.get("value") != value
            self._user_value(value)
            if changed:
                if self._updates is not None:
                    self._updates.discard("modified")
                self._modified = self._editing_dirty = True
                self.textEdited.emit(value)
                self.textChanged.emit(value)
            self._invoke_external_callback(sender, value, _args[0] if _args else self._external_user_data)

    def _invoke_external_callback(self, sender, value, user_data=None):
        callback = self._external_callback
        if not callable(callback):
            return
        try:
            signature = inspect.signature(callback)
            positional = [p for p in signature.parameters.values()
                          if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
            has_varargs = any(p.kind == p.VAR_POSITIONAL for p in signature.parameters.values())
            count = 3 if has_varargs else len(positional)
        except (TypeError, ValueError):
            count = 3
        if count <= 0:
            callback()
        elif count == 1:
            callback(sender)
        elif count == 2:
            callback(sender, value)
        else:
            callback(sender, value, user_data)

    def setText(self, text):
        self._on_ui("value", self._set_text, str(text))

    def _set_text(self, text):
        changed = self._properties.get("value") != text
        self._set_value(text)
        self._modified = self._editing_dirty = False
        if changed:
            self.textChanged.emit(text)

    def text(self):
        self._require_ui()
        return str(self.backend.get_value(self.tag))

    def clear(self):
        self.setText("")

    def setReadOnly(self, readonly):
        self._on_ui("readonly", self._configure, "readonly", bool(readonly))

    def isReadOnly(self):
        return bool(self._properties.get("readonly", False))

    def setPlaceholderText(self, text):
        text = str(text or "")
        self._on_ui("hint", self._set_placeholder_now, text)

    def _set_placeholder_now(self, text):
        self._configure("hint", text)
        self._properties["placeholder"] = text

    def placeholderText(self):
        return str(self._properties.get("placeholder", ""))

    def setEchoMode(self, mode):
        password = mode in (self.Password, True, "password")
        self._on_ui("password", self._configure, "password", bool(password))

    def echoMode(self):
        return self.Password if self._properties.get("password", False) else self.Normal

    def selectAll(self):
        # DPG exposes selection as an immediate InputText interaction rather
        # than a retained API. Focus the editor and let Ctrl+A semantics remain
        # with Dear ImGui; keep this method for Qt-compatible call sites.
        return self.setFocus()

    def _focused(self):
        try:
            state = self.backend.get_item_state(self.tag) or {}
            return bool(state.get("active", False) or state.get("focused", False))
        except Exception:
            return False

    def _refresh_style(self, *_args):
        enabled = bool(self._properties.get("enabled", True))
        if self._apply_state_theme(focused=enabled and self._focused(), disabled=not enabled):
            return
        # Embedded editors (e.g. QFileDialog's location combo) supply their
        # own borderless theme. Passive focus handlers must not replace it
        # with the standalone QLineEdit frame and create a nested border.
        explicit = self.theme()
        if explicit is not None:
            native = explicit.nativeId() if hasattr(explicit, 'nativeId') else explicit
            self.backend.bind_item_theme(self.tag, native)
            return
        bind_theme(
            self.backend,
            self.tag,
            line_edit_theme,
            disabled=not enabled,
            focused=enabled and self._focused(),
        )

    def delete(self):
        handlers = self._focus_handlers
        super().delete()
        _delete_aux_item(self.backend, handlers)
        _delete_aux_item(self.backend, self._key_handlers)


class QPlainTextEdit(ImGuiLineEdit):
    """Multiline plain-text editor backed by one native InputText item."""

    def __init__(self, text="", *, parent=None, after=None, backend=None, width=-1,
                 height=-1, readonly=False, placeholder="", callback=None,
                 no_horizontal_scroll=False, **kwargs):
        kwargs = dict(kwargs)
        kwargs.update(
            multiline=True,
            height=int(height),
            no_horizontal_scroll=bool(no_horizontal_scroll),
        )
        super().__init__(
            text, parent=parent, after=after, backend=backend, width=width,
            readonly=readonly, placeholder=placeholder, callback=callback, **kwargs
        )

    def setPlainText(self, text):
        self.setText(text)

    def toPlainText(self):
        return self.text()

    def appendPlainText(self, text):
        current = self.text()
        suffix = str(text)
        self.setText((current + "\n" if current else "") + suffix)

    def insertPlainText(self, text):
        # DPG does not expose a retained caret position. Appending is the only
        # deterministic programmatic insertion that does not synthesize native
        # key events or steal user selection.
        self.appendPlainText(text)




class _ImGuiAbstractSpinBox(QWidget):
    """Dear ImGui scalar editor with Qt-like integrated up/down buttons.

    Dear PyGui's stock scalar step buttons are laid out like ImGui controls.
    This wrapper disables those buttons and composes one outer frame containing
    the real numeric editor plus a narrow two-button sub-control.  The numeric
    editor remains the actual hit target, so caret/selection behavior stays
    native to Dear ImGui.
    """

    _kind = "int"
    _button_width = METRICS.spin_arrow_width

    def _layout_tag(self):
        return self.container

    def __init__(self, value=0, *, parent=None, after=None, backend=None,
                 width=None, minimum=None, maximum=None, step=1, decimals=2,
                 callback=None):
        backend, parent_options = self._construction(parent, backend)
        self.valueChanged = Signal()
        self._external_callback = callback
        self._minimum = minimum
        self._maximum = maximum
        self._single_step = step
        self._decimals = int(decimals)
        self._handlers = None
        self._arrow_handlers = []
        self._arrow_triangles = []
        self._drawn_arrows = False

        shell_width = -1 if width is None else int(width)
        native_parent = parent_options.get("parent")
        # Keep the complete framed spin box at the same 26 px height as the
        # other Qt-like editors.  The previous +2 px shell made QSpinBox look
        # lower/taller than neighbouring combos and line edits in table rows.
        shell_options = {
            "width": shell_width,
            "height": METRICS.control_height,
            "border": True,
            "no_scrollbar": True,
            "no_scroll_with_mouse": True,
            "always_use_window_padding": True,
        }
        if native_parent is not None:
            shell_options["parent"] = native_parent
        self.container = backend.add_child_window(**shell_options)

        inner_height = max(20, METRICS.control_height - 2 * METRICS.border_size)
        with backend.table(
            parent=self.container,
            header_row=False,
            width=-1,
            height=inner_height,
            policy=backend.mvTable_SizingStretchProp,
            pad_outerX=False,
            borders_innerH=False,
            borders_outerH=False,
            borders_innerV=False,
            borders_outerV=False,
        ):
            backend.add_table_column(width_stretch=True, init_width_or_weight=1.0)
            backend.add_table_column(width_fixed=True, init_width_or_weight=self._button_width)
            with backend.table_row():
                native_value = self._coerce(value)
                input_options = {
                    "default_value": native_value,
                    "width": -1,
                    "step": 0,
                    "step_fast": 0,
                    "callback": self._changed,
                }
                if minimum is not None:
                    input_options.update(min_value=self._coerce(minimum), min_clamped=True)
                if maximum is not None:
                    input_options.update(max_value=self._coerce(maximum), max_clamped=True)
                if self._kind == "float":
                    input_options["format"] = self._format_string()
                    input_tag = backend.add_input_float(**input_options)
                else:
                    input_tag = backend.add_input_int(**input_options)

                with backend.group(horizontal=False, horizontal_spacing=0) as buttons:
                    half_height = max(10, inner_height // 2)
                    self.up_button = self._create_spin_arrow(
                        backend, half_height, direction=1)
                    self.down_button = self._create_spin_arrow(
                        backend, half_height, direction=-1)

        super().__init__(input_tag, parent=parent, after=after, backend=backend)
        self.valueChanged.owner = self
        self.separator = None
        self.buttons = buttons
        bind_theme(backend, self.buttons, spin_button_stack_theme)
        self._properties.update(value=native_value, enabled=True)
        bind_theme(backend, self.tag, spin_editor_theme, kind=self._kind, disabled=False)
        bind_theme(backend, self.container, spin_shell_theme, focused=False, disabled=False)
        if not self._drawn_arrows:
            for button in (self.up_button, self.down_button):
                bind_theme(backend, button, spin_button_theme, disabled=False)
        self._render_spin_arrows(enabled=True)
        self._bind_focus_handlers()

    def _create_spin_arrow(self, backend, height, direction):
        """Create a font-independent spin sub-control.

        Real Dear PyGui backends use draw-triangle geometry. Test/minimal
        backends that do not expose drawlists fall back to a blank button --
        never to ``^``/``v`` glyphs that depend on the active font atlas.
        """
        if hasattr(backend, "add_drawlist") and hasattr(backend, "draw_triangle"):
            item = backend.add_drawlist(width=self._button_width, height=height)
            # Paint only inside the existing arrow strip; the numeric editor
            # remains white and keeps its original native input hit region.
            if hasattr(backend, "draw_rectangle"):
                backend.draw_rectangle(
                    (0, 0), (self._button_width, height),
                    color=(0, 0, 0, 0), fill=(240, 240, 240, 255), parent=item)
            cx = self._button_width * 0.5
            cy = height * 0.5
            if direction > 0:
                points = ((cx - 3.5, cy + 1.7),
                          (cx + 3.5, cy + 1.7),
                          (cx, cy - 2.2))
            else:
                points = ((cx - 3.5, cy - 1.7),
                          (cx + 3.5, cy - 1.7),
                          (cx, cy + 2.2))
            # Draw the editor/button divider as a true single-pixel line in
            # the arrow strip.  The old dedicated 1 px table column acquired
            # extra table/child geometry on Windows and looked 2-3 px thick.
            if hasattr(backend, "draw_line"):
                try:
                    backend.draw_line((0.5, 0), (0.5, height),
                                      color=(188, 188, 188, 255),
                                      thickness=1.0, parent=item)
                except Exception:
                    pass
            triangle = backend.draw_triangle(
                *points, color=(40, 40, 40, 255), fill=(40, 40, 40, 255),
                parent=item)
            self._arrow_triangles.append(triangle)
            try:
                with backend.item_handler_registry() as registry:
                    backend.add_item_clicked_handler(
                        button=backend.mvMouseButton_Left,
                        callback=lambda *_args, _direction=direction:
                            self.stepBy(_direction),
                    )
                backend.bind_item_handler_registry(item, registry)
                self._arrow_handlers.append(registry)
            except Exception:
                pass
            self._drawn_arrows = True
            return item
        return backend.add_button(
            label="", width=self._button_width, height=height,
            callback=lambda *_args, _direction=direction: self.stepBy(_direction),
        )

    def _render_spin_arrows(self, enabled=True):
        """Do not mutate draw-triangle items after creation.

        Some Dear PyGui 2.3.1 Windows builds report a low-level
        ``configure_item`` SystemError for draw commands.  Enabled state is
        already enforced by ``stepBy``/``isEnabled`` and the numeric editor,
        so keeping the geometric arrow static is both safe and behaviorally
        correct.
        """
        return

    def _format_string(self):
        return "%.{}f".format(max(0, self._decimals))

    def _coerce(self, value):
        return float(value) if self._kind == "float" else int(value)

    def _clamp(self, value):
        value = self._coerce(value)
        if self._minimum is not None:
            value = max(value, self._coerce(self._minimum))
        if self._maximum is not None:
            value = min(value, self._coerce(self._maximum))
        return value

    def _changed(self, sender, value, *_args):
        if self._deleted:
            return
        value = self._clamp(value)
        old = self._properties.get("value")
        self._user_value(value)
        if old != value:
            self.valueChanged.emit(value)
        if callable(self._external_callback):
            try:
                self._external_callback(sender, value, None)
            except TypeError:
                try:
                    self._external_callback(sender, value)
                except TypeError:
                    self._external_callback(value)
        self._refresh_style()

    def value(self):
        self._require_ui()
        return self._coerce(self.backend.get_value(self.tag))

    def setValue(self, value):
        self._on_ui("value", self._set_spin_value, self._clamp(value))

    def _set_spin_value(self, value):
        old = self._properties.get("value")
        self._set_value(value)
        if old != value:
            self.valueChanged.emit(value)

    def setMinimum(self, value):
        self._minimum = self._coerce(value)
        self._on_ui("minimum", self._configure_limits)

    def minimum(self):
        return self._minimum

    def setMaximum(self, value):
        self._maximum = self._coerce(value)
        self._on_ui("maximum", self._configure_limits)

    def maximum(self):
        return self._maximum

    def setRange(self, minimum, maximum):
        self._minimum = self._coerce(minimum)
        self._maximum = self._coerce(maximum)
        self._on_ui("range", self._configure_limits)

    def _configure_limits(self):
        options = {}
        if self._minimum is not None:
            options.update(min_value=self._coerce(self._minimum), min_clamped=True)
        if self._maximum is not None:
            options.update(max_value=self._coerce(self._maximum), max_clamped=True)
        if options:
            self.backend.configure_item(self.tag, **options)
        self._set_spin_value(self._clamp(self.value()))

    def setSingleStep(self, step):
        self._single_step = self._coerce(step)

    def singleStep(self):
        return self._single_step

    def stepBy(self, steps):
        if not self.isEnabled():
            return
        self.setValue(self.value() + self._single_step * int(steps))

    def stepUp(self):
        self.stepBy(1)

    def stepDown(self):
        self.stepBy(-1)

    def _focused(self):
        try:
            state = self.backend.get_item_state(self.tag) or {}
            return bool(state.get("active", False) or state.get("focused", False))
        except Exception:
            return False

    def _refresh_style(self, *_args):
        if not hasattr(self, "container"):
            return
        enabled = bool(self._properties.get("enabled", True))
        bind_theme(self.backend, self.tag, spin_editor_theme,
                   kind=self._kind, disabled=not enabled)
        bind_theme(self.backend, self.container, spin_shell_theme,
                   focused=enabled and self._focused(), disabled=not enabled)
        if self._drawn_arrows:
            self._render_spin_arrows(enabled=enabled)
        else:
            for button in (self.up_button, self.down_button):
                bind_theme(self.backend, button, spin_button_theme, disabled=not enabled)

    def _set_enabled_now(self, enabled):
        enabled = bool(enabled)
        self._properties["enabled"] = enabled
        try:
            self.backend.configure_item(self.tag, enabled=enabled)
        except Exception:
            pass
        if not self._drawn_arrows:
            for item in (self.up_button, self.down_button):
                try:
                    self.backend.configure_item(item, enabled=enabled)
                except Exception:
                    pass
        self._refresh_style()

    def _bind_focus_handlers(self):
        try:
            with self.backend.item_handler_registry() as registry:
                if hasattr(self.backend, "add_item_focus_handler"):
                    self.backend.add_item_focus_handler(callback=self._refresh_style)
                if hasattr(self.backend, "add_item_activated_handler"):
                    self.backend.add_item_activated_handler(callback=self._refresh_style)
                if hasattr(self.backend, "add_item_deactivated_handler"):
                    self.backend.add_item_deactivated_handler(callback=self._refresh_style)
            self.backend.bind_item_handler_registry(self.tag, registry)
            self._handlers = registry
        except Exception:
            self._handlers = None

    def delete(self):
        self._require_ui()
        if self._deleted:
            return
        handlers = self._handlers
        arrow_handlers = tuple(self._arrow_handlers)
        container = self.container
        # QObject/widget bookkeeping is anchored to the numeric editor tag.
        super().delete()
        for item in (handlers, *arrow_handlers, container):
            try:
                if item and self.backend.does_item_exist(item):
                    self.backend.delete_item(item)
            except Exception:
                pass


class ImGuiSpinBox(_ImGuiAbstractSpinBox):
    _kind = "int"


class ImGuiDoubleSpinBox(_ImGuiAbstractSpinBox):
    _kind = "float"

    def setDecimals(self, decimals):
        self._decimals = max(0, int(decimals))
        self._on_ui("format", self._configure, "format", self._format_string())

    def decimals(self):
        return self._decimals




QLineEdit = ImGuiLineEdit
QSpinBox = ImGuiSpinBox
QDoubleSpinBox = ImGuiDoubleSpinBox
__all__ = [
    "ImGuiLineEdit", "ImGuiSpinBox", "ImGuiDoubleSpinBox",
    "QLineEdit", "QPlainTextEdit", "QSpinBox", "QDoubleSpinBox",
]
