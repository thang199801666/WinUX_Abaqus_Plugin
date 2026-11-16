from collections import deque
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))

from DearUIQt.core.application import QApplication
from DearUIQt.core.input import QInputTarget
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.core.object import Qt, QEvent
from DearUIQt.gui.events import QKeyEvent


class Scheduler:
    def __init__(self):
        self.callbacks = deque()
    def after(self, _delay, callback, *args):
        self.callbacks.append((callback, args))


class Backend:
    mvKey_Escape = 10
    mvKey_Tab = 11
    mvKey_Return = 12
    mvKey_Enter = 13
    mvKey_NumPadEnter = 14
    mvKey_Spacebar = 15
    mvKey_Up = 16
    mvKey_Down = 17
    mvKey_Home = 18
    mvKey_End = 19
    mvKey_Prior = 20
    mvKey_Next = 21
    mvKey_A = 22
    mvKey_LShift = 30
    mvKey_RShift = 31
    mvKey_LControl = 32
    mvKey_RControl = 33
    mvKey_LAlt = 34
    mvKey_RAlt = 35
    mvKey_LWin = 36
    mvKey_RWin = 37

    def is_key_down(self, _key):
        return False


class KeyTranslationTests(unittest.TestCase):
    def test_application_delivers_qt_key_values_to_focus_object(self):
        scheduler = Scheduler()
        app = QApplication(after=scheduler.after)
        backend = Backend()
        received = []
        target = QInputTarget(key_handler=lambda event: received.append(event.key()) or True)
        try:
            app._input_backend = backend
            app.setFocusObject(target)
            self.assertTrue(app._native_key_pressed(user_data=backend.mvKey_Return))
            self.assertEqual(received, [Qt.Key_Return])
            self.assertTrue(app._native_key_pressed(user_data=backend.mvKey_Tab))
            self.assertEqual(received[-1], Qt.Key_Tab)
            self.assertTrue(app._native_key_pressed(user_data=backend.mvKey_Escape))
            self.assertEqual(received[-1], Qt.Key_Escape)
        finally:
            target.delete()
            app.delete()


    def test_qdialog_handles_qt_key_codes_for_escape_enter_and_tab(self):
        calls = []
        class Dummy:
            shortcuts = {}
            active_table = None
            _control_wrappers = {}
            def _accepts_dialog_keys(self): return True
            def focusWidget(self): return None
            def reject(self): calls.append(('reject', None))
            def invoke_default(self): calls.append(('default', None))
            def focusNextPrevChild(self, next=True): calls.append(('tab', bool(next)))

        dummy = Dummy()
        self.assertTrue(QtDialog._handle_key_event(dummy, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape)))
        self.assertTrue(QtDialog._handle_key_event(dummy, QKeyEvent(QEvent.KeyPress, Qt.Key_Return)))
        self.assertTrue(QtDialog._handle_key_event(
            dummy, QKeyEvent(QEvent.KeyPress, Qt.Key_Tab, Qt.ShiftModifier)))
        self.assertEqual(calls, [('reject', None), ('default', None), ('tab', False)])

    def test_unmapped_native_key_is_preserved(self):
        scheduler = Scheduler()
        app = QApplication(after=scheduler.after)
        backend = Backend()
        received = []
        target = QInputTarget(key_handler=lambda event: received.append(event.key()) or True)
        try:
            app._input_backend = backend
            app.setFocusObject(target)
            self.assertTrue(app._native_key_pressed(user_data=9999))
            self.assertEqual(received, [9999])
        finally:
            target.delete()
            app.delete()


if __name__ == '__main__':
    unittest.main()
