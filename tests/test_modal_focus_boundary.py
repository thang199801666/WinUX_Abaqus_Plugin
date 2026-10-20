"""Deferred widget focus cannot activate a disabled modal owner."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from DearUIQt.core import QObject
from DearUIQt.core.application import QApplication
from DearUIQt.widgets.widget import QWidget


class ModalFocusTests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication()
        self.addCleanup(self.app.delete)
        self.modal = QObject()
        self.modal.tag = 10
        self.modal._item_belongs_to = lambda tag, root: tag in (10, 11)
        self.background = QObject()
        self.app._register_modal(self.modal)
        self.app._set_focus_widget(self.modal)

    def test_background_widget_cannot_replace_modal_focus(self):
        self.assertFalse(self.app.canFocusWidget(self.background))
        self.assertFalse(self.app._set_focus_widget(self.background))
        self.assertIs(self.app.focusWidget(), self.modal)

    def test_logical_descendant_and_native_parent_tag_are_both_allowed(self):
        logical_child = QObject(parent=self.modal)
        raw_parent_child = QObject()
        raw_parent_child.tag = 11
        self.assertTrue(self.app.canFocusWidget(logical_child))
        self.assertTrue(self.app.canFocusWidget(raw_parent_child))

    def test_nested_modal_blocks_parent_focus_until_child_closes(self):
        child = QObject(parent=self.modal)
        self.app._register_modal(child)
        self.assertFalse(self.app.canFocusWidget(self.modal))
        self.assertTrue(self.app.canFocusWidget(child))
        self.app._unregister_modal(child)
        self.assertTrue(self.app.canFocusWidget(self.modal))

    def test_popup_has_priority_over_its_modal_owner(self):
        popup = QObject(parent=self.modal)
        self.app._register_popup(popup)
        self.assertFalse(self.app.canFocusWidget(self.modal))
        self.assertTrue(self.app.canFocusWidget(popup))

    def test_no_modal_means_ordinary_programmatic_focus_is_allowed(self):
        self.app._unregister_modal(self.modal)
        self.assertTrue(self.app.canFocusWidget(self.background))

    def test_qwidget_rejects_before_flushing_or_queuing_native_focus(self):
        backend = SimpleNamespace(focus_item=Mock())
        widget = QWidget(20, backend=backend)
        self.assertFalse(widget.setFocus())
        backend.focus_item.assert_not_called()
        self.assertIs(self.app.focusWidget(), self.modal)
