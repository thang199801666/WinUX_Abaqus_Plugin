import unittest
from pathlib import Path

from DearUIQt.docking import QDockCommitTransaction


class DockCommitTransactionTests(unittest.TestCase):
    def test_commit_runs_phases_in_qt_order(self):
        calls = []
        tx = QDockCommitTransaction(
            prepare=lambda c: calls.append("prepare") or True,
            reparent=lambda c: calls.append("reparent") or True,
            finalize=lambda c: calls.append("finalize") or True,
            persist=lambda c: calls.append("persist") or True,
            activate=lambda c: calls.append("activate") or True,
        )
        self.assertTrue(tx.commit({"id": 1}))
        self.assertEqual(calls, ["prepare", "reparent", "finalize", "persist", "activate"])
        self.assertEqual(tx.state(), tx.Committed)

    def test_failure_rolls_back_and_skips_later_phases(self):
        calls = []
        def rollback(context, completed, error):
            calls.append(("rollback", completed, type(error).__name__))
        tx = QDockCommitTransaction(
            prepare=lambda c: calls.append("prepare") or True,
            reparent=lambda c: calls.append("reparent") or False,
            finalize=lambda c: calls.append("finalize") or True,
            persist=lambda c: calls.append("persist") or True,
            activate=lambda c: calls.append("activate") or True,
            rollback=rollback,
        )
        self.assertFalse(tx.commit({}))
        self.assertEqual(calls[0:2], ["prepare", "reparent"])
        self.assertEqual(calls[2][0], "rollback")
        self.assertEqual(calls[2][1], ("prepare",))
        self.assertEqual(tx.state(), tx.RolledBack)

    def test_reentrant_commit_is_rejected(self):
        holder = {}
        def prepare(context):
            self.assertFalse(holder["tx"].commit({"nested": True}))
            return True
        tx = holder["tx"] = QDockCommitTransaction(prepare=prepare)
        self.assertTrue(tx.commit({"outer": True}))

    def test_winux_dock_paths_use_shared_transaction(self):
        root = Path(__file__).resolve().parents[1]
        console = (root / "WinUx/ui/behaviors/docking/console.py").read_text(encoding="utf-8")
        plot = (root / "WinUx/ui/behaviors/docking/plot.py").read_text(encoding="utf-8")
        self.assertIn("QDockCommitTransaction", console)
        self.assertIn("transaction.commit", console)
        self.assertIn("QDockCommitTransaction", plot)
        self.assertIn("transaction.commit", plot)


if __name__ == "__main__":
    unittest.main()
