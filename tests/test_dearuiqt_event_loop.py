from collections import deque
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from DearUIQt.QtCore import QEvent, QEventLoop, QObject
from DearUIQt.core.application import QApplication


class Scheduler:
    def __init__(self):
        self.callbacks = deque()

    def after(self, _delay, callback, *args):
        self.callbacks.append((callback, args))

    def turn(self):
        if not self.callbacks:
            return False
        callback, args = self.callbacks.popleft()
        callback(*args)
        return True


class ExitReceiver(QObject):
    def __init__(self, loop, code=0, **kwargs):
        super().__init__(**kwargs)
        self.loop = loop
        self.code = code
        self.events = []

    def event(self, event):
        if event.type() == QEvent.User:
            self.events.append(event.type())
            self.loop.exit(self.code)
            return True
        return super().event(event)


class EventLoopTests(unittest.TestCase):
    def tearDown(self):
        app = QApplication.instance()
        if app is not None:
            app.delete()

    def test_qtcore_facade_exports_event_loop(self):
        from DearUIQt import QEventLoop as RootEventLoop
        self.assertIs(RootEventLoop, QEventLoop)

    def test_posted_event_exits_nested_loop_with_result(self):
        scheduler = Scheduler()
        app = QApplication(after=scheduler.after)
        loop = QEventLoop(application=app)
        receiver = ExitReceiver(loop, 17, after=scheduler.after)
        app.postEvent(receiver, QEvent(QEvent.User))
        self.assertEqual(loop.exec(), 17)
        self.assertEqual(receiver.events, [QEvent.User])
        receiver.delete()
        loop.delete()

    def test_deferred_delete_is_delivered_inside_nested_loop(self):
        scheduler = Scheduler()
        app = QApplication(after=scheduler.after)
        target = QObject(after=scheduler.after)
        loop = QEventLoop(application=app)
        receiver = ExitReceiver(loop, 3, after=scheduler.after)
        target.deleteLater()
        app.postEvent(receiver, QEvent(QEvent.User))
        self.assertEqual(loop.exec(), 3)
        self.assertTrue(target._deleted)
        receiver.delete()
        loop.delete()

    def test_host_pump_can_quit_loop_without_private_worker(self):
        scheduler = Scheduler()
        app = QApplication(after=scheduler.after)
        turns = []
        loop = None

        def pump():
            turns.append(len(turns) + 1)
            scheduler.turn()
            if len(turns) == 2:
                loop.quit()

        loop = QEventLoop(application=app, pump=pump)
        self.assertEqual(loop.exec(), 0)
        self.assertEqual(turns, [1, 2])
        loop.delete()


    def test_application_host_turn_is_shared_by_nested_loops(self):
        scheduler = Scheduler()
        app = QApplication(after=scheduler.after)
        turns = []
        loop = QEventLoop(application=app)

        def host_turn():
            turns.append(len(turns) + 1)
            if len(turns) == 3:
                loop.exit(9)

        app.setHostTurn(host_turn)
        self.assertIs(app.hostTurn(), host_turn)
        self.assertEqual(loop.exec(), 9)
        self.assertEqual(turns, [1, 2, 3])
        loop.delete()

    def test_application_quit_detaches_host_turn(self):
        scheduler = Scheduler()
        app = QApplication(after=scheduler.after)
        app.setHostTurn(lambda: None)
        app.quit()
        self.assertIsNone(app.hostTurn())

    def test_reentrant_exec_is_rejected(self):
        scheduler = Scheduler()
        app = QApplication(after=scheduler.after)
        errors = []
        loop = None

        def pump():
            try:
                loop.exec()
            except RuntimeError as exc:
                errors.append(str(exc))
            loop.quit()

        loop = QEventLoop(application=app, pump=pump)
        loop.exec()
        self.assertEqual(errors, ["QEventLoop is already running"])
        loop.delete()


if __name__ == '__main__':
    unittest.main()
