from collections import deque
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))

from DearUIQt.core.application import QApplication
from DearUIQt.core.object import QObject, QEvent, Qt
from DearUIQt.gui.events import QKeyEvent, QMouseEvent, QWheelEvent


class Scheduler:
    def __init__(self):
        self.callbacks = deque()
    def after(self, _delay, callback, *args):
        self.callbacks.append((callback, args))


class Receiver(QObject):
    def __init__(self, name, parent=None, *, accept_types=()):
        super().__init__(parent=parent)
        self.name = name
        self.accept_types = set(accept_types)
        self.received = []

    def event(self, event):
        if event.type() in (
            QEvent.KeyPress, QEvent.KeyRelease, QEvent.ShortcutOverride,
            QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
            QEvent.MouseMove, QEvent.Wheel,
        ):
            self.received.append(event.type())
            if event.type() in self.accept_types:
                event.accept()
                return True
            event.ignore()
            return False
        return super().event(event)


class EventPropagationTests(unittest.TestCase):
    def setUp(self):
        self.scheduler = Scheduler()
        self.app = QApplication(after=self.scheduler.after)

    def tearDown(self):
        self.app.delete()

    def test_ignored_key_press_bubbles_to_parent(self):
        parent = Receiver('parent', accept_types=(QEvent.KeyPress,))
        child = Receiver('child', parent=parent)
        self.app.setFocusObject(child)
        try:
            event = QKeyEvent(QEvent.KeyPress, Qt.Key_A)
            self.assertTrue(self.app.dispatchKeyEvent(event))
            self.assertEqual(child.received, [QEvent.KeyPress])
            self.assertEqual(parent.received, [QEvent.KeyPress])
            self.assertTrue(event.isAccepted())
        finally:
            parent.delete()

    def test_accepted_key_press_stops_at_child(self):
        parent = Receiver('parent', accept_types=(QEvent.KeyPress,))
        child = Receiver('child', parent=parent, accept_types=(QEvent.KeyPress,))
        self.app.setFocusObject(child)
        try:
            self.assertTrue(self.app.dispatchKeyEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_A)))
            self.assertEqual(child.received, [QEvent.KeyPress])
            self.assertEqual(parent.received, [])
        finally:
            parent.delete()

    def test_ignored_mouse_press_bubbles_and_capture_belongs_to_handler(self):
        parent = Receiver('parent', accept_types=(QEvent.MouseButtonPress,))
        child = Receiver('child', parent=parent)
        try:
            event = QMouseEvent(
                QEvent.MouseButtonPress, (10, 20), button=Qt.LeftButton,
                buttons=Qt.LeftButton)
            handled, handled_by = self.app._deliver_input_event(child, event)
            self.assertTrue(handled)
            self.assertIs(handled_by, parent)
            self.assertEqual(child.received, [QEvent.MouseButtonPress])
            self.assertEqual(parent.received, [QEvent.MouseButtonPress])
        finally:
            parent.delete()

    def test_wheel_event_bubbles_and_preserves_delta(self):
        parent = Receiver('parent', accept_types=(QEvent.Wheel,))
        child = Receiver('child', parent=parent)
        try:
            event = QWheelEvent((5, 6), angle_delta=(0, 120))
            handled, handled_by = self.app._deliver_input_event(child, event)
            self.assertTrue(handled)
            self.assertIs(handled_by, parent)
            self.assertEqual(event.angleDelta().y(), 120)
            self.assertEqual(event.pixelDelta().x(), 0)
        finally:
            parent.delete()

    def test_send_event_uses_same_input_propagation_contract(self):
        parent = Receiver('parent', accept_types=(QEvent.KeyPress,))
        child = Receiver('child', parent=parent)
        try:
            event = QKeyEvent(QEvent.KeyPress, Qt.Key_A)
            self.assertTrue(QApplication.sendEvent(child, event))
            self.assertEqual(child.received, [QEvent.KeyPress])
            self.assertEqual(parent.received, [QEvent.KeyPress])
        finally:
            parent.delete()

    def test_top_level_boundary_prevents_input_leaking_to_owner(self):
        owner = Receiver('owner', accept_types=(QEvent.KeyPress,))
        class WindowReceiver(Receiver):
            def isWindow(self):
                return True
        window = WindowReceiver('window', parent=owner)
        child = Receiver('child', parent=window)
        try:
            self.assertFalse(QApplication.sendEvent(
                child, QKeyEvent(QEvent.KeyPress, Qt.Key_A)))
            self.assertEqual(child.received, [QEvent.KeyPress])
            self.assertEqual(window.received, [QEvent.KeyPress])
            self.assertEqual(owner.received, [])
        finally:
            owner.delete()

    def test_event_filter_can_stop_propagation_before_parent(self):
        parent = Receiver('parent', accept_types=(QEvent.KeyPress,))
        child = Receiver('child', parent=parent)
        class Filter(QObject):
            def eventFilter(self, watched, event):
                return watched is child and event.type() == QEvent.KeyPress
        filter_object = Filter()
        child.installEventFilter(filter_object)
        try:
            self.assertTrue(QApplication.sendEvent(
                child, QKeyEvent(QEvent.KeyPress, Qt.Key_A)))
            self.assertEqual(child.received, [])
            self.assertEqual(parent.received, [])
        finally:
            filter_object.delete()
            parent.delete()


