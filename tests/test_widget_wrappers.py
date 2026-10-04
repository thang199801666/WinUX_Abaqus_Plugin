import threading
import unittest
from unittest.mock import Mock

from WinUx.widgets import QObject, QLabel, QLineEdit, QPushButton, QProgressBar, QVBoxLayout


class WidgetTests(unittest.TestCase):
    def backend(self):
        backend = Mock()
        backend.does_item_exist.return_value = True
        backend.add_text.return_value = 1
        backend.add_input_text.return_value = 2
        backend.add_button.return_value = 3
        backend.add_progress_bar.return_value = 4
        return backend

    def test_parent_deletion_releases_children_and_signals(self):
        parent = QObject()
        backend = self.backend()
        label = QLabel("a", parent=parent, backend=backend)
        destroyed = Mock()
        label.destroyed.connect(destroyed)
        parent.delete()
        parent.delete()
        backend.delete_item.assert_called_once_with(1)
        destroyed.assert_called_once_with(label)
        self.assertEqual(parent._children, [])

    def test_repeated_label_and_progress_values_skip_native_writes(self):
        backend = self.backend()
        label = QLabel("a", backend=backend)
        label.setText("a")
        label.setText("b")
        label.setText("b")
        backend.set_value.assert_called_once_with(1, "b")
        progress = QProgressBar(backend=backend)
        progress.setValue(2)
        progress.setValue(1)
        self.assertEqual(backend.set_value.call_count, 2)

    def test_worker_updates_are_queued_and_coalesced(self):
        callbacks = []
        backend = self.backend()
        label = QLabel("a", backend=backend,
                       after=lambda delay, callback, *args: callbacks.append((callback, args)))
        worker = threading.Thread(target=lambda: [label.setText(str(n)) for n in range(100)])
        worker.start()
        worker.join()
        backend.set_value.assert_not_called()
        self.assertEqual(len(callbacks), 1)
        callback, args = callbacks.pop()
        callback(*args)
        backend.set_value.assert_called_once_with(1, "99")

    def test_deletion_invalidates_worker_updates(self):
        callbacks = []
        backend = self.backend()
        label = QLabel("a", backend=backend,
                       after=lambda delay, callback, *args: callbacks.append((callback, args)))
        worker = threading.Thread(target=label.setText, args=("b",))
        worker.start()
        worker.join()
        label.delete()
        callback, args = callbacks.pop()
        callback(*args)
        backend.set_value.assert_not_called()

    def test_button_and_lineedit_emit_signals(self):
        backend = self.backend()
        button = QPushButton("go", backend=backend)
        clicked = Mock()
        button.clicked.connect(clicked)
        button._clicked()
        clicked.assert_called_once_with()
        edit = QLineEdit("a", backend=backend)
        changed = Mock()
        edit.textChanged.connect(changed)
        edit.setText("b")
        edit.setText("b")
        changed.assert_called_once_with("b")

    def test_ui_setter_supersedes_old_queued_worker_update(self):
        callbacks = []
        backend = self.backend()
        label = QLabel("a", backend=backend,
                       after=lambda delay, callback, *args: callbacks.append((callback, args)))
        worker = threading.Thread(target=label.setText, args=("old",))
        worker.start()
        worker.join()
        label.setText("new")
        callback, args = callbacks.pop()
        callback(*args)
        backend.set_value.assert_called_once_with(1, "new")

    def test_layout_owns_children_and_passes_native_parent(self):
        backend = self.backend()
        backend.add_group.return_value = 5
        layout = QVBoxLayout(backend=backend)
        label = QLabel("a", parent=layout, backend=backend)
        backend.add_text.assert_called_once_with("a", parent=5)
        layout.delete()
        self.assertTrue(label._deleted)
        self.assertEqual(backend.delete_item.call_count, 2)
