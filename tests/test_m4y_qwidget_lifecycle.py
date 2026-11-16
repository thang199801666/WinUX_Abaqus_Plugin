from collections import deque
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from DearUIQt.QtCore import QPointer, Qt
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.widgets import QWidget
from test_dearuiqt_layout_cache import Backend


class Scheduler:
    def __init__(self):
        self.callbacks = deque()

    def after(self, _delay, callback, *args):
        self.callbacks.append((callback, args))

    def drain(self):
        while self.callbacks:
            callback, args = self.callbacks.popleft()
            callback(*args)


class RejectCloseWidget(QWidget):
    def closeEvent(self, event):
        event.ignore()


class LifecycleM4yTests(unittest.TestCase):
    def test_m4y_version(self):
        import re
        source = (ROOT / "DearUIQt" / "__init__.py").read_text(encoding="utf-8")
        match = re.search(r'__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)"', source)
        self.assertIsNotNone(match)
        self.assertGreaterEqual(tuple(map(int, match.groups())), (1, 81, 0))

    def test_delete_on_close_is_deferred_and_qpointer_dies_on_event_turn(self):
        scheduler = Scheduler()
        backend = Backend()
        widget = QWidget(backend.add_group(), backend=backend, after=scheduler.after)
        guard = QPointer(widget)
        widget.setAttribute(Qt.WA_DeleteOnClose, True)

        self.assertTrue(widget.close())
        self.assertTrue(widget.isHidden())
        self.assertFalse(guard.isNull())
        self.assertTrue(widget._delete_later_pending)

        scheduler.drain()
        self.assertTrue(guard.isNull())
        self.assertFalse(backend.does_item_exist(widget.tag))

    def test_rejected_close_keeps_widget_visible_and_alive(self):
        scheduler = Scheduler()
        backend = Backend()
        widget = RejectCloseWidget(backend.add_group(), backend=backend, after=scheduler.after)
        guard = QPointer(widget)
        try:
            self.assertFalse(widget.close())
            self.assertTrue(widget.isVisible())
            self.assertFalse(guard.isNull())
            self.assertFalse(widget._delete_later_pending)
        finally:
            widget.delete()

    def test_qwidget_direct_delete_hides_owned_dialog_before_child_delete(self):
        scheduler = Scheduler()
        backend = Backend()
        owner = QWidget(backend.add_group(), backend=backend, after=scheduler.after)
        child = object.__new__(QtDialog)
        child._deleted = False
        child._closed = False
        child._owner_teardown_in_progress = False
        child._visible_for_test = True
        order = []

        def is_visible():
            return child._visible_for_test

        def hide():
            order.append(("hide", child._owner_teardown_in_progress))
            child._visible_for_test = False
            return True

        def delete():
            order.append(("delete", child._owner_teardown_in_progress))
            child._deleted = True

        child.isVisible = is_visible
        child.hide = hide
        child.delete = delete
        child.parent = owner
        child._children = []
        owner._children.append(child)

        owner.delete()
        self.assertEqual(order[0], ("hide", True))
        self.assertEqual(order[1][0], "delete")
        self.assertFalse(child._visible_for_test)

    def test_dialog_terminal_cascade_suppresses_child_focus_restore(self):
        owner = object.__new__(QtDialog)
        child = object.__new__(QtDialog)
        child._closed = False
        child._owner_teardown_in_progress = False
        observed = []

        def destroy():
            observed.append(child._owner_teardown_in_progress)
            child._closed = True

        child.destroy = destroy
        owner._owned_dialogs = [child]
        QtDialog._destroy_owned_top_levels(owner)

        self.assertEqual(observed, [True])
        self.assertEqual(owner._owned_dialogs, [])
        self.assertFalse(child._owner_teardown_in_progress)


if __name__ == "__main__":
    unittest.main(verbosity=2)
