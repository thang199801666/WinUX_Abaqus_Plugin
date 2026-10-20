"""Backend-independent shared commands with a small QAction-like contract."""
import itertools
import threading

from ..core.object import QObject, Signal

_keys = itertools.count(1)


class QAction(QObject):
    def __init__(self, text="", parent=None, *, after=None, checkable=False, checked=False):
        super().__init__(parent, after=after)
        self.changed = Signal(self)
        self.toggled = Signal(self)
        self.triggered = Signal(self)
        self._action_key = "qaction.{}".format(next(_keys))
        self._text = str(text)
        self._enabled = True
        self._visible = True
        self._checkable = bool(checkable)
        self._checked = bool(checked) and self._checkable
        self._tooltip = ""
        self._icon = None
        self._data = None
        self._action_group = None

    def _require_thread(self):
        if threading.get_ident() != self.threadId():
            raise RuntimeError("action operations require the owning thread")

    def _set(self, name, value):
        self._require_thread()
        if self._deleted:
            raise RuntimeError("cannot configure a deleted action")
        if getattr(self, name) != value:
            setattr(self, name, value)
            self.changed.emit()

    def text(self):
        return self._text

    def setText(self, text):
        self._set("_text", str(text))

    def isEnabled(self):
        return (self._enabled and not self._deleted and
                (self._action_group is None or self._action_group.isEnabled()))

    def setEnabled(self, enabled):
        self._set("_enabled", bool(enabled))

    def setDisabled(self, disabled):
        self.setEnabled(not disabled)

    def isVisible(self):
        return (self._visible and not self._deleted and
                (self._action_group is None or self._action_group.isVisible()))

    def setVisible(self, visible):
        self._set("_visible", bool(visible))

    def isCheckable(self):
        return self._checkable

    def setCheckable(self, checkable):
        self._require_thread()
        if self._deleted:
            raise RuntimeError("cannot configure a deleted action")
        checkable = bool(checkable)
        if checkable == self._checkable:
            return
        was_checked = self._checked
        self._checkable = checkable
        if not checkable:
            self._checked = False
        self.changed.emit()
        if was_checked != self._checked:
            self.toggled.emit(self._checked)

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        self._require_thread()
        if self._deleted:
            raise RuntimeError("cannot configure a deleted action")
        checked = bool(checked) and self._checkable
        if self._action_group is not None and self._action_group.isExclusive() and checked:
            self._action_group._check_action(self)
            return
        if checked != self._checked:
            self._checked = checked
            self.changed.emit()
            self.toggled.emit(checked)

    def toggle(self):
        self.setChecked(not self._checked)

    def toolTip(self):
        return self._tooltip

    def setToolTip(self, text):
        self._set("_tooltip", str(text))

    def icon(self):
        return self._icon

    def setIcon(self, icon):
        self._require_thread()
        if self._deleted:
            raise RuntimeError("cannot configure a deleted action")
        if self._icon is not icon:
            self._icon = icon
            self.changed.emit()

    def data(self):
        return self._data

    def setData(self, data):
        self._require_thread()
        if self._deleted:
            raise RuntimeError("cannot configure a deleted action")
        if self._data is not data:
            self._data = data
            self.changed.emit()

    def trigger(self):
        self._require_thread()
        if not self.isEnabled():
            return False
        if self._checkable and not (self._checked and self._action_group is not None
                                    and self._action_group.isExclusive()):
            self.toggle()
        self.triggered.emit(self._checked)
        return True

    def actionGroup(self):
        return self._action_group

    def setActionGroup(self, group):
        self._require_thread()
        if self._deleted:
            raise RuntimeError("cannot configure a deleted action")
        if group is None:
            if self._action_group is not None:
                self._action_group.removeAction(self)
        elif isinstance(group, QActionGroup):
            group.addAction(self)
        else:
            raise TypeError("action group must be QActionGroup or None")

    def delete(self):
        self._require_thread()
        super().delete()


