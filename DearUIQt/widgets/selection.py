"""Boolean and radio-selection controls."""
from __future__ import annotations

from ..core.object import QObject, Signal
from ..gui.style import bind_theme, checkbox_theme, radio_group_theme
from .widget import QWidget
from ._utils import _bind_focus_state_handlers, _delete_aux_item

class ImGuiCheckBox(QWidget):
    """Boolean Dear ImGui checkbox with Qt-like retained signals/properties."""
    Unchecked = 0
    Checked = 2

    def __init__(self, text="", *, checked=False, parent=None, after=None, backend=None):
        backend, options = self._construction(parent, backend)
        self.toggled = Signal()
        self.stateChanged = Signal()
        self.clicked = Signal()
        self._focus_handlers = None
        super().__init__(backend.add_checkbox(label=str(text), default_value=bool(checked),
                         callback=self._changed, **options), parent=parent, after=after, backend=backend)
        self.toggled.owner = self
        self.stateChanged.owner = self
        self.clicked.owner = self
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
            self.clicked.emit(value)

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

    def checkState(self):
        return self.Checked if self.isChecked() else self.Unchecked

    def setCheckState(self, state):
        if state not in (self.Unchecked, self.Checked):
            raise ValueError("native checkbox supports only Unchecked and Checked")
        self.setChecked(state == self.Checked)

    def toggle(self):
        self._require_ui()
        self.setChecked(not self.isChecked())

    def click(self):
        self._require_ui()
        if self._deleted or not self.isEnabled():
            return False
        self.toggle()
        self.clicked.emit(self._properties["value"])
        return True

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
    is a better behavioral fit for retained desktop controls because it preserves keyboard/mouse
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


class QRadioButton(QWidget):
    """One radio option with Qt-style checked/toggled semantics.

    Dear PyGui exposes radio controls as groups, so one wrapper owns a native
    one-item group. ``QButtonGroup`` coordinates exclusivity across multiple
    wrappers without introducing another renderer or hit target.
    """

    def __init__(self, text="", *, checked=False, parent=None, after=None, backend=None):
        backend, options = self._construction(parent, backend)
        self.toggled = Signal()
        self.clicked = Signal()
        self._text = str(text)
        self._checked = bool(checked)
        self._group = None
        self._focus_handlers = None
        default = self._text if self._checked else ""
        tag = backend.add_radio_button(
            [self._text],
            default_value=default,
            callback=self._changed,
            **options,
        )
        super().__init__(tag, parent=parent, after=after, backend=backend)
        self.toggled.owner = self
        self.clicked.owner = self
        self._properties.update(value=default, enabled=True)
        self._focus_handlers = _bind_focus_state_handlers(
            backend, self.tag, self._refresh_style)
        self._refresh_style()

    def text(self):
        return self._text

    def setText(self, text):
        text = str(text)
        if text == self._text:
            return
        was_checked = self._checked
        self._text = text
        try:
            self.backend.configure_item(self.tag, items=[text])
        except Exception:
            # Fake/minimal backends may not expose the item-list configuration.
            pass
        self._set_checked_now(was_checked, emit=False)

    def isChecked(self):
        return bool(self._checked)

    def setChecked(self, checked):
        checked = bool(checked)
        if checked and self._group is not None and self._group.exclusive():
            self._group._check(self)
        else:
            self._on_ui("checked", self._set_checked_now, checked, True)

    def _set_checked_now(self, checked, emit=True):
        checked = bool(checked)
        if self._checked == checked:
            return False
        self._checked = checked
        value = self._text if checked else ""
        try:
            self.backend.set_value(self.tag, value)
        except Exception:
            pass
        self._properties["value"] = value
        if emit:
            self.toggled.emit(checked)
        return True

    def click(self):
        self._require_ui()
        if self._deleted or not self.isEnabled():
            return False
        if self._group is not None and self._group.exclusive():
            self._group._check(self)
        else:
            self._set_checked_now(not self._checked)
        self.clicked.emit(self._checked)
        return True

    def _changed(self, sender, value, *_args):
        if self._deleted:
            return
        # A one-item Dear ImGui radio returns its label when activated.
        if self._group is not None and self._group.exclusive():
            self._group._check(self)
        else:
            self._set_checked_now(bool(value))
        self.clicked.emit(self._checked)

    def _refresh_style(self, *_args):
        enabled = bool(self._properties.get("enabled", True))
        focused = False
        try:
            state = self.backend.get_item_state(self.tag) or {}
            focused = bool(state.get("active", False) or state.get("focused", False))
        except Exception:
            pass
        bind_theme(self.backend, self.tag, radio_group_theme,
                   disabled=not enabled, focused=enabled and focused)

    def delete(self):
        group = self._group
        if group is not None:
            group.removeButton(self)
        handlers = self._focus_handlers
        super().delete()
        _delete_aux_item(self.backend, handlers)


