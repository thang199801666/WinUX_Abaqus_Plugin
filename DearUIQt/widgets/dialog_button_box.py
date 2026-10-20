"""Reusable QDialogButtonBox-like action cluster."""
from __future__ import annotations

from ..core.object import Qt, Signal
from .widget import QWidget
from .buttons import QPushButton


class QDialogButtonBox(QWidget):
    # Standard button flags (stable bit values; combinations are supported).
    NoButton = 0x00000000
    Ok = 0x00000400
    Save = 0x00000800
    SaveAll = 0x00001000
    Open = 0x00002000
    Yes = 0x00004000
    YesToAll = 0x00008000
    No = 0x00010000
    NoToAll = 0x00020000
    Abort = 0x00040000
    Retry = 0x00080000
    Ignore = 0x00100000
    Close = 0x00200000
    Cancel = 0x00400000
    Discard = 0x00800000
    Help = 0x01000000
    Apply = 0x02000000
    Reset = 0x04000000
    RestoreDefaults = 0x08000000

    InvalidRole = -1
    AcceptRole = 0
    RejectRole = 1
    DestructiveRole = 2
    ActionRole = 3
    HelpRole = 4
    YesRole = 5
    NoRole = 6
    ResetRole = 7
    ApplyRole = 8

    _STANDARD = {
        Ok: ("OK", AcceptRole, "primary", True),
        Save: ("Save", AcceptRole, "primary", True),
        SaveAll: ("Save All", AcceptRole, "primary", True),
        Open: ("Open", AcceptRole, "primary", True),
        Yes: ("Yes", YesRole, "primary", True),
        YesToAll: ("Yes to All", YesRole, "primary", False),
        No: ("No", NoRole, "secondary", False),
        NoToAll: ("No to All", NoRole, "secondary", False),
        Abort: ("Abort", RejectRole, "danger", False),
        Retry: ("Retry", AcceptRole, "primary", True),
        Ignore: ("Ignore", ActionRole, "secondary", False),
        Close: ("Close", RejectRole, "secondary", False),
        Cancel: ("Cancel", RejectRole, "secondary", False),
        Discard: ("Discard", DestructiveRole, "danger", False),
        Help: ("Help", HelpRole, "secondary", False),
        Apply: ("Apply", ApplyRole, "secondary", False),
        Reset: ("Reset", ResetRole, "secondary", False),
        RestoreDefaults: ("Restore Defaults", ResetRole, "secondary", False),
    }

    def __init__(self, buttons=NoButton, orientation=Qt.Horizontal, *, parent=None,
                 after=None, backend=None, spacing=7):
        orientation = int(orientation)
        if orientation not in (Qt.Horizontal, Qt.Vertical):
            raise ValueError("orientation must be Qt.Horizontal or Qt.Vertical")
        backend, options = self._construction(parent, backend)
        self.clicked = Signal()
        self.accepted = Signal()
        self.rejected = Signal()
        self.helpRequested = Signal()
        tag = backend.add_group(
            horizontal=orientation == Qt.Horizontal,
            horizontal_spacing=max(0, int(spacing)),
            **options,
        )
        super().__init__(tag, parent=parent, after=after, backend=backend)
        for signal in (self.clicked, self.accepted, self.rejected, self.helpRequested):
            signal.owner = self
        self._orientation = orientation
        self._standard_buttons = int(buttons or 0)
        self._buttons = []
        self._roles = {}
        self._standard_by_button = {}
        self._button_by_standard = {}
        self.setStandardButtons(self._standard_buttons)

    def orientation(self):
        return self._orientation

    def standardButtons(self):
        return self._standard_buttons

    def setStandardButtons(self, buttons):
        self._require_ui()
        buttons = int(buttons or 0)
        for button in tuple(self._buttons):
            if button in self._standard_by_button:
                self.removeButton(button)
        self._standard_buttons = buttons
        for flag, (text, role, style_role, default) in self._STANDARD.items():
            if buttons & flag:
                button = QPushButton(
                    text,
                    parent=self,
                    after=self._after,
                    backend=self.backend,
                    role=style_role,
                    default=default,
                )
                self._register_button(button, role, flag)
        return self

    def _register_button(self, button, role, standard=NoButton):
        if not isinstance(button, QPushButton):
            raise TypeError("button box requires QPushButton instances")
        if button.backend is not self.backend:
            raise ValueError("button and button box must use the same backend")
        if button.parent is not self:
            self.backend.move_item(button._layout_tag(), parent=self.tag)
            button.setParent(self)
        role = int(role)
        self._buttons.append(button)
        self._roles[button] = role
        if standard:
            self._standard_by_button[button] = standard
            self._button_by_standard[standard] = button
        button.clicked.connect(lambda _button=button: self._button_clicked(_button), receiver=self)
        return button

    def addButton(self, button_or_text, role=None):
        if isinstance(button_or_text, str):
            if role is None:
                raise TypeError("a custom text button requires a button role")
            button = QPushButton(
                button_or_text, parent=self, after=self._after, backend=self.backend)
            return self._register_button(button, role)
        if role is None:
            raise TypeError("a custom button requires a button role")
        return self._register_button(button_or_text, role)

    def removeButton(self, button):
        if button not in self._buttons:
            return False
        self._buttons.remove(button)
        self._roles.pop(button, None)
        standard = self._standard_by_button.pop(button, self.NoButton)
        if standard:
            self._button_by_standard.pop(standard, None)
            self._standard_buttons &= ~standard
        button.delete()
        return True

    def clear(self):
        for button in tuple(self._buttons):
            self.removeButton(button)
        self._standard_buttons = self.NoButton

    def buttons(self):
        return list(self._buttons)

    def button(self, standard_button):
        return self._button_by_standard.get(int(standard_button))

    def standardButton(self, button):
        return self._standard_by_button.get(button, self.NoButton)

    def buttonRole(self, button):
        return self._roles.get(button, self.InvalidRole)

    def _button_clicked(self, button):
        role = self.buttonRole(button)
        self.clicked.emit(button)
        if role in (self.AcceptRole, self.YesRole):
            self.accepted.emit()
        elif role in (self.RejectRole, self.NoRole):
            self.rejected.emit()
        elif role == self.HelpRole:
            self.helpRequested.emit()


__all__ = ["QDialogButtonBox"]
