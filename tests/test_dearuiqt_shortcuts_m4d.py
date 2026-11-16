import unittest

from DearUIQt.core import QObject, QEvent, QKeyEvent, Qt
from DearUIQt.widgets import QApplication, QWidget
from DearUIQt.gui import QAction, QKeySequence, QShortcut


class _Backend:
    def does_item_exist(self, _tag): return True
    def configure_item(self, *_args, **_kwargs): return None
    def delete_item(self, _tag): return None
    def get_item_configuration(self, _tag): return {"enabled": True, "show": True}

class _Node(QObject):
    def __init__(self, parent=None, *, window=None):
        super().__init__(parent=parent)
        self._window = window or self
        self.override = False
        self.keys = []

    def window(self):
        return self._window

    def event(self, event):
        if event.type() == QEvent.ShortcutOverride:
            if self.override:
                event.accept()
            else:
                event.ignore()
            return event.isAccepted()
        if event.type() == QEvent.KeyPress:
            self.keys.append((event.key(), event.modifiers()))
            event.ignore()
            return False
        return super().event(event)


class ShortcutContractTests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication()

    def tearDown(self):
        self.app.delete()

    def keypress(self, receiver, key, modifiers=Qt.NoModifier, auto_repeat=False):
        return self.app.sendEvent(receiver, QKeyEvent(
            QEvent.KeyPress, key, modifiers, auto_repeat=auto_repeat))

    def test_key_sequence_parse_and_roundtrip(self):
        seq = QKeySequence("Ctrl+Shift+S")
        self.assertEqual(seq.key(), Qt.Key_S)
        self.assertEqual(seq.modifiers(), Qt.ControlModifier | Qt.ShiftModifier)
        self.assertEqual(QKeySequence(seq), seq)
        self.assertEqual(seq.matches("Ctrl+Shift+S"), QKeySequence.ExactMatch)

    def test_application_shortcut_triggers(self):
        target = _Node()
        fired = []
        shortcut = QShortcut("Ctrl+R", target, lambda: fired.append("r"),
                             context=Qt.ApplicationShortcut)
        self.app.setFocusObject(target)
        self.assertTrue(self.keypress(target, Qt.Key_R, Qt.ControlModifier))
        self.assertEqual(fired, ["r"])
        shortcut.delete()

    def test_shortcut_override_keeps_key_with_editor(self):
        target = _Node()
        target.override = True
        fired = []
        QShortcut("Ctrl+C", target, lambda: fired.append("copy"),
                  context=Qt.ApplicationShortcut)
        self.app.setFocusObject(target)
        self.keypress(target, Qt.Key_C, Qt.ControlModifier)
        self.assertEqual(fired, [])
        self.assertEqual(target.keys[-1], (Qt.Key_C, Qt.ControlModifier))

    def test_window_context_and_ambiguity(self):
        window = _Node()
        child = _Node(parent=window, window=window)
        other_window = _Node()
        fired = []
        ambiguous = []
        a = QShortcut("F5", window, lambda: fired.append("a"), context=Qt.WindowShortcut)
        b = QShortcut("F5", window, lambda: fired.append("b"), context=Qt.WindowShortcut)
        a.activatedAmbiguously.connect(lambda: ambiguous.append("a"))
        self.app.setFocusObject(child)
        self.keypress(child, Qt.Key_F5)
        self.assertEqual(fired, [])
        self.assertEqual(ambiguous, ["a"])
        self.app.setFocusObject(other_window)
        self.keypress(other_window, Qt.Key_F5)
        self.assertEqual(fired, [])

    def test_action_shortcut_metadata(self):
        action = QAction("Refresh")
        action.setShortcut("Ctrl+R")
        self.assertEqual(action.shortcut(), QKeySequence("Ctrl+R"))
        action.setShortcuts(["Ctrl+R", "F5"])
        self.assertEqual([s.toString() for s in action.shortcuts()], ["Ctrl+R", "F5"])
        action.setShortcutContext(Qt.ApplicationShortcut)
        self.assertEqual(action.shortcutContext(), Qt.ApplicationShortcut)


    def test_widget_action_shortcut_tracks_action_changes(self):
        widget = QWidget(101, backend=_Backend())
        action = QAction("Refresh")
        action.setShortcut("F5")
        action.setShortcutContext(Qt.WindowShortcut)
        widget.addAction(action)
        fired = []
        action.triggered.connect(lambda *_args: fired.append("hit"))
        self.app.setFocusObject(widget)
        self.keypress(widget, Qt.Key_F5)
        self.assertEqual(fired, ["hit"])
        action.setShortcut("Ctrl+R")
        self.keypress(widget, Qt.Key_F5)
        self.assertEqual(fired, ["hit"])
        self.keypress(widget, Qt.Key_R, Qt.ControlModifier)
        self.assertEqual(fired, ["hit", "hit"])
        widget.removeAction(action)
        self.keypress(widget, Qt.Key_R, Qt.ControlModifier)
        self.assertEqual(fired, ["hit", "hit"])
        widget.delete()

    def test_same_qaction_on_multiple_widgets_is_not_ambiguous(self):
        window = QWidget(201, backend=_Backend())
        left = QWidget(202, parent=window, backend=window.backend)
        right = QWidget(203, parent=window, backend=window.backend)
        action = QAction("Shared")
        action.setShortcut("F5")
        action.setShortcutContext(Qt.WindowShortcut)
        left.addAction(action)
        right.addAction(action)
        fired = []
        action.triggered.connect(lambda *_args: fired.append("hit"))
        self.app.setFocusObject(left)
        self.keypress(left, Qt.Key_F5)
        self.assertEqual(fired, ["hit"])
        window.delete()

    def test_auto_repeat_can_be_disabled(self):
        target = _Node()
        fired = []
        shortcut = QShortcut("F5", target, lambda: fired.append(1),
                             context=Qt.ApplicationShortcut)
        shortcut.setAutoRepeat(False)
        self.app.setFocusObject(target)
        self.keypress(target, Qt.Key_F5, auto_repeat=True)
        self.assertEqual(fired, [])
        self.keypress(target, Qt.Key_F5)
        self.assertEqual(fired, [1])


if __name__ == '__main__':
    unittest.main()
