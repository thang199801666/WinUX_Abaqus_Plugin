import unittest
from pathlib import Path

from DearUIQt.core.object import QObject, Signal, Qt, QEvent
from DearUIQt.gui.events import QKeyEvent
from DearUIQt.modelview.delegates import (
    QAbstractItemDelegate,
    QItemEditorLifecycle,
)


class _Editor(QObject):
    def __init__(self, value="draft"):
        super().__init__()
        self.value = value
        self.editingFinished = Signal(self)
        self.escapePressed = Signal(self)
        self.navigationRequested = Signal(self)


class _Model:
    def __init__(self, value="old"):
        self.value = value
        self.commits = 0


class _Delegate(QAbstractItemDelegate):
    def __init__(self):
        super().__init__()
        self.restores = 0

    def setEditorData(self, editor, index):
        editor.value = index[0].value
        self.restores += 1
        return editor.value

    def setModelData(self, editor, model, index):
        del index
        model.value = editor.value
        model.commits += 1
        return True


class EditorDelegateLifecycleTests(unittest.TestCase):
    def test_release_version(self):
        import DearUIQt
        self.assertGreaterEqual(tuple(map(int, DearUIQt.__version__.split("."))), (1, 110, 0))

    def _session(self, value="draft"):
        delegate = _Delegate()
        model = _Model()
        editor = _Editor(value)
        closes = []
        navigation = []
        session = QItemEditorLifecycle(
            delegate, editor, model, (model, 0),
            close_callback=lambda e, i, h: closes.append(h),
            navigate_callback=lambda d, i: navigation.append(d),
        )
        return session, delegate, model, editor, closes, navigation

    def test_enter_commits_and_closes(self):
        session, _delegate, model, editor, closes, _navigation = self._session("new")
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_Return)
        self.assertTrue(session.eventFilter(editor, event))
        self.assertEqual(model.value, "new")
        self.assertEqual(model.commits, 1)
        self.assertEqual(closes, [QAbstractItemDelegate.NoHint])
        self.assertFalse(session.isActive())

    def test_escape_reverts_editor_without_model_commit(self):
        session, delegate, model, editor, closes, _navigation = self._session("new")
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape)
        self.assertTrue(session.eventFilter(editor, event))
        self.assertEqual(model.value, "old")
        self.assertEqual(model.commits, 0)
        self.assertEqual(editor.value, "old")
        self.assertEqual(delegate.restores, 1)
        self.assertEqual(closes, [QAbstractItemDelegate.RevertModelCache])

    def test_tab_and_backtab_commit_then_request_navigation(self):
        session, _delegate, model, editor, closes, navigation = self._session("next")
        session.eventFilter(editor, QKeyEvent(QEvent.KeyPress, Qt.Key_Tab))
        self.assertEqual(model.value, "next")
        self.assertEqual(closes[-1], QAbstractItemDelegate.EditNextItem)
        self.assertEqual(navigation, [1])

        session, _delegate, model, editor, closes, navigation = self._session("prev")
        session.eventFilter(editor, QKeyEvent(QEvent.KeyPress, Qt.Key_Backtab))
        self.assertEqual(closes[-1], QAbstractItemDelegate.EditPreviousItem)
        self.assertEqual(navigation, [-1])

    def test_native_editor_signals_use_same_lifecycle(self):
        session, _delegate, model, editor, closes, navigation = self._session("native")
        editor.navigationRequested.emit(1)
        self.assertEqual(model.value, "native")
        self.assertEqual(closes, [QAbstractItemDelegate.EditNextItem])
        self.assertEqual(navigation, [1])

        session, _delegate, model, editor, closes, navigation = self._session("cancel")
        editor.escapePressed.emit()
        self.assertEqual(model.value, "old")
        self.assertEqual(closes, [QAbstractItemDelegate.RevertModelCache])

    def test_item_views_route_transient_editors_through_lifecycle(self):
        root = Path(__file__).resolve().parents[1]
        table = (root / "DearUIQt/modelview/table.py").read_text(encoding="utf-8")
        tree = (root / "DearUIQt/modelview/tree.py").read_text(encoding="utf-8")
        base = (root / "DearUIQt/modelview/base.py").read_text(encoding="utf-8")
        self.assertIn("_start_editor_lifecycle(editor, index", table)
        self.assertIn("QItemEditorLifecycle(", tree)
        self.assertIn("_navigate_after_editor", base)


if __name__ == "__main__":
    unittest.main()
