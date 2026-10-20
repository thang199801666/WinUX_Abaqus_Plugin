import itertools
import threading
import unittest
from unittest.mock import Mock

from WinUx.ui import QPushButton, QCheckBox, QLineEdit, QTabWidget, QSignalBlocker


def backend_fixture():
    backend = Mock()
    tags = itertools.count(1)
    values, configs = {}, {}

    def create(*args, **kwargs):
        tag = next(tags)
        configs[tag] = dict(kwargs, enabled=True, multiline=False)
        values[tag] = kwargs.get('default_value', '')
        return tag

    for name in ('add_button', 'add_checkbox', 'add_input_text', 'add_tab', 'add_tab_bar'):
        getattr(backend, name).side_effect = create
    backend.get_value.side_effect = lambda tag: values[tag]
    backend.set_value.side_effect = lambda tag, value: values.__setitem__(tag, value)
    backend.get_item_configuration.side_effect = lambda tag: configs[tag]
    backend.configure_item.side_effect = lambda tag, **kwargs: configs[tag].update(kwargs)
    backend.get_item_state.return_value = {'active': True}
    backend.does_item_exist.return_value = True
    return backend


class QtControlInteractionTests(unittest.TestCase):
    def test_checkable_button_toggles_before_clicked_and_ignores_disabled_clicks(self):
        backend = backend_fixture()
        button = QPushButton('Pin', checkable=True, backend=backend)
        events = []
        button.toggled.connect(lambda checked: events.append(('toggled', checked)))
        button.clicked.connect(lambda: events.append(('clicked', button.isChecked())))
        button.click()
        button.click()
        self.assertEqual(events, [('toggled', True), ('clicked', True),
                                  ('toggled', False), ('clicked', False)])
        button.setDisabled(True)
        self.assertFalse(button.click())
        self.assertFalse(button.isChecked())

    def test_programmatic_button_state_is_blockable_and_disabling_checkable_resets_it(self):
        button = QPushButton('Toggle', checkable=True, backend=backend_fixture())
        events = []
        button.toggled.connect(events.append)
        with QSignalBlocker(button):
            button.setChecked(True)
        self.assertTrue(button.isChecked())
        self.assertEqual(events, [])
        button.setCheckable(False)
        self.assertFalse(button.isChecked())
        self.assertEqual(events, [False])

    def test_native_button_click_supersedes_queued_worker_checked_value(self):
        pending = []
        button = QPushButton('Toggle', checkable=True, checked=True, backend=backend_fixture(),
                             after=lambda delay, cb, *args: pending.append((cb, args)))
        worker = threading.Thread(target=button.setChecked, args=(True,))
        worker.start()
        worker.join()
        button._clicked()
        for callback, args in pending:
            callback(*args)
        self.assertFalse(button.isChecked())

    def test_checkbox_click_and_check_state_have_separate_signals(self):
        box = QCheckBox('Option', backend=backend_fixture())
        toggles, clicks = [], []
        box.toggled.connect(toggles.append)
        box.clicked.connect(clicks.append)
        box.setCheckState(box.Checked)
        self.assertEqual(box.checkState(), box.Checked)
        self.assertEqual(clicks, [])
        box.click()
        self.assertEqual(toggles, [True, False])
        self.assertEqual(clicks, [False])
        with self.assertRaises(ValueError):
            box.setCheckState(1)

    def test_line_edit_finishes_once_after_enter_then_focus_loss(self):
        backend = backend_fixture()
        edit = QLineEdit('old', backend=backend)
        events = []
        edit.returnPressed.connect(lambda: events.append('return'))
        edit.editingFinished.connect(lambda: events.append('finished'))
        backend.set_value(edit.tag, 'new')
        edit._changed(edit.tag, 'new')
        self.assertTrue(edit.isModified())
        edit._return_pressed()
        edit._finish_editing()
        self.assertEqual(events, ['return', 'finished'])
        edit.setText('programmatic')
        self.assertFalse(edit.isModified())
        edit._finish_editing()
        self.assertEqual(events, ['return', 'finished'])

    def test_line_edit_focus_loss_commits_user_edit_and_late_events_are_ignored(self):
        backend = backend_fixture()
        edit = QLineEdit(backend=backend)
        finished = Mock()
        edit.editingFinished.connect(finished)
        edit._changed(edit.tag, 'typed')
        edit._finish_editing()
        edit._finish_editing()
        finished.assert_called_once_with()
        backend.get_item_state.return_value = {'active': False}
        edit._return_pressed()
        finished.assert_called_once_with()
        edit.delete()
        edit._return_pressed()
        edit._finish_editing()
        finished.assert_called_once_with()

    def test_line_edit_readonly_and_password_setters_update_native_configuration(self):
        backend = backend_fixture()
        edit = QLineEdit(backend=backend)
        edit.setReadOnly(True)
        self.assertTrue(backend.get_item_configuration(edit.tag)['readonly'])
        self.assertTrue(edit.isReadOnly())
        edit.setEchoMode(edit.Password)
        self.assertTrue(backend.get_item_configuration(edit.tag)['password'])
        self.assertEqual(edit.echoMode(), edit.Password)
        edit.setReadOnly(False)
        edit.setEchoMode(edit.Normal)
        self.assertFalse(backend.get_item_configuration(edit.tag)['readonly'])
        self.assertFalse(backend.get_item_configuration(edit.tag)['password'])

    def test_native_text_edit_supersedes_older_queued_modified_flag(self):
        pending = []
        edit = QLineEdit(backend=backend_fixture(),
                         after=lambda delay, cb, *args: pending.append((cb, args)))
        worker = threading.Thread(target=edit.setModified, args=(False,))
        worker.start()
        worker.join()
        edit._changed(edit.tag, 'new user text')
        for callback, args in pending:
            callback(*args)
        self.assertTrue(edit.isModified())

    def test_signal_blocker_can_temporarily_unblock_and_reblock(self):
        button = QPushButton('Toggle', checkable=True, backend=backend_fixture())
        events = []
        button.toggled.connect(events.append)
        with QSignalBlocker(button) as blocker:
            button.setChecked(True)
            blocker.unblock()
            button.setChecked(False)
            blocker.reblock()
            button.setChecked(True)
        self.assertFalse(button.signalsBlocked())
        self.assertEqual(events, [False])


