import gc
import unittest
import weakref

from DearUIQt.core import QCoreApplication, QEventDispatcher, QObject, QThread
from DearUIQt.widgets import QApplication
from DearUIQt.runtime import StandaloneUiHost


class QtCoreM11RuntimeTests(unittest.TestCase):
    def tearDown(self):
        app = QCoreApplication.instance()
        if app is not None:
            app.delete()

    def test_qcoreapplication_is_real_base_type_with_shared_singleton(self):
        self.assertIsNot(QCoreApplication, QApplication)
        self.assertTrue(issubclass(QApplication, QCoreApplication))
        app = QApplication(after=lambda delay, callback, *args: None)
        self.assertIs(QCoreApplication.instance(), app)
        self.assertIs(QApplication.instance(), app)
        with self.assertRaises(RuntimeError):
            QCoreApplication(after=lambda delay, callback, *args: None)

    def test_core_instance_prevents_second_gui_application(self):
        app = QCoreApplication(after=lambda delay, callback, *args: None)
        self.assertIs(QCoreApplication.instance(), app)
        self.assertIs(QApplication.instance(), app)
        with self.assertRaises(RuntimeError):
            QApplication(after=lambda delay, callback, *args: None)

    def test_dispatcher_priority_is_ordered_within_ready_turn(self):
        now = [10.0]
        dispatcher = QEventDispatcher(clock=lambda: now[0])
        seen = []
        dispatcher.post(seen.append, 'normal', priority=0)
        dispatcher.post(seen.append, 'high-a', priority=10)
        dispatcher.post(seen.append, 'low', priority=-10)
        dispatcher.post(seen.append, 'high-b', priority=10)
        self.assertEqual(dispatcher.processEvents(), 4)
        self.assertEqual(seen, ['high-a', 'high-b', 'normal', 'low'])

    def test_future_priority_does_not_jump_a_deadline(self):
        now = [1.0]
        dispatcher = QEventDispatcher(clock=lambda: now[0])
        seen = []
        dispatcher.after(0, seen.append, 'ready', priority=-100)
        dispatcher.after(50, seen.append, 'future', priority=100)
        self.assertEqual(dispatcher.processEvents(), 1)
        self.assertEqual(seen, ['ready'])
        now[0] += 0.1
        self.assertEqual(dispatcher.processEvents(), 1)
        self.assertEqual(seen, ['ready', 'future'])

    def test_application_post_call_preserves_dispatcher_priority(self):
        host = StandaloneUiHost(backend=object())
        app = QCoreApplication(after=host.after)
        seen = []
        app.postCall(seen.append, 'low', priority=-1)
        app.postCall(seen.append, 'high', priority=5)
        app.postCall(seen.append, 'normal')
        host.pump()
        self.assertEqual(seen, ['high', 'normal', 'low'])
        app.delete()
        host.close()

    def test_qobject_registry_and_tree_diagnostics_are_weak_and_read_only(self):
        root = QObject()
        root.setObjectName('root')
        child = QObject(root)
        child.setObjectName('child')
        leaf = QObject(child)
        leaf.setObjectName('leaf')
        snapshot = root.objectTreeSnapshot(max_depth=1)
        self.assertEqual(snapshot['object_name'], 'root')
        self.assertEqual(snapshot['child_count'], 1)
        self.assertEqual(snapshot['children'][0]['object_name'], 'child')
        self.assertTrue(snapshot['children'][0]['truncated'])
        self.assertIn(root, QObject.rootObjects(thread_id=root.threadId()))
        self.assertTrue(child.diagnosticsSnapshot()['has_parent'])

        orphan = QObject()
        ref = weakref.ref(orphan)
        self.assertIn(orphan, QObject.liveObjects())
        del orphan
        gc.collect()
        self.assertIsNone(ref())
        self.assertTrue(all(obj is not None for obj in QObject.liveObjects()))
        root.delete()

    def test_application_diagnostics_include_parentless_candidates_without_mutation(self):
        queue = []
        app = QCoreApplication(after=lambda delay, callback, *args: queue.append((callback, args)))
        child = QObject(app)
        extra_root = QObject()
        before = list(QObject.liveObjects(thread_id=app.threadId()))
        snap = app.diagnosticsSnapshot()
        after = list(QObject.liveObjects(thread_id=app.threadId()))
        self.assertEqual(set(before), set(after))
        self.assertGreaterEqual(snap['live_object_count'], 3)
        self.assertGreaterEqual(snap['parentless_object_count'], 1)
        extra_root.delete()
        child.delete()

    def test_qthread_post_priority_and_diagnostics(self):
        thread = QThread(name="m11-priority")
        seen = []
        thread.post(seen.append, "low", priority=-5)
        thread.post(seen.append, "high", priority=5)
        thread.post(seen.append, "normal")
        snap = thread.diagnosticsSnapshot()
        self.assertEqual(snap["pending_count"], 3)
        self.assertEqual(snap["highest_priority"], 5)
        thread.start()
        # Quit is queued last at the lowest priority so all ready work runs first.
        thread.post(thread.quit, priority=-100)
        self.assertTrue(thread.wait(2000))
        self.assertEqual(seen, ["high", "normal", "low"])
        final = thread.diagnosticsSnapshot()
        self.assertTrue(final["finished"])
        self.assertEqual(final["pending_count"], 0)
        thread.delete()


if __name__ == '__main__':
    unittest.main(verbosity=2)
