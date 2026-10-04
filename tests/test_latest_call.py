import threading
import unittest

from WinUx.runtime.latest_call import LatestCallQueue


class LatestCallTests(unittest.TestCase):
    def queue(self):
        callbacks = []
        queue = LatestCallQueue(lambda delay, callback, *args: callbacks.append((callback, args)))
        return queue, callbacks

    def drain(self, callbacks):
        while callbacks:
            callback, args = callbacks.pop(0)
            callback(*args)

    def test_burst_preserves_only_latest_state_per_key(self):
        queue, callbacks = self.queue()
        values = []
        for value in range(10_000):
            queue.post("progress", values.append, value)
        self.assertEqual(len(callbacks), 1)
        self.drain(callbacks)
        self.assertEqual(values, [9999])

    def test_reentrant_and_independent_updates_are_delivered(self):
        queue, callbacks = self.queue()
        values = []
        queue.post("a", lambda: queue.post("a", values.append, "next"))
        queue.post("b", values.append, "b")
        self.drain(callbacks)
        self.assertEqual(values, ["b", "next"])

    def test_close_discards_queued_payloads(self):
        queue, callbacks = self.queue()
        values = []
        queue.post("a", values.append, 1)
        queue.close()
        self.assertFalse(queue.post("a", values.append, 2))
        self.drain(callbacks)
        self.assertEqual(values, [])

    def test_concurrent_producers_schedule_once(self):
        queue, callbacks = self.queue()
        values = []
        threads = [threading.Thread(target=lambda: [queue.post("a", values.append, n) for n in range(100)])
                   for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(callbacks), 1)
        self.drain(callbacks)
        self.assertEqual(values, [99])

