import unittest
from pathlib import Path

from DearUIQt.docking import QDockFloatTransaction


class DockFloatTransactionTests(unittest.TestCase):
    def test_two_stage_float_runs_in_qt_order(self):
        calls = []
        tx = QDockFloatTransaction(
            prepare=lambda c: calls.append("prepare") or True,
            create=lambda c: calls.append("create") or True,
            present=lambda c: calls.append("present") or True,
            transfer=lambda c: calls.append("transfer") or True,
            finalize=lambda c: calls.append("finalize") or True,
            persist=lambda c: calls.append("persist") or True,
            activate=lambda c: calls.append("activate") or True,
        )
        self.assertTrue(tx.begin({"id": 1}))
        self.assertEqual(tx.state(), tx.AwaitingPresentation)
        self.assertEqual(calls, ["prepare", "create", "present"])
        self.assertTrue(tx.complete())
        self.assertEqual(
            calls,
            ["prepare", "create", "present", "transfer", "finalize", "persist", "activate"],
        )
        self.assertEqual(tx.state(), tx.Committed)

    def test_transfer_failure_rolls_back_and_skips_persist(self):
        calls = []
        def rollback(context, completed, error):
            calls.append(("rollback", completed, type(error).__name__))
        tx = QDockFloatTransaction(
            prepare=lambda c: calls.append("prepare") or True,
            create=lambda c: calls.append("create") or True,
            present=lambda c: calls.append("present") or True,
            transfer=lambda c: calls.append("transfer") or False,
            persist=lambda c: calls.append("persist") or True,
            rollback=rollback,
        )
        self.assertTrue(tx.begin({}))
        self.assertFalse(tx.complete())
        self.assertEqual(calls[0:4], ["prepare", "create", "present", "transfer"])
        self.assertEqual(calls[4][0], "rollback")
        self.assertEqual(calls[4][1], ("prepare", "create", "present"))
        self.assertEqual(tx.state(), tx.RolledBack)
        self.assertNotIn("persist", calls)

    def test_cancel_while_waiting_rolls_back_once(self):
        rollbacks = []
        tx = QDockFloatTransaction(
            prepare=lambda c: True,
            create=lambda c: True,
            present=lambda c: True,
            rollback=lambda context, completed, error: rollbacks.append(completed),
        )
        self.assertTrue(tx.begin({}))
        self.assertTrue(tx.cancel("dock again"))
        self.assertEqual(tx.state(), tx.RolledBack)
        self.assertEqual(rollbacks, [("prepare", "create", "present")])
        self.assertFalse(tx.complete())
        self.assertEqual(len(rollbacks), 1)

    def test_reentrant_begin_is_rejected(self):
        holder = {}
        def prepare(context):
            self.assertFalse(holder["tx"].begin({"nested": True}))
            return True
        tx = holder["tx"] = QDockFloatTransaction(prepare=prepare)
        self.assertTrue(tx.begin({"outer": True}))

    def test_winux_undock_paths_use_shared_float_transaction(self):
        root = Path(__file__).resolve().parents[1]
        console = (root / "WinUx/ui/behaviors/docking/console.py").read_text(encoding="utf-8")
        plot = (root / "WinUx/ui/behaviors/docking/plot.py").read_text(encoding="utf-8")
        self.assertIn("QDockFloatTransaction", console)
        self.assertIn("_start_console_float_transaction", console)
        self.assertIn("QDockFloatTransaction", plot)
        self.assertIn("_start_plot_float_transaction", plot)


if __name__ == "__main__":
    unittest.main()