class QButtonGroup(QObject):
    """Exclusive group for QRadioButton objects with stable integer ids."""

    def __init__(self, parent=None, *, after=None):
        super().__init__(parent=parent, after=after)
        self.buttonClicked = Signal(self)
        self.idClicked = Signal(self)
        self.buttonToggled = Signal(self)
        self.idToggled = Signal(self)
        self._buttons = []
        self._ids = {}
        self._exclusive = True
        self._button_connections = {}

    def setExclusive(self, exclusive):
        self._exclusive = bool(exclusive)

    def exclusive(self):
        return self._exclusive

    def addButton(self, button, button_id=-1):
        if not isinstance(button, QRadioButton):
            raise TypeError("QButtonGroup currently accepts QRadioButton instances")
        if button in self._buttons:
            if button_id != -1:
                self._ids[button] = int(button_id)
            return button
        if button._group is not None and button._group is not self:
            button._group.removeButton(button)
        if button_id == -1:
            used = set(self._ids.values())
            button_id = -2
            while button_id in used:
                button_id -= 1
        self._buttons.append(button)
        self._ids[button] = int(button_id)
        button._group = self
        self._button_connections[button] = (
            button.clicked.connect(lambda checked, b=button: self._clicked(b, checked), receiver=self),
            button.toggled.connect(lambda checked, b=button: self._toggled(b, checked), receiver=self),
        )
        if self._exclusive and button.isChecked():
            self._check(button)
        return button

    def removeButton(self, button):
        if button not in self._buttons:
            return False
        self._buttons.remove(button)
        self._ids.pop(button, None)
        for connection in self._button_connections.pop(button, ()):
            connection.disconnect()
        if button._group is self:
            button._group = None
        return True

    def buttons(self):
        return list(self._buttons)

    def button(self, button_id):
        button_id = int(button_id)
        return next((button for button in self._buttons
                     if self._ids.get(button) == button_id), None)

    def id(self, button):
        return self._ids.get(button, -1)

    def setId(self, button, button_id):
        if button not in self._buttons:
            raise ValueError("button is not in this group")
        self._ids[button] = int(button_id)

    def checkedButton(self):
        return next((button for button in self._buttons if button.isChecked()), None)

    def checkedId(self):
        button = self.checkedButton()
        return -1 if button is None else self.id(button)

    def _check(self, target):
        if target not in self._buttons:
            return target._set_checked_now(True)
        changed = False
        if self._exclusive:
            for button in self._buttons:
                if button is not target and button.isChecked():
                    changed = button._set_checked_now(False) or changed
        changed = target._set_checked_now(True) or changed
        return changed

    def _clicked(self, button, checked):
        self.buttonClicked.emit(button)
        self.idClicked.emit(self.id(button))

    def _toggled(self, button, checked):
        self.buttonToggled.emit(button, bool(checked))
        self.idToggled.emit(self.id(button), bool(checked))

    def delete(self):
        for button in tuple(self._buttons):
            self.removeButton(button)
        super().delete()


QCheckBox = ImGuiCheckBox
QRadioButtonGroup = ImGuiRadioButtonGroup
__all__ = [
    "ImGuiCheckBox", "ImGuiRadioButtonGroup", "QCheckBox",
    "QRadioButton", "QButtonGroup", "QRadioButtonGroup",
]
