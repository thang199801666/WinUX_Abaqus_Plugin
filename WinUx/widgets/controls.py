"""Retained Dear ImGui controls with Qt-like properties and signals.

These widgets are *not* Qt wrappers.  They own Dear PyGui items and expose the
small Qt-style property/signal surface WinUx needs so dialogs can share one
consistent interaction contract without introducing another UI toolkit.
"""
from __future__ import annotations

import inspect
import threading

from ..runtime.latest_call import LatestCallQueue
from .core import QObject, Signal
from .imgui_qt_style import (
    bind_theme,
    button_theme,
    checkbox_theme,
    radio_group_theme,
    line_edit_theme,
    progress_theme,
    group_box_theme,
    spin_editor_theme,
    spin_shell_theme,
    spin_button_theme,
    spin_button_stack_theme,
    separator_theme,
    METRICS,
)


def _bind_focus_state_handlers(backend, item, callback):
    """Bind passive focus/activation handlers without changing ImGui focus.

    The callbacks only refresh visual state.  They never call ``focus_item``
    from a mouse event, which keeps native InputText caret placement intact.
    """
    try:
        with backend.item_handler_registry() as registry:
            if hasattr(backend, "add_item_focus_handler"):
                backend.add_item_focus_handler(callback=callback)
            if hasattr(backend, "add_item_activated_handler"):
                backend.add_item_activated_handler(callback=callback)
            if hasattr(backend, "add_item_deactivated_handler"):
                backend.add_item_deactivated_handler(callback=callback)
        backend.bind_item_handler_registry(item, registry)
        return registry
    except Exception:
        return None


def _delete_aux_item(backend, item):
    try:
        if item and backend.does_item_exist(item):
            backend.delete_item(item)
    except Exception:
        pass


