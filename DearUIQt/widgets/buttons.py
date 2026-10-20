"""Label and push-button controls."""
from __future__ import annotations

from ..core.object import Signal, QSignalBlocker
from ..gui.style import bind_theme, button_theme, tool_button_theme, METRICS
from .widget import QWidget
from ._utils import _bind_focus_state_handlers, _delete_aux_item

class ImGuiLabel(QWidget):
    def __init__(self, text="", *, parent=None, after=None, backend=None,
                 wrap=0, color=None, tag=None):
        backend, options = self._construction(parent, backend)
        if wrap:
            options["wrap"] = int(wrap)
        if color is not None:
            options["color"] = tuple(color)
        if tag is not None:
            options["tag"] = tag
        super().__init__(backend.add_text(str(text), **options), parent=parent, after=after, backend=backend)
        self._properties["value"] = str(text)
        self._wrap_width = max(0, int(wrap or 0))

    def setWordWrap(self, enabled):
        enabled = bool(enabled)
        if not enabled:
            self._wrap_width = 0
            self._configure("wrap", 0)
        elif self._wrap_width <= 0:
            self._wrap_width = 320
            self._configure("wrap", self._wrap_width)

    def wordWrap(self):
        return self._wrap_width > 0

    def setWrapWidth(self, width):
        self._wrap_width = max(0, int(width))
        self._configure("wrap", self._wrap_width)

    def wrapWidth(self):
        return self._wrap_width

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
                 height=None, role="secondary", default=False, checkable=False, checked=False,
                 icon=None, icon_size=None):
        backend, options = self._construction(parent, backend)
        requested_text = str(text)
        self._icon = icon
        if icon_size is None:
            icon_size = (20, 20)
        elif isinstance(icon_size, (int, float)):
            icon_size = (int(icon_size), int(icon_size))
        else:
            icon_size = tuple(icon_size)
        if len(icon_size) != 2:
            raise ValueError("icon_size requires width and height")
        self._icon_size = (max(1, int(icon_size[0])), max(1, int(icon_size[1])))
        self._image_button = bool(
            icon is not None and not requested_text and hasattr(backend, "add_image_button"))
        if self._image_button:
            # Dear PyGui image-button width/height describe image content, not
            # the outer hit rectangle.  QToolButton's theme padding supplies
            # the frame around this icon size.
            options["width"], options["height"] = self._icon_size
        else:
            if width is not None:
                options["width"] = width
            # QPushButton has a stable style-driven height in Qt.  Do not let
            # arbitrary surrounding ImGui item spacing determine button geometry.
            options["height"] = METRICS.button_height if height is None else int(height)
        self.clicked = Signal()
        self.toggled = Signal()
        self._checkable = bool(checkable)
        self._checked = bool(checked) if self._checkable else False
        requested_role = str(role or "secondary")
        self._default = bool(default)
        self._default_promoted = self._default and requested_role == "secondary"
        self.role = "primary" if self._default_promoted else requested_role
        self._focus_handlers = None
        self._default_action = None
        self._action_connections = []
        self._dialog_pointer_routing = False
        self._pointer_pressed = False
        self._pointer_generation = 0
        self._native_pointer_suppressed = False
        if self._image_button:
            native_icon = icon.nativeId() if hasattr(icon, "nativeId") else icon
            tag = backend.add_image_button(native_icon, callback=self._clicked, **options)
        else:
            tag = backend.add_button(label=requested_text, callback=self._clicked, **options)
        super().__init__(tag, parent=parent, after=after, backend=backend)
        self.clicked.owner = self
        self.toggled.owner = self
        self._properties.update(label=requested_text, enabled=True, icon=icon)
        self._focus_handlers = _bind_focus_state_handlers(
            backend, self.tag, self._refresh_style)
        self._refresh_style()

    def _clicked(self, *_args):
        # Dialogs deliver pointer gestures through QApplication. Native ImGui
        # activation is still a fallback for keyboard/non-dialog controls, but
        # must not emit a second clicked() for that same physical mouse release.
        if _args and self._dialog_pointer_routing and self._after is not None:
            from ..core.application import QApplication
            application = QApplication.instance()
            if application is not None and application._pointer_bridge_installed:
                if self._native_pointer_suppressed:
                    return
                # A fast click can enqueue the widget callback before the
                # global press/release handlers. Let that input batch finish
                # before deciding whether native delivery is still needed.
                self._after(0, self._deliver_native_click)
                return
        self._activate_click()

    def _deliver_native_click(self):
        if not self._native_pointer_suppressed and not self._deleted and self.isVisible():
            self._activate_click()

    def _begin_pointer_click(self):
        if self._deleted or not self.isEnabled():
            return False
        if not self._pointer_pressed:
            self._pointer_generation += 1
        self._pointer_pressed = True
        self._native_pointer_suppressed = True
        return True

    def _end_pointer_click(self, activate):
        pressed = self._pointer_pressed
        self._pointer_pressed = False
        generation = self._pointer_generation
        if self._after is not None:
            self._after(0, self._clear_pointer_suppression, generation)
        if pressed and activate:
            self._activate_click()

    def _clear_pointer_suppression(self, generation):
        if generation == self._pointer_generation and not self._pointer_pressed:
            self._native_pointer_suppressed = False

    def _activate_click(self):
        if self._deleted or not self.isEnabled():
            return
        if self._updates is not None:
            self._updates.discard("checked")
        if self._default_action is not None:
            previous_checked = self._checked
            if not self._default_action.trigger():
                return
            if previous_checked != self._checked:
                self.toggled.emit(self._checked)
        elif self._checkable:
            self._set_checked_now(not self._checked)
        self.clicked.emit()

    def defaultAction(self):
        return self._default_action

    def setDefaultAction(self, action):
        """QToolButton-style shared-action binding, also supported by this button."""
        from ..gui.action import QAction
        self._require_ui()
        if self._deleted:
            raise RuntimeError("cannot bind an action to a deleted button")
        if action is not None:
            if not isinstance(action, QAction):
                raise TypeError("default action must be QAction or None")
            if action._deleted or action.threadId() != self.threadId():
                raise RuntimeError("action must be live and belong to the button's thread")
        for connection in self._action_connections:
            connection.disconnect()
        self._action_connections.clear()
        self._default_action = action
        if action is not None:
            self._action_connections = [
                action.changed.connect(self._sync_default_action),
                action.destroyed.connect(self._default_action_destroyed),
            ]
            self._sync_default_action()

    def _sync_default_action(self):
        action = self._default_action
        if action is None or self._deleted:
            return
        with QSignalBlocker(self):
            self.setText(action.text())
            self.setEnabled(action.isEnabled())
            self.setVisible(action.isVisible())
            self.setCheckable(action.isCheckable())
            self.setChecked(action.isChecked())
            if action.icon() is not None:
                self.setIcon(action.icon())
            # Tooltip allocation is only necessary when its text changed.
            if self.toolTip() != action.toolTip():
                self.setToolTip(action.toolTip())

    def _default_action_destroyed(self, action):
        if self._default_action is action:
            self.setDefaultAction(None)
            self.setEnabled(False)

    def click(self):
        """Programmatically click the button, matching QPushButton::click()."""
        self._require_ui()
        if self._deleted or not self.isEnabled():
            return False
        self._activate_click()
        return True

    def setCheckable(self, checkable):
        self._on_ui("checkable", self._set_checkable_now, bool(checkable))

    def _set_checkable_now(self, checkable):
        self._checkable = checkable
        if not checkable:
            self._set_checked_now(False)

    def isCheckable(self):
        self._require_ui()
        return self._checkable

    def setChecked(self, checked):
        self._on_ui("checked", self._set_checked_now, bool(checked))

    def _set_checked_now(self, checked):
        checked = bool(checked) and self._checkable
        if checked != self._checked:
            self._checked = checked
            self._refresh_style()
            self.toggled.emit(checked)

    def isChecked(self):
        self._require_ui()
        return self._checked

    def toggle(self):
        self._require_ui()
        self.setChecked(not self._checked)

    def setText(self, text):
        text = str(text)
        if self._image_button:
            # Image-only buttons have no native label. Retain the Qt property
            # so QAction/QToolButton APIs remain coherent without replacing the
            # native DPG item at runtime.
            self._properties["label"] = text
            return
        self._on_ui("label", self._configure, "label", text)

    def text(self):
        return str(self._properties.get("label", ""))

    def setIcon(self, icon):
        self._icon = icon
        self._properties["icon"] = icon
        if self._image_button:
            # ``texture_tag`` is the native mvImageButton texture property.
            # Backend-light test doubles may not support it, so keep the
            # retained Qt state authoritative when configuration is unavailable.
            try:
                native_icon = icon.nativeId() if hasattr(icon, "nativeId") else icon
                self._on_ui("texture_tag", self._configure, "texture_tag", native_icon)
            except Exception:
                pass

    def icon(self):
        return self._icon

    def setIconSize(self, size):
        if isinstance(size, (int, float)):
            size = (int(size), int(size))
        size = tuple(size)
        if len(size) != 2:
            raise ValueError("icon size requires width and height")
        self._icon_size = (max(1, int(size[0])), max(1, int(size[1])))
        if self._image_button:
            self._on_ui(
                "icon-size", self._configure_many,
                width=self._icon_size[0], height=self._icon_size[1])

    def iconSize(self):
        return self._icon_size

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
        if self._apply_state_theme(focused=enabled and self._focused(), disabled=not enabled):
            return
        if self.theme() is not None:
            self.setTheme(self.theme())
            return
        bind_theme(
            self.backend,
            self.tag,
            button_theme,
            role=self.role,
            disabled=not enabled,
            focused=enabled and self._focused(),
            default=self._default,
            checked=self._checked,
        )

    def delete(self):
        self._require_ui()
        if self._deleted:
            return
        self.setDefaultAction(None)
        handlers = self._focus_handlers
        super().delete()
        _delete_aux_item(self.backend, handlers)


