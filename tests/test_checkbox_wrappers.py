import threading
import unittest
from unittest.mock import Mock

from WinUx.widgets import QCheckBox, QLineEdit, QObject, QSignalBlocker


class CheckboxTests(unittest.TestCase):
    def fixture(self, cls=QCheckBox):
        pending = []
        backend = Mock()
        backend.add_checkbox.return_value = 1
        backend.add_input_text.return_value = 2
        backend.does_item_exist.return_value = True
        widget = cls('Option', backend=backend,
                     after=lambda delay, cb, *args: pending.append((cb, args)))
        return widget, backend, pending

    def drain(self, pending):
        while pending:
            cb, args = pending.pop(0)
            cb(*args)

    def test_setters_deduplicate_and_signal_changed_value_only(self):
        box, backend, _ = self.fixture()
        changes = []
        box.toggled.connect(changes.append)
        box.setChecked(False)
        box.setChecked(True)
        box.setChecked(True)
        backend.set_value.assert_called_once_with(1, True)
        self.assertEqual(changes, [True])
        box.setText('Option')
        box.setText('New')
        box.setText('New')
        backend.configure_item.assert_called_once_with(1, label='New')

    def test_worker_burst_delivers_latest_value_once(self):
        box, backend, pending = self.fixture()
        changes = []
        box.toggled.connect(changes.append)
        worker = threading.Thread(target=lambda: [box.setChecked(n % 2 == 1) for n in range(1000)])
        worker.start()
        worker.join()
        self.assertEqual(len(pending), 1)
        backend.set_value.assert_not_called()
        self.drain(pending)
        backend.set_value.assert_called_once_with(1, True)
        self.assertEqual(changes, [True])

    def test_user_interaction_supersedes_queued_value_even_without_change(self):
        box, backend, pending = self.fixture()
        worker = threading.Thread(target=box.setChecked, args=(True,))
        worker.start()
        worker.join()
        box._changed(1, False)
        self.drain(pending)
        backend.set_value.assert_not_called()

    def test_lineedit_user_input_supersedes_queued_worker_value(self):
        edit, backend, pending = self.fixture(QLineEdit)
        changes = []
        edit.textChanged.connect(changes.append)
        worker = threading.Thread(target=edit.setText, args=('Old worker value',))
        worker.start()
        worker.join()
        edit._changed(2, 'User text')
        self.drain(pending)
        backend.set_value.assert_not_called()
        self.assertEqual(changes, ['User text'])

    def test_signal_blocker_suppresses_programmatic_changes(self):
        box, backend, _ = self.fixture()
        changes = []
        box.toggled.connect(changes.append)
        with QSignalBlocker(box):
            box.setChecked(True)
        backend.set_value.assert_called_once_with(1, True)
        self.assertEqual(changes, [])
        box._changed(1, False)
        self.assertEqual(changes, [False])

    def test_parent_disposal_invalidates_pending_and_native_callback(self):
        parent = QObject()
        box, backend, pending = self.fixture()
        box.setParent(parent)
        changes = []
        box.toggled.connect(changes.append)
        worker = threading.Thread(target=box.setChecked, args=(True,))
        worker.start()
        worker.join()
        parent.delete()
        box._changed(1, True)
        self.drain(pending)
        self.assertEqual(changes, [])
        backend.set_value.assert_not_called()
        backend.delete_item.assert_called_once_with(1)

    def test_worker_getter_is_rejected_without_native_access(self):
        box, backend, _ = self.fixture()
        errors = []
        def read():
            try:
                box.isChecked()
            except RuntimeError as exc:
                errors.append(str(exc))
        worker = threading.Thread(target=read)
        worker.start()
        worker.join()
        self.assertEqual(len(errors), 1)
        backend.get_value.assert_not_called()

    def test_initial_value_and_ui_getter_use_native_boolean(self):
        backend = Mock()
        box = QCheckBox('Option', checked=True, backend=backend)
        self.assertTrue(backend.add_checkbox.call_args.kwargs['default_value'])
        backend.get_value.return_value = False
        self.assertFalse(box.isChecked())


if __name__ == '__main__':
    unittest.main()
