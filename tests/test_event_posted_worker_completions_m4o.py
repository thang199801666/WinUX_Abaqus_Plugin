from pathlib import Path
from types import SimpleNamespace
import unittest

from WinUx.runtime.completion import submit_with_completion


ROOT = Path(__file__).resolve().parents[1]


class Scheduler:
    def __init__(self):
        self.calls = []

    def after(self, delay, callback, *args):
        self.calls.append((delay, callback, args))
        callback(*args)


class EventPostedWorkerCompletionsM4o(unittest.TestCase):
    def test_real_manager_path_passes_on_done_to_submitter(self):
        captured = {}
        manager = object()
        expected = SimpleNamespace(state="queued")

        def submitter(name, worker, **kwargs):
            captured.update(name=name, worker=worker, kwargs=kwargs)
            return expected

        callback = lambda handle: None
        handle = submit_with_completion(
            submitter, manager, "task", lambda: 3, callback, key="k")
        self.assertIs(handle, expected)
        self.assertIs(captured["kwargs"]["on_done"], callback)
        self.assertEqual(captured["kwargs"]["key"], "k")

    def test_legacy_path_delivers_worker_result_once(self):
        scheduler = Scheduler()
        delivered = []

        def submitter(name, worker, **kwargs):
            self.assertEqual(worker(), 7)
            return SimpleNamespace(state="queued")

        submit_with_completion(
            submitter, None, "legacy", lambda: 7,
            lambda handle: delivered.append((handle.state, handle.result)),
            scheduler=scheduler,
        )
        self.assertEqual(delivered, [("completed", 7)])

    def test_migrated_workers_use_completion_adapter(self):
        paths = [
            "WinUx/controllers/odb/analysis.py",
            "WinUx/controllers/jobs/plot.py",
            "WinUx/controllers/transfer/controller.py",
            "WinUx/controllers/transfer/clipboard.py",
            "WinUx/controllers/console/facade.py",
        ]
        for relative in paths:
            text = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(relative=relative):
                self.assertIn("submit_with_completion", text)

    def test_odb_workers_no_longer_post_ui_from_operation_context(self):
        text = (ROOT / "WinUx/controllers/odb/analysis.py").read_text(encoding="utf-8")
        self.assertNotIn("context.post(", text)
        self.assertNotIn("report_rejection(", text)


if __name__ == "__main__":
    unittest.main()
