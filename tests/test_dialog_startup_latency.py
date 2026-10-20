"""IPC startup must wake on commands without hidden-frame polling."""
import ast
from pathlib import Path
import queue
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


def load_class(path, name, **namespace):
    source = ROOT / path
    tree = ast.parse(source.read_text(encoding='utf-8'))
    tree.body = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name]
    exec(compile(tree, str(source), 'exec'), namespace)
    return namespace[name]


class DialogStartupLatencyTests(unittest.TestCase):
    def runtime(self, timeout=.1):
        deliver = Mock()
        cls = load_class('WinUx/dialogs/floating_runtime.py', 'FloatingDialogRuntime',
                         queue=queue, time=time, PUBLISH_HANDSHAKE_TIMEOUT=timeout,
                         deliver_command=deliver)
        runtime = cls.__new__(cls)
        runtime.incoming = queue.Queue()
        runtime.view = SimpleNamespace(drain=Mock())
        alive = [True]
        runtime.form = SimpleNamespace(winfo_exists=lambda: alive[0],
                                      destroy=lambda: alive.__setitem__(0, False))
        runtime._publish_requested = runtime._commit_requested = False
        runtime.desired_visible = True
        runtime._render_settled_frame = Mock()
        return runtime, deliver

    def test_startup_preserves_command_order_without_render_polling(self):
        runtime, deliver = self.runtime()
        for message in ({'command': 'hide'}, {'command': 'output', 'args': ['latest']},
                        {'command': 'publish'}, {'command': 'publish_commit'}):
            runtime.incoming.put(message)
        self.assertTrue(runtime._wait_for_publish())
        self.assertFalse(runtime.desired_visible)
        deliver.assert_called_once_with(runtime.form, 'output', ['latest'])
        self.assertFalse(runtime._commit_requested)
        self.assertTrue(runtime._wait_for_publish_commit())
        runtime._render_settled_frame.assert_not_called()

    def test_close_during_publish_wait_returns_immediately(self):
        runtime, deliver = self.runtime()
        runtime.incoming.put({'command': 'close'})
        self.assertFalse(runtime._wait_for_publish())
        deliver.assert_not_called()
        runtime._render_settled_frame.assert_not_called()

    def test_missing_ack_times_out_without_spinning_frames(self):
        runtime, _ = self.runtime(timeout=.01)
        self.assertFalse(runtime._wait_for_publish_commit())
        runtime._render_settled_frame.assert_not_called()
        runtime.view.drain.assert_called()

    def test_claim_can_defer_refill_until_dialog_has_been_published(self):
        cls = load_class('WinUx/dialogs/prewarm_pool.py', 'DialogPrewarmPool', threading=threading)
        pool = cls.__new__(cls)
        pool._lock = threading.Lock()
        pool._closed = False
        worker = SimpleNamespace(ready=threading.Event(), closed=False,
                                 process=SimpleNamespace(poll=lambda: None))
        worker.ready.set()
        pool._workers = [worker]
        pool.refill = Mock()
        self.assertIs(pool.claim(refill=False), worker)
        pool.refill.assert_not_called()
        self.assertEqual(pool._workers, [])

    def test_controller_refills_once_even_if_ready_is_followed_by_close(self):
        cls = load_class('WinUx/dialogs/floating_dialog.py', 'FloatingDialogController')
        controller = cls.__new__(cls)
        controller._prewarm_pool = SimpleNamespace(refill=Mock())
        controller._prewarm_refill_requested = False
        controller._refill_prewarm_pool()
        controller._refill_prewarm_pool()
        controller._prewarm_pool.refill.assert_called_once_with()
