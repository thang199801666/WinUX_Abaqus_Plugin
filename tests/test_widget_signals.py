import threading
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from WinUx.widgets import QObject, Signal, QSignalBlocker, QLabel, QLineEdit, QVBoxLayout, QPushButton


class Receiver(QObject):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.received = []

    def receive(self, value):
        self.received.append((value, threading.get_ident()))


class SignalTests(unittest.TestCase):
    def test_bound_receiver_disconnects_on_deletion(self):
        signal, receiver = Signal(), Receiver()
        connection = signal.connect(receiver.receive)
        receiver.delete()
        signal.emit("late")
        self.assertEqual(receiver.received, [])
        self.assertFalse(connection.active)
        self.assertEqual(signal._slots, [])

    def test_queued_signals_preserve_events_and_deliver_on_ui_thread(self):
        pending = []
        receiver = Receiver(after=lambda delay, cb, *args: pending.append((cb, args)))
        signal = Signal()
        signal.connect(receiver.receive, queued=True)
        worker = threading.Thread(target=lambda: [signal.emit(i) for i in range(10)])
        worker.start()
        worker.join()
        self.assertEqual(receiver.received, [])
        self.assertEqual(len(pending), 10)
        for callback, args in pending:
            callback(*args)
        self.assertEqual(receiver.received, [(i, threading.get_ident()) for i in range(10)])

    def test_disconnect_invalidates_queued_events(self):
        pending = []
        receiver = Receiver(after=lambda delay, cb, *args: pending.append((cb, args)))
        signal = Signal()
        connection = signal.connect(receiver.receive, queued=True)
        signal.emit("late")
        connection.disconnect()
        pending[0][0](*pending[0][1])
        self.assertEqual(receiver.received, [])

    def test_deleted_receiver_invalidates_queued_events(self):
        pending = []
        receiver = Receiver(after=lambda delay, cb, *args: pending.append((cb, args)))
        signal = Signal()
        signal.connect(receiver.receive, queued=True)
        signal.emit("late")
        receiver.delete()
        pending[0][0](*pending[0][1])
        self.assertEqual(receiver.received, [])

    def test_duplicate_connection_does_not_duplicate_delivery(self):
        signal, receiver = Signal(), Receiver()
        self.assertIs(signal.connect(receiver.receive), signal.connect(receiver.receive))
        signal.emit(1)
        self.assertEqual(len(receiver.received), 1)

    def test_queued_connection_requires_scheduler(self):
        with self.assertRaises(ValueError):
            Signal().connect(Receiver().receive, queued=True)

    def test_reparent_validates_cycles_before_detaching(self):
        root, other = QObject(), QObject()
        child = QObject(root)
        with self.assertRaises(ValueError):
            root.setParent(child)
        self.assertIs(child.parent, root)
        child.setParent(other)
        root.delete()
        self.assertFalse(child._deleted)
        other.delete()
        self.assertTrue(child._deleted)

    def test_signal_blocker_restores_nested_state_on_exception(self):
        receiver = Receiver()
        signal = Signal(receiver)
        signal.connect(receiver.receive)
        with self.assertRaises(ValueError):
            with QSignalBlocker(receiver):
                with QSignalBlocker(receiver):
                    signal.emit(1)
                signal.emit(2)
                raise ValueError("test")
        signal.emit(3)
        self.assertEqual(receiver.received, [(3, threading.get_ident())])

    def test_children_inherit_backend_and_scheduler(self):
        pending = []
        backend = Mock()
        backend.add_group.return_value = 1
        backend.add_text.return_value = 2
        layout = QVBoxLayout(backend=backend, after=lambda delay, cb, *args: pending.append((cb, args)))
        label = QLabel("old", parent=layout)
        worker = threading.Thread(target=label.setText, args=("new",))
        worker.start()
        worker.join()
        pending[0][0](*pending[0][1])
        backend.set_value.assert_called_once_with(2, "new")

    def test_deleted_parent_refused_before_native_construction(self):
        parent = QObject()
        parent.delete()
        backend = Mock()
        with self.assertRaises(RuntimeError):
            QLabel(parent=parent, backend=backend)
        backend.add_text.assert_not_called()

    def test_cleanup_releases_siblings_when_destroyed_slot_raises(self):
        parent = QObject()
        backend = Mock()
        backend.add_text.side_effect = [1, 2]
        first, second = QLabel(parent=parent, backend=backend), QLabel(parent=parent, backend=backend)
        first.destroyed.connect(Mock(side_effect=ValueError("slot failed")))
        with self.assertRaises(ValueError):
            parent.delete()
        self.assertTrue(second._deleted)
        self.assertEqual(backend.delete_item.call_count, 2)
        self.assertEqual(parent._children, [])

    def test_line_edit_blocked_sync_still_updates_native_value(self):
        backend = Mock()
        edit = QLineEdit(backend=backend)
        changed = Mock()
        edit.textChanged.connect(changed)
        with QSignalBlocker(edit):
            edit.setText("sync")
        changed.assert_not_called()
        backend.set_value.assert_called_once_with(edit.tag, "sync")

    def test_dialog_action_preserves_callback_default_and_disposal(self):
        source = Path(__file__).resolve().parents[1] / "WinUx/dialogs/qt_dialog.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "QtDialog")
        methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in {"action", "own_widget"}]
        backend = Mock()
        backend.add_button.return_value = 17
        namespace = {"QPushButton": QPushButton, "dpg": backend,
                     "DialogMetrics": SimpleNamespace(BUTTON_HEIGHT=28)}
        for theme in ("primary_button_theme", "danger_button_theme", "secondary_button_theme"):
            namespace[theme] = lambda: "theme"
        harness = ast.ClassDef(name="Harness", bases=[], keywords=[], body=methods, decorator_list=[])
        exec(compile(ast.fix_missing_locations(ast.Module(body=[harness], type_ignores=[])), str(source), "exec"), namespace)
        dialog = namespace["Harness"]()
        dialog._widget_owner = QObject()
        dialog.view, dialog.footer = SimpleNamespace(after=Mock()), 9
        dialog.action_width = lambda label: 80
        accepted = Mock()
        self.assertEqual(dialog.action("Run", accepted, "primary", True), 17)
        click = backend.add_button.call_args.kwargs["callback"]
        click()
        accepted.assert_called_once_with()
        self.assertIs(dialog._default, accepted)
        self.assertEqual(dialog._default_button, 17)
        dialog._widget_owner.delete()
        click()
        accepted.assert_called_once_with()
        backend.delete_item.assert_called_once_with(17)
