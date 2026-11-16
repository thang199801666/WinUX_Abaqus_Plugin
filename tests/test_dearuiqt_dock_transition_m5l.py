import unittest
from pathlib import Path

from DearUIQt.docking import (
    QDockCommitTransaction,
    QDockFloatTransaction,
    QDockTransition,
)


class DockTransitionM5lTests(unittest.TestCase):
    def test_dock_factory_runs_shared_pipeline(self):
        calls = []
        legacy_started = []
        unified_started = []
        tx = QDockTransition.dock(
            prepare=lambda c: calls.append("prepare") or True,
            reparent=lambda c: calls.append("reparent") or True,
            finalize=lambda c: calls.append("finalize") or True,
            persist=lambda c: calls.append("persist") or True,
            activate=lambda c: calls.append("activate") or True,
        )
        tx.started.connect(lambda context: legacy_started.append(context["id"]))
        tx.transitionStarted.connect(
            lambda direction, context: unified_started.append((direction, context["id"])))
        self.assertTrue(tx.commit({"id": 7}))
        self.assertEqual(calls, ["prepare", "reparent", "finalize", "persist", "activate"])
        self.assertEqual(legacy_started, [7])
        self.assertEqual(unified_started, [(QDockTransition.Dock, 7)])
        self.assertEqual(tx.state(), tx.Committed)
        self.assertEqual(tx.diagnostics()["direction"], "dock")

    def test_float_factory_pauses_and_resumes_same_engine(self):
        calls = []
        tx = QDockTransition.float(
            prepare=lambda c: calls.append("prepare") or True,
            create=lambda c: calls.append("create") or True,
            present=lambda c: calls.append("present") or True,
            transfer=lambda c: calls.append("transfer") or True,
            finalize=lambda c: calls.append("finalize") or True,
            persist=lambda c: calls.append("persist") or True,
            activate=lambda c: calls.append("activate") or True,
        )
        self.assertTrue(tx.begin({"id": 1}))
        self.assertTrue(tx.isAwaitingContinuation())
        self.assertEqual(calls, ["prepare", "create", "present"])
        self.assertTrue(tx.continueTransition())
        self.assertEqual(calls, [
            "prepare", "create", "present", "transfer", "finalize", "persist", "activate"
        ])
        self.assertEqual(tx.state(), tx.Committed)

    def test_cancel_and_failure_share_rollback_contract(self):
        rollbacks = []
        tx = QDockTransition.float(
            prepare=lambda c: True,
            create=lambda c: True,
            present=lambda c: True,
            rollback=lambda context, completed, error: rollbacks.append((completed, str(error))),
        )
        self.assertTrue(tx.begin({}))
        self.assertTrue(tx.cancel("dock requested"))
        self.assertEqual(tx.state(), tx.RolledBack)
        self.assertEqual(rollbacks[0][0], ("prepare", "create", "present"))
        self.assertFalse(tx.continueTransition())

    def test_compatibility_wrappers_use_unified_engine(self):
        self.assertTrue(issubclass(QDockCommitTransaction, QDockTransition))
        self.assertTrue(issubclass(QDockFloatTransaction, QDockTransition))
        tx = QDockFloatTransaction(prepare=lambda c: True, create=lambda c: True, present=lambda c: True)
        self.assertTrue(tx.begin({}))
        self.assertEqual(tx.state(), tx.AwaitingPresentation)
        self.assertTrue(tx.cancel("compat"))

    def test_winux_paths_use_unified_transition_factories(self):
        root = Path(__file__).resolve().parents[1]
        console = (root / "WinUx/ui/behaviors/docking/console.py").read_text(encoding="utf-8")
        plot = (root / "WinUx/ui/behaviors/docking/plot.py").read_text(encoding="utf-8")
        for source in (console, plot):
            self.assertIn("QDockTransition.float(", source)
            self.assertIn("QDockTransition.dock(", source)
            self.assertNotIn("transaction = QDockFloatTransaction(", source)
            self.assertNotIn("transaction = QDockCommitTransaction(", source)


if __name__ == "__main__":
    unittest.main()