class QWidget(QObject):
    """Base retained wrapper over one Dear PyGui item.

    The API intentionally mirrors the useful subset of QWidget properties:
    object name, dynamic properties, visibility/enabled state, geometry hints,
    tooltip and focus.  DPG remains the renderer and event owner.
    """

    def __init__(self, tag, *, parent=None, after=None, backend=None):
        super().__init__(parent=parent if isinstance(parent, QObject) else None, after=after)
        if backend is None:
            import dearpygui.dearpygui as backend
        self.backend = backend
        self.tag = tag
        self._ui_thread = threading.get_ident()
        self._properties = {}
        self._dynamic_properties = {}
        self._object_name = ""
        self._tooltip = None
        self._tooltip_text = None
        self._updates = LatestCallQueue(self._after) if self._after is not None else None

    @staticmethod
    def _construction(parent, backend):
        if isinstance(parent, QObject) and parent._deleted:
            raise RuntimeError("cannot construct a child of a deleted parent")
        if backend is None:
            backend = getattr(parent, "backend", None)
        if backend is None:
            import dearpygui.dearpygui as backend
        native_parent = getattr(parent, "tag", None) if isinstance(parent, QObject) else parent
        options = {} if native_parent is None else {"parent": native_parent}
        return backend, options

    def _on_ui(self, key, callback, *args):
        if self._deleted:
            return
        if threading.get_ident() == self._ui_thread:
            if self._updates is not None:
                self._updates.discard(key)
            callback(*args)
        elif self._updates is not None:
            self._updates.post(key, self._deliver, callback, args)
        else:
            raise RuntimeError("worker updates require a UI scheduler")

    def _deliver(self, callback, args):
        self._require_ui()
        if not self._deleted and self.backend.does_item_exist(self.tag):
            callback(*args)

    def _require_ui(self):
        if threading.get_ident() != self._ui_thread:
            raise RuntimeError("native widget access requires the UI thread")

    def _configure(self, key, value):
        if self._properties.get(key, object()) != value:
            self.backend.configure_item(self.tag, **{key: value})
            self._properties[key] = value

    def _set_value(self, value):
        if self._properties.get("value", object()) != value:
            self.backend.set_value(self.tag, value)
            self._properties["value"] = value

    def _user_value(self, value):
        # Native interaction is newer than any display value queued by a worker.
        self._require_ui()
        if self._updates is not None:
            self._updates.discard("value")
        self._properties["value"] = value

    # ---------------------------------------------------------------- Qt-like common properties
    def setObjectName(self, name):
        self._object_name = str(name or "")

    def objectName(self):
        return self._object_name

    def setProperty(self, name, value):
        self._dynamic_properties[str(name)] = value
        return True

    def property(self, name):
        return self._dynamic_properties.get(str(name))

    def setEnabled(self, enabled):
        self._on_ui("enabled", self._set_enabled_now, bool(enabled))

    def _set_enabled_now(self, enabled):
        self._configure("enabled", bool(enabled))
        self._refresh_style()

    def isEnabled(self):
        self._require_ui()
        try:
            return bool(self.backend.get_item_configuration(self.tag).get("enabled", True))
        except Exception:
            return bool(self._properties.get("enabled", True))

    def setDisabled(self, disabled):
        self.setEnabled(not bool(disabled))

    def setVisible(self, visible):
        self._on_ui("show", self._configure, "show", bool(visible))

    def isVisible(self):
        self._require_ui()
        try:
            return bool(self.backend.get_item_configuration(self.tag).get("show", True))
        except Exception:
            return bool(self._properties.get("show", True))

    def show(self):
        self.setVisible(True)

    def hide(self):
        self.setVisible(False)

    def setFixedWidth(self, width):
        self._on_ui("width", self._configure, "width", int(width))

    def setFixedHeight(self, height):
        self._on_ui("height", self._configure, "height", int(height))

    def setFixedSize(self, width, height):
        self.setFixedWidth(width)
        self.setFixedHeight(height)

    def resize(self, width, height):
        self.setFixedSize(width, height)

    def width(self):
        self._require_ui()
        try:
            return int(self.backend.get_item_configuration(self.tag).get("width", 0))
        except Exception:
            return int(self._properties.get("width", 0) or 0)

    def height(self):
        self._require_ui()
        try:
            return int(self.backend.get_item_configuration(self.tag).get("height", 0))
        except Exception:
            return int(self._properties.get("height", 0) or 0)

    def setFocus(self):
        self._require_ui()
        try:
            self.backend.focus_item(self.tag)
            return True
        except Exception:
            return False

    def hasFocus(self):
        self._require_ui()
        try:
            state = self.backend.get_item_state(self.tag) or {}
            return bool(state.get("focused", False) or state.get("active", False))
        except Exception:
            return False

    def setToolTip(self, text):
        self._require_ui()
        text = str(text or "")
        self._tooltip_text = text
        try:
            if self._tooltip is None or not self.backend.does_item_exist(self._tooltip):
                with self.backend.tooltip(self.tag) as tooltip:
                    self._tooltip = tooltip
                    self.backend.add_text(text)
            else:
                children = self.backend.get_item_children(self._tooltip, 1) or []
                if children:
                    self.backend.set_value(children[0], text)
        except Exception:
            # Fake backends and old DPG builds can still use the property API.
            pass

    def toolTip(self):
        return self._tooltip_text or ""

    def _refresh_style(self):
        """Subclass hook after enabled/style-role changes."""

    def delete(self):
        self._require_ui()
        if self._deleted:
            return
        if self._updates is not None:
            self._updates.close()
        try:
            super().delete()
        finally:
            if self.backend.does_item_exist(self.tag):
                self.backend.delete_item(self.tag)


class ImGuiLabel(QWidget):
    def __init__(self, text="", *, parent=None, after=None, backend=None):
        backend, options = self._construction(parent, backend)
        super().__init__(backend.add_text(str(text), **options), parent=parent, after=after, backend=backend)
        self._properties["value"] = str(text)

    def setText(self, text):
        self._on_ui("value", self._set_value, str(text))

    def text(self):
        self._require_ui()
        try:
            return str(self.backend.get_value(self.tag))
        except Exception:
            return str(self._properties.get("value", ""))


