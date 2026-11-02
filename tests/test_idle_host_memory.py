"""Only unused clean dialog hosts expire; active/retained tool state is safe."""
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.ui.hosting.host import QDialogHostPool, QDialogHostManager


class HostMemoryTests(unittest.TestCase):
    def pool(self):
        return QDialogHostPool(capacity=1, reusable=True, signature_cache=False, autostart=False)

    def host(self, since, ready=True):
        return SimpleNamespace(idle_ack=ready, idle_since=since, close=Mock())

    def test_only_expired_clean_idle_host_is_closed(self):
        pool = self.pool()
        old, recent, preparing = self.host(10), self.host(150), self.host(None, False)
        pool._workers = [old, recent, preparing]
        leased = Mock()
        pool._leased.add(leased)
        with patch.object(pool, 'refill') as refill:
            self.assertEqual(pool.trim_idle(120, now=200), 1)
            refill.assert_not_called()
        old.close.assert_called_once()
        recent.close.assert_not_called()
        preparing.close.assert_not_called()
        leased.close.assert_not_called()
        self.assertEqual(pool._workers, [recent, preparing])

    def test_gui_maintenance_does_not_wait_on_pool_lock(self):
        pool = self.pool()
        pool._lock.acquire()
        try:
            self.assertEqual(pool.trim_idle(0), 0)
        finally:
            pool._lock.release()

    def test_closed_pool_does_not_trim_again(self):
        pool = self.pool()
        pool._closed = True
        old = self.host(0)
        pool._workers = [old]
        self.assertEqual(pool.trim_idle(0, now=200), 0)
        old.close.assert_not_called()

    def test_returned_lease_gets_a_fresh_idle_grace_period(self):
        pool = self.pool()
        worker = Mock()
        worker.lease, worker.closed, worker.reuse_count = 'lease', False, 0
        worker.process.poll.return_value = None
        worker.channel_healthy.return_value = True
        worker.ready = threading.Event()
        pool._leased.add(worker)
        with patch.object(pool, '_identity', return_value=object()), \
                patch.object(pool, '_matches', return_value=True), \
                patch('WinUx.ui.hosting.host.time.monotonic', return_value=1000):
            self.assertTrue(pool.release(worker, 'lease'))
        self.assertEqual(worker.idle_since, 1000)
        self.assertEqual(pool.trim_idle(120, now=1050), 0)
        self.assertEqual(pool.trim_idle(120, now=1120), 1)
        worker.close.assert_called_once()

    def test_manager_schedules_one_sweep_and_cancels_on_close(self):
        view = SimpleNamespace(after=Mock(return_value=123), after_cancel=Mock())
        pool = Mock()
        manager = QDialogHostManager(view, pool)
        manager.schedule_idle_trim()
        manager.schedule_idle_trim()
        view.after.assert_called_once_with(30000, manager._trim_idle_hosts)
        manager._trim_idle_hosts()
        pool.trim_idle.assert_called_once_with(120.0)
        self.assertEqual(view.after.call_count, 2)
        manager.close()
        view.after_cancel.assert_called_once_with(123)
        pool.close.assert_called_once()
        manager._trim_idle_hosts()
        self.assertEqual(view.after.call_count, 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