class QToolButton(ImGuiPushButton):
    """Compact flat action button with QToolButton-style menu support."""

    DelayedPopup = 0
    MenuButtonPopup = 1
    InstantPopup = 2

    def __init__(self, text="", *, parent=None, after=None, backend=None,
                 width=None, height=28, auto_raise=True, icon=None, icon_size=(20, 20)):
        self._auto_raise = bool(auto_raise)
        self._menu = None
        self._popup_mode = self.DelayedPopup
        super().__init__(
            text,
            parent=parent,
            after=after,
            backend=backend,
            width=width,
            height=height,
            role="flat" if self._auto_raise else "secondary",
            icon=icon,
            icon_size=icon_size,
        )

    def _refresh_style(self, *_args):
        # QToolButton uses one compact, transparent chrome for both text and
        # image variants.  The theme targets mvButton and mvImageButton, unlike
        # QPushButton's raised surface theme which only targets mvButton.
        enabled = bool(self._properties.get("enabled", True))
        if self._apply_state_theme(focused=enabled and self._focused(), disabled=not enabled):
            return
        if self.theme() is not None:
            self.setTheme(self.theme())
            return
        bind_theme(
            self.backend,
            self.tag,
            tool_button_theme,
            disabled=not enabled,
            frame_padding=(4, 3),
        )

    def setAutoRaise(self, enabled):
        self._auto_raise = bool(enabled)
        self.setRole("flat" if self._auto_raise else "secondary")

    def autoRaise(self):
        return self._auto_raise

    def setMenu(self, menu):
        from .menu import QMenu
        if menu is not None and not isinstance(menu, QMenu):
            raise TypeError("tool button menu must be QMenu or None")
        self._menu = menu

    def menu(self):
        return self._menu

    def setPopupMode(self, mode):
        mode = int(mode)
        if mode not in (self.DelayedPopup, self.MenuButtonPopup, self.InstantPopup):
            raise ValueError("invalid QToolButton popup mode")
        self._popup_mode = mode

    def popupMode(self):
        return self._popup_mode

    def showMenu(self):
        menu = self._menu
        if menu is None:
            return False
        try:
            x, y = self.backend.get_item_rect_min(self.tag)
            _width, height = self.backend.get_item_rect_size(self.tag)
            menu.popup((x, y + height))
        except Exception:
            menu.popup()
        return True

    def _clicked(self, *_args):
        if self._popup_mode == self.InstantPopup and self._menu is not None:
            self.showMenu()
            return
        super()._clicked(*_args)


QLabel = ImGuiLabel
QPushButton = ImGuiPushButton
__all__ = ["ImGuiLabel", "ImGuiPushButton", "QLabel", "QPushButton", "QToolButton"]
