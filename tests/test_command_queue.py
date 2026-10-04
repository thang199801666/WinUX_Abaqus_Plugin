import queue
import ast
from pathlib import Path
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from WinUx.runtime.command_queue import LatestCommandQueue


def controller_shell():
    """Execute real transport methods without importing native input hooks."""
    source = Path(__file__).resolve().parents[1] / "WinUx/dialogs/floating_dialog.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "FloatingDialogController")
    methods = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in {"post", "post_latest"}]
    shell = ast.ClassDef(name="Controller", bases=[], keywords=[], body=methods, decorator_list=[])
    namespace = {"queue": queue}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[shell], type_ignores=[])), str(source), "exec"), namespace)
    return namespace["Controller"]()


class CommandQueueTests(unittest.TestCase):
    def test_display_burst_occupies_one_slot_with_latest_value(self):
        pending = LatestCommandQueue(4)
        for i in range(10000):
            pending.put_latest("progress", i)
        self.assertEqual(pending.qsize(), 1)
        self.assertEqual(pending.get_nowait(), 9999)
        pending.task_done()
        pending.join()

    def test_ordinary_command_is_a_replacement_barrier(self):
        pending = LatestCommandQueue(8)
        pending.put_latest("state", "before")
        pending.put_nowait("cancel")
        pending.put_latest("state", "after-1")
        pending.put_latest("state", "after-2")
        self.assertEqual([pending.get_nowait() for _ in range(3)], ["before", "cancel", "after-2"])

    def test_old_entry_delivery_does_not_invalidate_new_segment(self):
        pending = LatestCommandQueue(8)
        pending.put_latest("state", 1)
        pending.put_nowait("command")
        pending.put_latest("state", 2)
        self.assertEqual(pending.get_nowait(), 1)
        pending.put_latest("state", 3)
        self.assertEqual(pending.qsize(), 2)
        self.assertEqual([pending.get_nowait(), pending.get_nowait()], ["command", 3])

    def test_full_queue_can_replace_state_but_never_drops_commands(self):
        pending = LatestCommandQueue(2)
        pending.put_nowait("run")
        pending.put_latest("state", 1)
        pending.put_latest("state", 2)
        with self.assertRaises(queue.Full):
            pending.put_nowait("delete")
        with self.assertRaises(queue.Full):
            pending.put_latest("other", 3)
        self.assertEqual([pending.get_nowait(), pending.get_nowait()], ["run", 2])

    def test_consumer_wakes_for_latest_state_and_empty_timeout_is_preserved(self):
        pending = LatestCommandQueue(2)
        result, ready = [], threading.Event()
        def consume():
            ready.set()
            result.append(pending.get(timeout=1))
        consumer = threading.Thread(target=consume)
        consumer.start()
        self.assertTrue(ready.wait(1))
        pending.put_latest("state", "ready")
        consumer.join(1)
        self.assertFalse(consumer.is_alive())
        self.assertEqual(result, ["ready"])
        with self.assertRaises(queue.Empty):
            pending.get(timeout=0.001)

    def test_simultaneous_producers_keep_one_slot_per_state_key(self):
        pending = LatestCommandQueue(8)
        def produce(key):
            for i in range(1000):
                pending.put_latest(key, (key, i))
        workers = [threading.Thread(target=produce, args=(key,)) for key in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual(pending.qsize(), 4)
        self.assertEqual({pending.get_nowait() for _ in range(4)}, {(key, 999) for key in range(4)})

    def test_controller_publishes_latest_state_and_preserves_failure_command(self):
        controller = controller_shell()
        controller._closed = False
        controller._outgoing = LatestCommandQueue(4)
        controller.view = SimpleNamespace(after=Mock())
        controller._failed = Mock()
        for i in range(100):
            self.assertTrue(controller.post_latest("progress", i))
        self.assertTrue(controller.post("fail", "message"))
        self.assertEqual(controller._outgoing.qsize(), 2)
        self.assertEqual(controller._outgoing.get_nowait()["args"], (99,))
        self.assertEqual(controller._outgoing.get_nowait()["command"], "fail")
        controller._closed = True
        self.assertFalse(controller.post_latest("progress", 100))

    def test_controller_reports_full_queue(self):
        controller = controller_shell()
        controller._closed = False
        controller._outgoing = LatestCommandQueue(1)
        controller.view = SimpleNamespace(after=Mock())
        controller._failed = Mock()
        controller.post("init")
        self.assertFalse(controller.post_latest("progress", 1))
        controller.view.after.assert_called_once()