class NativeKeyReleaseTests(unittest.TestCase):
    class Backend:
        mvKey_A = 11
        mvKey_LShift = 20
        mvKey_RShift = 21
        mvKey_LControl = 22
        mvKey_RControl = 23
        mvKey_LAlt = 24
        mvKey_RAlt = 25
        mvKey_LWin = 26
        mvKey_RWin = 27
        def is_key_down(self, _key):
            return False

    def test_native_key_release_is_delivered_as_qt_key_release(self):
        scheduler = Scheduler()
        app = QApplication(after=scheduler.after)
        received = []
        target = Receiver('target', accept_types=(QEvent.KeyRelease,))
        try:
            app._input_backend = self.Backend()
            app.setFocusObject(target)
            self.assertTrue(app._native_key_released(user_data=self.Backend.mvKey_A))
            self.assertEqual(received, [])
            self.assertEqual(target.received, [QEvent.KeyRelease])
        finally:
            target.delete()
            app.delete()


class NativeBridgeRegistrationTests(unittest.TestCase):
    class Registry:
        def __init__(self, backend):
            self.backend = backend
        def __enter__(self):
            self.backend.registry_open = True
            return 101
        def __exit__(self, exc_type, exc, tb):
            return False

    class Backend:
        mvKey_A = 11
        mvMouseButton_Left = 0
        mvKey_LShift = 20
        mvKey_RShift = 21
        mvKey_LControl = 22
        mvKey_RControl = 23
        mvKey_LAlt = 24
        mvKey_RAlt = 25
        mvKey_LWin = 26
        mvKey_RWin = 27
        def __init__(self):
            self.calls = []
            self.registry_open = False
        def handler_registry(self):
            return NativeBridgeRegistrationTests.Registry(self)
        def add_key_press_handler(self, **kwargs): self.calls.append(('key-press', kwargs))
        def add_key_release_handler(self, **kwargs): self.calls.append(('key-release', kwargs))
        def add_mouse_click_handler(self, **kwargs): self.calls.append(('mouse-press', kwargs))
        def add_mouse_release_handler(self, **kwargs): self.calls.append(('mouse-release', kwargs))
        def add_mouse_move_handler(self, **kwargs): self.calls.append(('mouse-move', kwargs))
        def add_mouse_wheel_handler(self, **kwargs): self.calls.append(('mouse-wheel', kwargs))
        def does_item_exist(self, _tag): return True
        def delete_item(self, _tag): pass
        def is_key_down(self, _key): return False

    def test_install_input_backend_registers_release_and_wheel_when_supported(self):
        scheduler = Scheduler()
        app = QApplication(after=scheduler.after)
        backend = self.Backend()
        try:
            self.assertTrue(app.installInputBackend(backend, key_names=('mvKey_A',)))
            kinds = [kind for kind, _ in backend.calls]
            self.assertIn('key-press', kinds)
            self.assertIn('key-release', kinds)
            self.assertIn('mouse-press', kinds)
            self.assertIn('mouse-release', kinds)
            self.assertIn('mouse-move', kinds)
            self.assertIn('mouse-wheel', kinds)
        finally:
            app.delete()


if __name__ == '__main__':
    unittest.main()
