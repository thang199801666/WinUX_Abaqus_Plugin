import inspect
import threading
import unittest

from DearUIQt.core import QThread
from WinUx.controllers.jobs.schedule import JobScheduleController
from WinUx.services import ssh_server
from WinUx.ui.hosting import source_signature_cache


class _Dispatcher:
    def post(self, callback, *args, key=None):
        callback(*args)
        return True


class _View:
    def __init__(self):
        self._dispatcher = _Dispatcher()

    def after(self, _delay, callback, *args):
        callback(*args)


class _Server:
    connected = True
    username = "test"


class _App:
    def __init__(self):
        self._closing = True
        self.view = _View()
        self.server = _Server()


class QThreadLongLivedWorkerContractTests(unittest.TestCase):
    def test_schedule_controller_uses_qthread_worker_and_interruptible_stop(self):
        app = _App()
        controller = JobScheduleController(app)
        thread = controller.start()
        self.assertIsInstance(thread, QThread)
        self.assertIs(app._schedule_thread, thread)
        self.assertIsNotNone(app._schedule_worker)
        self.assertTrue(thread.wait(1000))
        controller.stop()
        self.assertTrue(thread.isInterruptionRequested())

    def test_schedule_source_has_no_raw_thread_creation(self):
        source = inspect.getsource(JobScheduleController.start)
        self.assertNotIn("threading.Thread", source)
        self.assertIn("QThread", source)

    def test_source_signature_cache_uses_qthread(self):
        source = inspect.getsource(source_signature_cache.SourceSignatureCache.__init__)
        self.assertNotIn("threading.Thread", source)
        self.assertIn("QThread", source)
        run_source = inspect.getsource(source_signature_cache.SourceSignatureCache._run)
        self.assertIn("isInterruptionRequested", run_source)

    def test_ssh_shell_reader_uses_qthread_worker(self):
        source = inspect.getsource(ssh_server.SSHServerModel._open_shell)
        self.assertNotIn("threading.Thread", source)
        self.assertIn("QThread", source)
        loop_source = inspect.getsource(ssh_server.SSHServerModel._read_shell_loop)
        self.assertIn("isInterruptionRequested", loop_source)

    def test_app_shutdown_stops_schedule_qthread(self):
        from WinUx.app.controller import WinUXController
        source = inspect.getsource(WinUXController._finish_close)
        self.assertIn("schedule_controller.stop()", source)


if __name__ == "__main__":
    unittest.main()
