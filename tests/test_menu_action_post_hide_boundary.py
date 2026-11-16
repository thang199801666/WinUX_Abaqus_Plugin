import unittest
from DearUIQt.widgets.menu import QMenu


class _Menu(QMenu):
    def __init__(self):
        # Deliberately avoid renderer allocation; this test targets only the
        # post-hide scheduling contract.
        self.queued = []
        self._after = lambda delay, callback, *args: self.queued.append((delay, callback, args))


class MenuPostHideBoundaryTests(unittest.TestCase):
    def test_delivery_is_deferred_when_scheduler_exists(self):
        menu = _Menu()
        called = []
        self.assertTrue(menu._deliver_after_hide(lambda value: called.append(value), 'ok'))
        self.assertEqual(called, [])
        self.assertEqual(len(menu.queued), 1)
        delay, callback, args = menu.queued.pop(0)
        self.assertEqual(delay, 0)
        callback(*args)
        self.assertEqual(called, ['ok'])

    def test_non_callable_is_rejected_without_invocation(self):
        menu = _Menu()
        self.assertFalse(menu._deliver_after_hide(None))
        self.assertEqual(menu.queued, [])

    def test_fallback_without_scheduler_is_direct_for_lightweight_hosts(self):
        menu = _Menu()
        menu._after = None
        called = []
        self.assertTrue(menu._deliver_after_hide(lambda: called.append(True)))
        self.assertEqual(called, [True])


if __name__ == '__main__':
    unittest.main()
