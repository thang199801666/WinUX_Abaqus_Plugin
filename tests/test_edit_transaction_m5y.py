"""M5y: explicit Qt-style edit transactions for Plot Digitizer gestures."""
import unittest

from DearUIQt import QEditTransaction
from WinUx.plotdigitizer.ui.controllers.calibration import CalibrationController
from WinUx.plotdigitizer.ui.controllers.canvas import CanvasController


class EditTransactionM5yTests(unittest.TestCase):
    def test_begin_update_commit_lifecycle(self):
        tx = QEditTransaction()
        events = []
        tx.started.connect(lambda label, ctx: events.append(("start", label, ctx)))
        tx.updated.connect(lambda value, ctx: events.append(("update", value, ctx)))
        tx.committed.connect(lambda value, ctx, result: events.append(("commit", value, ctx, result)))
        self.assertTrue(tx.begin("Move point", context={"kind": "point"}, value=(1, 2)))
        self.assertTrue(tx.update((3, 4)))
        self.assertTrue(tx.commit(value=(5, 6), apply=lambda value: tuple(value)))
        self.assertFalse(tx.isActive())
        self.assertEqual("committed", tx.state())
        self.assertEqual((5, 6), tx.value())
        self.assertEqual("start", events[0][0])
        self.assertEqual("update", events[1][0])
        self.assertEqual("commit", events[2][0])

    def test_cancel_rolls_back_live_edit_snapshot(self):
        state = {"value": 1}
        tx = QEditTransaction()
        tx.begin("Live edit", capture=lambda: dict(state), restore=lambda snapshot: state.update(snapshot))
        tx.update(7, apply=lambda value: state.__setitem__("value", value))
        self.assertEqual(7, state["value"])
        self.assertTrue(tx.cancel())
        self.assertEqual(1, state["value"])
        self.assertEqual("canceled", tx.state())

    def test_failed_commit_rolls_back(self):
        state = {"value": 2}
        tx = QEditTransaction()
        tx.begin("Broken edit", capture=lambda: dict(state), restore=lambda snapshot: state.update(snapshot))
        tx.update(9, apply=lambda value: state.__setitem__("value", value))
        with self.assertRaisesRegex(RuntimeError, "boom"):
            tx.commit(apply=lambda _value: (_ for _ in ()).throw(RuntimeError("boom")))
        self.assertEqual(2, state["value"])
        self.assertEqual("failed", tx.state())

    def test_plot_controllers_use_explicit_transaction(self):
        calibration_source = open(CalibrationController.__module__.replace('.', '/') + '.py', 'r', encoding='utf-8') if False else None
        import inspect
        cal = inspect.getsource(CalibrationController)
        canvas = inspect.getsource(CanvasController)
        self.assertIn('self._edit_transaction().begin(', cal)
        self.assertIn('transaction.commit(', cal)
        self.assertIn('transaction.update(', canvas)
        self.assertIn('transaction.cancel()', canvas)


if __name__ == "__main__":
    unittest.main()
