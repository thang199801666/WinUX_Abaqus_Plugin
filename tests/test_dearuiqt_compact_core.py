import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))

from DearUIQt.core import QChildEvent, QCloseEvent, QEvent, QKeyEvent, QMouseEvent, Qt, Signal
from DearUIQt.core.object import SignalConnection


class CompactCoreTests(unittest.TestCase):
    def test_signal_storage_is_compact_without_changing_snapshot_semantics(self):
        signal = Signal()
        self.assertFalse(hasattr(signal, '__dict__'))
        seen = []
        connection = signal.connect(seen.append)
        self.assertIsInstance(connection, SignalConnection)
        self.assertFalse(hasattr(connection, '__dict__'))
        signal.emit(7)
        self.assertEqual(seen, [7])
        connection.disconnect()
        signal.emit(8)
        self.assertEqual(seen, [7])

    def test_event_types_are_compact_and_keep_payload_acceptance(self):
        event = QEvent(QEvent.User, answer=42)
        self.assertFalse(hasattr(event, '__dict__'))
        self.assertEqual(event.payload['answer'], 42)
        self.assertTrue(event.isAccepted())
        event.ignore()
        self.assertFalse(event.isAccepted())
        event.accept()
        self.assertTrue(event.isAccepted())

    def test_specialized_events_remain_slot_only(self):
        close = QCloseEvent()
        key = QKeyEvent(QEvent.KeyPress, 65, Qt.ControlModifier, text='a')
        mouse = QMouseEvent(QEvent.MouseMove, (12.5, 4.5), buttons=Qt.LeftButton)
        child_value = object()
        child = QChildEvent(QEvent.ChildAdded, child_value)
        for event in (close, key, mouse, child):
            self.assertFalse(hasattr(event, '__dict__'))
        self.assertEqual(key.key(), 65)
        self.assertEqual(key.text(), 'a')
        self.assertEqual(tuple(mouse.position()), (12.5, 4.5))
        self.assertIs(child.child(), child_value)
        self.assertTrue(child.added())


if __name__ == '__main__':
    unittest.main(verbosity=2)