class ImGuiPushButton(QWidget):
    def __init__(self, text="", *, parent=None, after=None, backend=None, width=None,
                 height=None, role="secondary", default=False):
        backend, options = self._construction(parent, backend)
        if width is not None:
            options["width"] = width
        if height is not None:
            options["height"] = height
        self.clicked = Signal()
        requested_role = str(role or "secondary")
        self._default = bool(default)
        self._default_promoted = self._default and requested_role == "secondary"
        self.role = "primary" if self._default_promoted else requested_role
        self._focus_handlers = None
        super().__init__(backend.add_button(label=str(text), callback=self._clicked, **options),
                         parent=parent, after=after, backend=backend)
        self.clicked.owner = self
        self._properties.update(label=str(text), enabled=True)
        self._focus_handlers = _bind_focus_state_handlers(
            backend, self.tag, self._refresh_style)
        self._refresh_style()

    def _clicked(self, *_args):
        if not self._deleted:
            self.clicked.emit()

    def setText(self, text):
        self._on_ui("label", self._configure, "label", str(text))

    def text(self):
        return str(self._properties.get("label", ""))

    def setDefault(self, default):
        default = bool(default)
        if default and not self._default and self.role == "secondary":
            self.role = "primary"
            self._default_promoted = True
        elif not default and self._default_promoted:
            self.role = "secondary"
            self._default_promoted = False
        self._default = default
        self._refresh_style()

    def isDefault(self):
        return bool(self._default)

    def setRole(self, role):
        self.role = str(role or "secondary")
        self._default_promoted = False
        self._refresh_style()

    def _focused(self):
        try:
            state = self.backend.get_item_state(self.tag) or {}
            return bool(state.get("active", False) or state.get("focused", False))
        except Exception:
            return False

    def _refresh_style(self, *_args):
        enabled = bool(self._properties.get("enabled", True))
        bind_theme(
            self.backend,
            self.tag,
            button_theme,
            role=self.role,
            disabled=not enabled,
            focused=enabled and self._focused(),
            default=self._default,
        )

    def delete(self):
        handlers = self._focus_handlers
        super().delete()
        _delete_aux_item(self.backend, handlers)


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
        self._external_callback = callback
        self._focus_handlers = None
        if width is not None:
            options["width"] = width
        options.update(kwargs)
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
        self._properties.update(value=str(text), enabled=True, readonly=bool(readonly),
                                placeholder=str(placeholder or ""), password=bool(password))
        self._focus_handlers = _bind_focus_state_handlers(
            backend, self.tag, self._refresh_style)
        self._refresh_style()

    def _changed(self, sender, value, *_args):
        if not self._deleted:
            value = str(value)
            changed = self._properties.get("value") != value
            self._user_value(value)
            if changed:
                self.textEdited.emit(value)
                self.textChanged.emit(value)
            self._invoke_external_callback(sender, value)

    def _invoke_external_callback(self, sender, value):
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
            callback(sender, value, None)

    def setText(self, text):
        self._on_ui("value", self._set_text, str(text))

    def _set_text(self, text):
        changed = self._properties.get("value") != text
        self._set_value(text)
        if changed:
            self.textChanged.emit(text)

    def text(self):
        self._require_ui()
        return str(self.backend.get_value(self.tag))

    def clear(self):
        self.setText("")

    def setReadOnly(self, readonly):
        self._properties["readonly"] = bool(readonly)
        self._on_ui("readonly", self._configure, "readonly", bool(readonly))

    def isReadOnly(self):
        return bool(self._properties.get("readonly", False))

    def setPlaceholderText(self, text):
        text = str(text or "")
        self._properties["placeholder"] = text
        self._on_ui("hint", self._configure, "hint", text)

    def placeholderText(self):
        return str(self._properties.get("placeholder", ""))

    def setEchoMode(self, mode):
        password = mode in (self.Password, True, "password")
        self._properties["password"] = bool(password)
        self._on_ui("password", self._configure, "password", bool(password))

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
        shell_options = {
            "width": shell_width,
            "height": METRICS.control_height + 2,
            "border": True,
            "no_scrollbar": True,
            "no_scroll_with_mouse": True,
        }
        if native_parent is not None:
            shell_options["parent"] = native_parent
        self.container = backend.add_child_window(**shell_options)

        with backend.table(
            parent=self.container,
            header_row=False,
            width=-1,
            height=METRICS.control_height,
            policy=backend.mvTable_SizingStretchProp,
            pad_outerX=False,
            borders_innerH=False,
            borders_outerH=False,
            borders_innerV=False,
            borders_outerV=False,
        ):
            backend.add_table_column(width_stretch=True, init_width_or_weight=1.0)
            backend.add_table_column(width_fixed=True, init_width_or_weight=1)
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

                separator = backend.add_child_window(
                    width=1, height=METRICS.control_height, border=False,
                    no_scrollbar=True, no_scroll_with_mouse=True,
                )
                with backend.group(horizontal=False, horizontal_spacing=0) as buttons:
                    half_height = max(10, METRICS.control_height // 2)
                    self.up_button = self._create_spin_arrow(
                        backend, half_height, direction=1)
                    self.down_button = self._create_spin_arrow(
                        backend, half_height, direction=-1)

        super().__init__(input_tag, parent=parent, after=after, backend=backend)
        self.valueChanged.owner = self
        self.separator = separator
        self.buttons = buttons
        bind_theme(backend, self.buttons, spin_button_stack_theme)
        self._properties.update(value=native_value, enabled=True)
        bind_theme(backend, self.tag, spin_editor_theme, kind=self._kind, disabled=False)
        bind_theme(backend, self.container, spin_shell_theme, focused=False, disabled=False)
        bind_theme(backend, self.separator, separator_theme)
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



class ImGuiGroupBox(QWidget):
    """Compact Dear ImGui group container with QGroupBox-like properties."""

    def __init__(self, title="", *, parent=None, after=None, backend=None,
                 width=-1, auto_resize_y=True):
        backend, options = self._construction(parent, backend)
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
    """Use normalized values (0..1), matching WinUx transfer ratios."""

    def __init__(self, *, parent=None, after=None, backend=None):
        backend, options = self._construction(parent, backend)
        super().__init__(backend.add_progress_bar(width=-1, overlay="0%", **options),
                         parent=parent, after=after, backend=backend)
        bind_theme(self.backend, self.tag, progress_theme)

    def setValue(self, value):
        self._on_ui("value", self._set_value, max(0.0, min(1.0, float(value))))

    def setFormat(self, text):
        self._on_ui("overlay", self._configure, "overlay", str(text))


class ImGuiCheckBox(QWidget):
    """Boolean Dear ImGui checkbox with Qt-like retained signals/properties."""

    def __init__(self, text="", *, checked=False, parent=None, after=None, backend=None):
        backend, options = self._construction(parent, backend)
        self.toggled = Signal()
        self.stateChanged = Signal()
        self._focus_handlers = None
        super().__init__(backend.add_checkbox(label=str(text), default_value=bool(checked),
                         callback=self._changed, **options), parent=parent, after=after, backend=backend)
        self.toggled.owner = self
        self.stateChanged.owner = self
        self._properties.update(value=bool(checked), label=str(text), enabled=True)
        self._focus_handlers = _bind_focus_state_handlers(
            backend, self.tag, self._refresh_style)
        self._refresh_style()

    def _changed(self, sender, value, *_args):
        if not self._deleted:
            value = bool(value)
            changed = self._properties.get("value") != value
            self._user_value(value)
            self._refresh_style()
            if changed:
                self.toggled.emit(value)
                self.stateChanged.emit(2 if value else 0)

    def setChecked(self, checked):
        self._on_ui("value", self._set_checked, bool(checked))

    def _set_checked(self, checked):
        changed = self._properties.get("value") != checked
        self._set_value(checked)
        self._refresh_style()
        if changed:
            self.toggled.emit(checked)
            self.stateChanged.emit(2 if checked else 0)

    def isChecked(self):
        self._require_ui()
        return bool(self.backend.get_value(self.tag))

    def setText(self, text):
        self._on_ui("label", self._configure, "label", str(text))

    def text(self):
        return str(self._properties.get("label", ""))

    def _focused(self):
        try:
            state = self.backend.get_item_state(self.tag) or {}
            return bool(state.get("active", False) or state.get("focused", False))
        except Exception:
            return False

    def _refresh_style(self, *_args):
        enabled = bool(self._properties.get("enabled", True))
        checked = bool(self._properties.get("value", False))
        bind_theme(
            self.backend,
            self.tag,
            checkbox_theme,
            disabled=not enabled,
            checked=checked,
            focused=enabled and self._focused(),
        )

    def delete(self):
        handlers = self._focus_handlers
        super().delete()
        _delete_aux_item(self.backend, handlers)


class ImGuiRadioButtonGroup(QWidget):
    """Retained wrapper over Dear ImGui's native radio-button group.

    Qt uses individual ``QRadioButton`` widgets plus an optional
    ``QButtonGroup``.  Dear PyGui exposes a native grouped radio control, which
    is a better behavioral fit for WinUx because it preserves keyboard/mouse
    ownership in Dear ImGui.  This wrapper provides the small Qt-like value and
    signal surface the dialogs need without synthesizing extra hit targets.
    """

    def __init__(self, items=(), *, current=None, horizontal=False, parent=None,
                 after=None, backend=None, callback=None):
        backend, options = self._construction(parent, backend)
        self.currentTextChanged = Signal()
        self.currentIndexChanged = Signal()
        self.activated = Signal()
        self._external_callback = callback
        self._items = [str(item) for item in items]
        if current is None:
            current = self._items[0] if self._items else ""
        current = str(current)
        if self._items and current not in self._items:
            current = self._items[0]
        self._focus_handlers = None
        super().__init__(backend.add_radio_button(
            self._items,
            default_value=current,
            horizontal=bool(horizontal),
            callback=self._changed,
            **options,
        ), parent=parent, after=after, backend=backend)
        self.currentTextChanged.owner = self
        self.currentIndexChanged.owner = self
        self.activated.owner = self
        self._properties.update(value=current, enabled=True)
        self._focus_handlers = _bind_focus_state_handlers(
            backend, self.tag, self._refresh_style)
        self._refresh_style()

    def _index_of(self, text):
        try:
            return self._items.index(str(text))
        except ValueError:
            return -1

    def _changed(self, sender, value, *_args):
        if self._deleted:
            return
        value = str(value)
        old = str(self._properties.get("value", ""))
        self._user_value(value)
        if old != value:
            self.currentTextChanged.emit(value)
            self.currentIndexChanged.emit(self._index_of(value))
        self.activated.emit(value)
        callback = self._external_callback
        if callable(callback):
            try:
                callback(sender, value, None)
            except TypeError:
                try:
                    callback(sender, value)
                except TypeError:
                    callback()

    def setCurrentText(self, text):
        text = str(text)
        if text not in self._items:
            return False
        self._on_ui("value", self._set_current_text, text)
        return True

    def _set_current_text(self, text):
        old = str(self._properties.get("value", ""))
        self._set_value(text)
        if old != text:
            self.currentTextChanged.emit(text)
            self.currentIndexChanged.emit(self._index_of(text))

    def currentText(self):
        self._require_ui()
        try:
            return str(self.backend.get_value(self.tag))
        except Exception:
            return str(self._properties.get("value", ""))

    def currentIndex(self):
        return self._index_of(self.currentText())

    def setCurrentIndex(self, index):
        index = int(index)
        if not 0 <= index < len(self._items):
            return False
        return self.setCurrentText(self._items[index])

    def count(self):
        return len(self._items)

    def itemText(self, index):
        index = int(index)
        return self._items[index] if 0 <= index < len(self._items) else ""

    def items(self):
        return tuple(self._items)

    def _focused(self):
        try:
            state = self.backend.get_item_state(self.tag) or {}
            return bool(state.get("active", False) or state.get("focused", False))
        except Exception:
            return False

    def _refresh_style(self, *_args):
        enabled = bool(self._properties.get("enabled", True))
        bind_theme(
            self.backend,
            self.tag,
            radio_group_theme,
            disabled=not enabled,
            focused=enabled and self._focused(),
        )

    def delete(self):
        handlers = self._focus_handlers
        super().delete()
        _delete_aux_item(self.backend, handlers)


# Qt-style names remain compatibility aliases only.  New WinUx UI code should
# prefer ImGui* names so the backend is always explicit.
QLabel = ImGuiLabel
QPushButton = ImGuiPushButton
QLineEdit = ImGuiLineEdit
QProgressBar = ImGuiProgressBar
QCheckBox = ImGuiCheckBox
QRadioButtonGroup = ImGuiRadioButtonGroup
QSpinBox = ImGuiSpinBox
QDoubleSpinBox = ImGuiDoubleSpinBox
QGroupBox = ImGuiGroupBox


__all__ = [
    "QWidget", "ImGuiLabel", "ImGuiPushButton", "ImGuiLineEdit",
    "ImGuiProgressBar", "ImGuiCheckBox", "ImGuiSpinBox",
    "ImGuiDoubleSpinBox", "ImGuiGroupBox", "ImGuiRadioButtonGroup", "QLabel", "QPushButton", "QLineEdit",
    "QProgressBar", "QCheckBox", "QRadioButtonGroup", "QSpinBox", "QDoubleSpinBox", "QGroupBox",
]