class QActionGroup(QObject):
    """Shared exclusive selection; membership does not reparent existing actions."""
    def __init__(self, parent=None, *, after=None, exclusive=True):
        super().__init__(parent, after=after)
        self.triggered = Signal(self)
        self._actions = []
        self._bindings = {}
        self._exclusive = bool(exclusive)
        self._enabled = True
        self._visible = True

    def _require_live(self):
        if threading.get_ident() != self.threadId():
            raise RuntimeError("action group operations require the owning thread")
        if self._deleted:
            raise RuntimeError("cannot configure a deleted action group")

    def actions(self):
        return [action for action in self._actions if not action._deleted]

    def checkedAction(self):
        return next((action for action in self._actions if not action._deleted and action.isChecked()), None)

    def isExclusive(self):
        return self._exclusive

    def setExclusive(self, exclusive):
        self._require_live()
        self._exclusive = bool(exclusive)
        checked = self.checkedAction()
        if self._exclusive and checked is not None:
            self._check_action(checked)

    def isEnabled(self):
        return self._enabled and not self._deleted

    def isVisible(self):
        return self._visible and not self._deleted

    def _set_state(self, name, value):
        self._require_live()
        if getattr(self, name) == bool(value):
            return
        states = {action: (action.isEnabled(), action.isVisible()) for action in self._actions}
        setattr(self, name, bool(value))
        for action, previous in states.items():
            if (not action._deleted and action.actionGroup() is self and
                    previous != (action.isEnabled(), action.isVisible())):
                action.changed.emit()

    def setEnabled(self, enabled):
        self._set_state("_enabled", enabled)

    def setDisabled(self, disabled):
        self.setEnabled(not disabled)

    def setVisible(self, visible):
        self._set_state("_visible", visible)

    def addAction(self, action):
        self._require_live()
        if isinstance(action, str):
            action = QAction(action, self)
        if not isinstance(action, QAction):
            raise TypeError("group action must be QAction or text")
        if action._deleted or action.threadId() != self.threadId():
            raise RuntimeError("group actions must be live and belong to the same thread")
        if action.actionGroup() is self:
            return action
        previous = (action.isEnabled(), action.isVisible())
        if action.actionGroup() is not None:
            action.actionGroup()._detach(action, notify=False)
        self._actions.append(action)
        action._action_group = self
        self._bindings[action] = [
            action.destroyed.connect(self._action_destroyed),
            action.triggered.connect(lambda checked, member=action: self._triggered(member), receiver=self),
        ]
        if self._exclusive and action.isChecked():
            self._check_action(action)
        if (not action._deleted and action.actionGroup() is self and
                previous != (action.isEnabled(), action.isVisible())):
            action.changed.emit()
        return action

    def removeAction(self, action):
        self._require_live()
        self._detach(action)

    def _detach(self, action, notify=True):
        if action not in self._actions:
            return
        previous = (action.isEnabled(), action.isVisible())
        self._actions.remove(action)
        action._action_group = None
        for binding in self._bindings.pop(action):
            binding.disconnect()
        if notify and previous != (action.isEnabled(), action.isVisible()):
            action.changed.emit()

    def _action_destroyed(self, action):
        self.removeAction(action)

    def _triggered(self, action):
        if action in self._actions and not action._deleted:
            self.triggered.emit(action)

    def _check_action(self, action):
        self._require_live()
        changes = []
        # Commit the entire selection before notifications: observers must not
        # see two checked members, even when reacting from a changed slot.
        for member in self._actions:
            checked = member is action
            if member._checked != checked:
                member._checked = checked
                changes.append((member, checked))
        for member, checked in changes:
            if not member._deleted and member.actionGroup() is self and member._checked == checked:
                member.changed.emit()
                member.toggled.emit(checked)

    def delete(self):
        if self._deleted:
            return
        self._require_live()
        states = [(action, action.isEnabled(), action.isVisible()) for action in self._actions]
        for action in self._actions:
            action._action_group = None
            for binding in self._bindings[action]:
                binding.disconnect()
        self._actions.clear()
        self._bindings.clear()
        try:
            super().delete()
        finally:
            for action, enabled, visible in states:
                if not action._deleted and (enabled, visible) != (action.isEnabled(), action.isVisible()):
                    action.changed.emit()


__all__ = ["QAction", "QActionGroup"]
