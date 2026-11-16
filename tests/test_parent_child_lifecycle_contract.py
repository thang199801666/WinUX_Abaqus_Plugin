import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.widgets.widget import QWidget
from DearUIQt.core.application import QApplication
from DearUIQt.core.object import QPointer
from WinUx.ui.hosting.floating_dialog import FloatingDialogController


class ParentChildLifecycleContractTests(unittest.TestCase):
    def dialog_stub(self, *, visible=True):
        child = object.__new__(QtDialog)
        child._closed = False
        child._deleted = False
        child._owner_teardown_in_progress = False
        child._visible_for_test = bool(visible)
        child.hide_calls = 0

        def is_visible():
            return child._visible_for_test

        def hide():
            child.hide_calls += 1
            self.assertTrue(child._owner_teardown_in_progress)
            child._visible_for_test = False
            return True

        child.isVisible = is_visible
        child.hide = hide
        child.destroy = lambda: None
        return child

    def test_dialog_parent_hides_owned_child_before_itself(self):
        parent = object.__new__(QtDialog)
        child = self.dialog_stub()
        parent._owned_dialogs = [child]
        parent._children = []
        parent._widget_owner = object()
        children = list(QtDialog._iter_owned_top_levels(parent))
        self.assertEqual(children, [child])
        QtDialog._hide_owned_top_levels(parent)
        self.assertEqual(child.hide_calls, 1)
        self.assertFalse(child._owner_teardown_in_progress)
        self.assertFalse(child.isVisible())

    def test_hidden_child_is_not_reclosed(self):
        parent = object.__new__(QtDialog)
        child = self.dialog_stub(visible=False)
        parent._owned_dialogs = [child]
        parent._children = []
        parent._widget_owner = object()
        QtDialog._hide_owned_top_levels(parent)
        self.assertEqual(child.hide_calls, 0)

    def test_implicit_nested_dialog_adopts_active_visual_owner(self):
        parent = object.__new__(QtDialog)
        parent._owned_dialogs = []
        child = object.__new__(QtDialog)
        child._requested_parent = None
        child._transient_visual_owner = None
        child._modal_owner_candidate = lambda: parent
        owner = QtDialog._adopt_active_visual_owner(child)
        self.assertIs(owner, parent)
        self.assertIs(child._transient_visual_owner, parent)
        self.assertIn(child, parent._owned_dialogs)
        # Idempotent on repeated show leases.
        QtDialog._adopt_active_visual_owner(child)
        self.assertEqual(parent._owned_dialogs.count(child), 1)

    def test_explicit_parent_is_never_replaced_by_active_owner(self):
        explicit = object()
        active = object.__new__(QtDialog)
        active._owned_dialogs = []
        child = object.__new__(QtDialog)
        child._requested_parent = explicit
        child._transient_visual_owner = None
        child._modal_owner_candidate = lambda: active
        self.assertIsNone(QtDialog._adopt_active_visual_owner(child))
        self.assertNotIn(child, active._owned_dialogs)

    def test_qwidget_hide_propagates_to_qdialog_descendant_through_helper_qobject(self):
        owner = object.__new__(QWidget)
        child = self.dialog_stub()
        helper = SimpleNamespace(_children=[child])
        owner._children = [helper]
        QWidget._hide_owned_top_levels(owner)
        self.assertEqual(child.hide_calls, 1)


    def test_process_host_parent_hide_destroys_owned_children_without_focus_return(self):
        parent = object.__new__(FloatingDialogController)
        parent._closed = False
        parent._hwnd = 0
        parent._owner_acquired = False
        parent._owner_hwnd = 0
        parent._visible = True
        events = []
        parent._set_visible = lambda visible, return_focus=False: events.append(("visible", visible, return_focus))
        parent.post = lambda command, *args: events.append(("post", command)) or True
        class Child:
            _closed = False
            def destroy(self, **kwargs):
                events.append(("child-destroy", kwargs.get("return_focus")))
                self._closed = True
        child = Child()
        parent._owned_dialogs = [child]
        self.assertTrue(FloatingDialogController.hide(parent))
        self.assertEqual(events[0], ("child-destroy", False))
        self.assertEqual(parent._owned_dialogs, [])
        self.assertIn(("visible", False, False), events)

    def test_hidden_subtree_is_removed_from_popup_and_modal_stacks(self):
        app = object.__new__(QApplication)
        root = SimpleNamespace(parent=None, _deleted=False)
        child = SimpleNamespace(parent=root, _deleted=False)
        app._popup_stack = [QPointer.__new__(QPointer)]
        app._modal_stack = [QPointer.__new__(QPointer)]
        # QPointer internals are unnecessary here; use tiny pointer facades.
        class Pointer:
            def __init__(self, value): self.value = value
            def data(self): return self.value
        app._popup_stack = [Pointer(child)]
        app._modal_stack = [Pointer(child)]
        app._posted_lock = __import__('threading').Lock()
        app._posted = {}
        app._pointer_targets = []
        app._mouse_grabber = None
        app._hover_pointer_target = None
        app._focus_object = None
        app._focus_widget = None
        app._active_window = None
        app._set_hover_pointer_target = lambda *_: None
        app.mouseGrabberObject = lambda: None
        app.hoverPointerObject = lambda: None
        app.focusObject = lambda: None
        app.activeWindow = lambda: None
        QApplication._widget_hidden(app, root)
        self.assertEqual(app._popup_stack, [])
        self.assertEqual(app._modal_stack, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