class QtTabInteractionTests(unittest.TestCase):
    def test_insert_preserves_current_page_and_updates_its_index(self):
        tabs = QTabWidget(backend=backend_fixture())
        first, second = tabs.addTab('First'), tabs.addTab('Second')
        tabs.setCurrentWidget(second)
        changes = []
        tabs.currentChanged.connect(changes.append)
        inserted = tabs.insertTab(0, 'Inserted')
        self.assertIs(tabs.widget(0), inserted)
        self.assertIs(tabs.currentWidget(), second)
        self.assertEqual(tabs.currentIndex(), 2)
        self.assertEqual(changes, [2])
        self.assertEqual(tabs.indexOf(first), 1)

    def test_hide_and_restore_tabs_keep_current_page_valid(self):
        tabs = QTabWidget(backend=backend_fixture())
        first, second = tabs.addTab('First'), tabs.addTab('Second')
        tabs.setTabVisible(0, False)
        self.assertIs(tabs.currentWidget(), second)
        self.assertFalse(tabs.setCurrentIndex(0))
        tabs.setTabVisible(1, False)
        self.assertEqual(tabs.currentIndex(), -1)
        tabs.setTabVisible(0, True)
        self.assertIs(tabs.currentWidget(), first)

    def test_direct_page_deletion_and_clear_remove_stale_references(self):
        tabs = QTabWidget(backend=backend_fixture())
        first, second = tabs.addTab('First'), tabs.addTab('Second')
        first.delete()
        self.assertEqual(tabs.count(), 1)
        self.assertIs(tabs.currentWidget(), second)
        events = []
        tabs.currentChanged.connect(events.append)
        tabs.clear()
        self.assertEqual(tabs.count(), 0)
        self.assertEqual(tabs.currentIndex(), -1)
        self.assertTrue(second._deleted)
        self.assertEqual(events, [-1])
