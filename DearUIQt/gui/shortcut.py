"""Qt-style key sequences and shortcut objects."""
from __future__ import annotations

from ..core.object import QObject, Qt, Signal


_KEY_NAMES = {
    "ESC": Qt.Key_Escape, "ESCAPE": Qt.Key_Escape,
    "TAB": Qt.Key_Tab, "BACKTAB": Qt.Key_Backtab,
    "BACKSPACE": Qt.Key_Backspace,
    "RETURN": Qt.Key_Return, "ENTER": Qt.Key_Enter,
    "INSERT": Qt.Key_Insert, "DELETE": Qt.Key_Delete,
    "HOME": Qt.Key_Home, "END": Qt.Key_End,
    "LEFT": Qt.Key_Left, "RIGHT": Qt.Key_Right,
    "UP": Qt.Key_Up, "DOWN": Qt.Key_Down,
    "PAGEUP": Qt.Key_PageUp, "PGUP": Qt.Key_PageUp,
    "PAGEDOWN": Qt.Key_PageDown, "PGDOWN": Qt.Key_PageDown,
    "SPACE": Qt.Key_Space,
}
for _index in range(1, 13):
    _KEY_NAMES["F{}".format(_index)] = getattr(Qt, "Key_F{}".format(_index))
for _letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    _KEY_NAMES[_letter] = getattr(Qt, "Key_{}".format(_letter))

_MOD_NAMES = {
    "CTRL": Qt.ControlModifier, "CONTROL": Qt.ControlModifier,
    "SHIFT": Qt.ShiftModifier,
    "ALT": Qt.AltModifier,
    "META": Qt.MetaModifier, "WIN": Qt.MetaModifier, "CMD": Qt.MetaModifier,
}


class QKeySequence:
    """Single-chord Qt-compatible key sequence.

    DearUIQt intentionally starts with one chord because all existing WinUx
    shortcuts are single-step. The representation is backend-neutral and can be
    extended to multi-chord sequences without changing QShortcut/QAction APIs.
    """
    NoMatch = 0
    PartialMatch = 1
    ExactMatch = 2

    def __init__(self, sequence=""):
        if isinstance(sequence, QKeySequence):
            self._key = sequence._key
            self._modifiers = sequence._modifiers
            return
        if isinstance(sequence, tuple) and len(sequence) == 2:
            self._key = int(sequence[0])
            self._modifiers = int(sequence[1])
            return
        self._key, self._modifiers = self._parse(str(sequence or ""))

    @staticmethod
    def _parse(text):
        text = text.strip()
        if not text:
            return 0, Qt.NoModifier
        parts = [part.strip() for part in text.replace("-", "+").split("+") if part.strip()]
        modifiers = Qt.NoModifier
        key = 0
        for part in parts:
            upper = part.upper().replace(" ", "")
            modifier = _MOD_NAMES.get(upper)
            if modifier is not None:
                modifiers |= modifier
                continue
            candidate = _KEY_NAMES.get(upper)
            if candidate is None and len(part) == 1:
                candidate = ord(part.upper())
            if candidate is None:
                raise ValueError("unknown key sequence component: {!r}".format(part))
            if key:
                raise ValueError("DearUIQt QKeySequence currently supports one key chord")
            key = candidate
        if not key:
            raise ValueError("key sequence requires a key")
        return key, modifiers

    def isEmpty(self):
        return self._key == 0

    def key(self):
        return self._key

    def modifiers(self):
        return self._modifiers

    def matches(self, other):
        other = QKeySequence(other)
        return self.ExactMatch if self == other else self.NoMatch

    def toString(self):
        if self.isEmpty():
            return ""
        parts = []
        if self._modifiers & Qt.ControlModifier:
            parts.append("Ctrl")
        if self._modifiers & Qt.AltModifier:
            parts.append("Alt")
        if self._modifiers & Qt.ShiftModifier:
            parts.append("Shift")
        if self._modifiers & Qt.MetaModifier:
            parts.append("Meta")
        name = next((name for name, value in _KEY_NAMES.items()
                     if value == self._key and name not in ("ESC", "PGUP", "PGDOWN")), None)
        if name is None and 32 <= self._key <= 126:
            name = chr(self._key).upper()
        parts.append(name or str(self._key))
        return "+".join(parts)

    def __bool__(self):
        return not self.isEmpty()

    def __eq__(self, other):
        try:
            other = QKeySequence(other)
        except Exception:
            return False
        return (self._key, self._modifiers) == (other._key, other._modifiers)

    def __hash__(self):
        return hash((self._key, self._modifiers))

    def __repr__(self):
        return "QKeySequence({!r})".format(self.toString())


class QShortcut(QObject):
    """Application-registered Qt-style shortcut."""
    def __init__(self, key, parent=None, member=None, ambiguousMember=None, context=Qt.WindowShortcut):
        super().__init__(parent=parent)
        self.activated = Signal(self)
        self.activatedAmbiguously = Signal(self)
        self._key = QKeySequence(key)
        self._enabled = True
        self._context = int(context)
        self._auto_repeat = True
        if callable(member):
            self.activated.connect(member)
        if callable(ambiguousMember):
            self.activatedAmbiguously.connect(ambiguousMember)
        self._register()

    def _register(self):
        from ..core.application import QApplication
        application = QApplication.instance()
        if application is not None:
            application.registerShortcut(self)

    def key(self):
        return QKeySequence(self._key)

    def setKey(self, key):
        self._key = QKeySequence(key)

    def isEnabled(self):
        return self._enabled and not self._deleted

    def setEnabled(self, enabled):
        self._enabled = bool(enabled)

    def context(self):
        return self._context

    def setContext(self, context):
        self._context = int(context)

    def autoRepeat(self):
        return self._auto_repeat

    def setAutoRepeat(self, enabled):
        self._auto_repeat = bool(enabled)

    def delete(self):
        from ..core.application import QApplication
        application = QApplication.instance()
        if application is not None:
            application.unregisterShortcut(self)
        super().delete()
