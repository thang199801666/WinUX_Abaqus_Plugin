from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from DearUIQt.core import QEventDispatcher
from DearUIQt.runtime import StandaloneUiHost
from DearUIQt.widgets import QApplication, QWidget


class _Backend:
    def does_item_exist(self, tag):
        return True

    def delete_item(self, tag):
        return None


class GuiThreadLatestTests(unittest.TestCase):
    def tearDown(self):
        app = QApplication.instance()
        if app is not None:
            app.delete()

    def test_dispatcher_post_latest_replaces_payload_without_growing_queue(self):
        dispatcher = QEventDispatcher()
        received = []
        first = dispatcher.postLatest("same", received.append, 1)
        second = dispatcher.postLatest("same", received.append, 2)
        third = dispatcher.postLatest("same", received.append, 3)
        self.assertEqual(first, second)
        self.assertEqual(second, third)
        self.assertEqual(dispatcher.pendingCount(), 1)
        self.assertEqual(dispatcher.processEvents(), 1)
        self.assertEqual(received, [3])

    def test_worker_burst_wakes_once_and_delivers_latest_value(self):
        dispatcher = QEventDispatcher()
        received = []
        wakes = []
        dispatcher.setWakeCallback(lambda: wakes.append(1))

        def worker():
            for value in range(100):
                dispatcher.postLatest("burst", received.append, value)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertEqual(dispatcher.pendingCount(), 1)
        self.assertEqual(len(wakes), 1)
        self.assertEqual(dispatcher.processEvents(), 1)
        self.assertEqual(received, [99])

    def test_qapplication_resolves_host_dispatcher_and_enforces_owner_thread(self):
        host = StandaloneUiHost(backend=object())
        app = QApplication(after=host.after)
        self.assertTrue(app.isGuiThread())
        self.assertIs(app._call_dispatcher(), host.dispatcher)
        errors = []

        def worker():
            try:
                app.assertGuiThread("test mutation")
            except RuntimeError as exc:
                errors.append(str(exc))

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertEqual(len(errors), 1)
        self.assertIn("QApplication GUI thread", errors[0])
        app.delete()
        host.close()

    def test_widget_worker_updates_share_application_dispatcher(self):
        host = StandaloneUiHost(backend=object())
        app = QApplication(after=host.after)
        widget = QWidget(tag="fake", after=host.after, backend=_Backend())
        received = []

        def worker():
            widget._on_ui("value", received.append, 1)
            widget._on_ui("value", received.append, 2)
            widget._on_ui("value", received.append, 3)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertIsNone(widget._updates, "canonical QApplication path should not allocate a widget-local queue")
        self.assertEqual(host.dispatcher.pendingCount(), 1)
        self.assertEqual(host.pump(), 1)
        self.assertEqual(received, [3])
        widget.delete()
        app.delete()
        host.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
