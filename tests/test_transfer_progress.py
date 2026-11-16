"""Latest per-file progress, ordered terminal delivery and cheap row updates."""
from collections import deque
import gc
import itertools
import os
from pathlib import Path
import sys
import threading
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import weakref

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.runtime.transfer_progress import TransferProgressDelivery
from WinUx.runtime.frame_clock import AdaptiveFrameClock
from WinUx.dialogs.logic.transfer import TransferCenterLogic
from WinUx.dialogs.transfer_center_form import TransferCenterDialog
from WinUx.controllers.transfer import TransferController
from WinUx.controllers.clipboard_transfer import ClipboardTransferController


class Scheduler:
    def __init__(self):
        self.pending = deque()
        self.wakes = 0
    def after(self, delay, callback, *args):
        self.wakes += 1
        self.pending.append((callback, args))
    def turn(self):
        callback, args = self.pending.popleft()
        callback(*args)
    def flush(self):
        while self.pending:
            self.turn()


class Center(TransferCenterLogic):
    def __init__(self):
        self.tasks, self._row_to_task, self._row_ids = [], {}, itertools.count(1)
        self.updates = {}
        self.view = SimpleNamespace(after=Mock())
        self.show, self.hide = Mock(), Mock()
    def post(self, *args):
        return True
    def update_row(self, row_id, **values):
        self.updates.setdefault(row_id, {}).update(values)


class TransferProgressTests(unittest.TestCase):
    def test_burst_keeps_latest_sample_and_one_wake(self):
        scheduler, events = Scheduler(), []
        pump = TransferProgressDelivery(scheduler.after, lambda *args: events.append(args))
        for i in range(30000):
            pump.progress('large.odb', i, 30000, i, 30000)
        self.assertEqual(scheduler.wakes, 1)
        self.assertEqual(len(pump._pending), 1)
        pump.finish(lambda: events.append('finished'))
        self.assertFalse(pump.progress('late', 1, 1, 1, 1))
        scheduler.flush()
        self.assertEqual(events, [('large.odb', 29999, 30000, 29999, 30000), 'finished'])
        self.assertTrue(pump._closed)

    def test_terminal_never_overtakes_samples_across_small_batches(self):
        scheduler, events = Scheduler(), []
        pump = TransferProgressDelivery(scheduler.after, lambda name, *args: events.append(name), max_batch=1)
        for name in ('a', 'b', 'c'):
            pump.progress(name, 1, 10, 1, 30)
        pump.finish(lambda: events.append('failure'))
        scheduler.turn()
        self.assertEqual(events, ['a'])
        scheduler.flush()
        self.assertEqual(events, ['a', 'b', 'c', 'failure'])

    def test_late_frame_flush_cannot_run_completion_or_modal_callbacks(self):
        scheduler, events = Scheduler(), []
        pump = TransferProgressDelivery(scheduler.after, lambda name, *args: events.append(name))
        pump.progress('a', 1, 10, 1, 10)
        pump.finish(lambda: events.append('terminal'))
        pump.flush_progress()
        self.assertEqual(events, ['a'])
        self.assertEqual(len(scheduler.pending), 1)
        scheduler.flush()
        self.assertEqual(events, ['a', 'terminal'])

    def test_reentrant_replacement_cannot_skip_a_file_or_terminal(self):
        scheduler, events = Scheduler(), []
        pump = None
        def progress(name, done, *args):
            events.append((name, done))
            if name == 'a':
                pump.progress('b', 99, 100, 99, 200)
                pump.finish(lambda: events.append('done'))
        pump = TransferProgressDelivery(scheduler.after, progress)
        pump.progress('a', 1, 100, 1, 200)
        pump.progress('b', 2, 100, 2, 200)
        scheduler.flush()
        self.assertEqual(events, [('a', 1), ('b', 99), 'done'])

    def test_failed_progress_consumer_does_not_drop_terminal(self):
        scheduler, terminal = Scheduler(), Mock()
        pump = TransferProgressDelivery(scheduler.after, Mock(side_effect=ValueError('bad progress')))
        pump.progress('a', 1, 2, 1, 2)
        pump.finish(terminal)
        with self.assertRaisesRegex(ValueError, 'bad progress'):
            scheduler.flush()
        terminal.assert_called_once()
        self.assertTrue(pump._closed)

    def test_close_releases_dialog_before_scheduled_turn(self):
        scheduler = Scheduler()
        class Dialog:
            def update(self, *args):
                raise AssertionError('closed delivery ran')
        dialog = Dialog()
        reference = weakref.ref(dialog)
        pump = TransferProgressDelivery(scheduler.after, dialog.update)
        pump.progress('a', 1, 2, 1, 2)
        pump.finish(dialog.update)
        del dialog
        pump.close()
        gc.collect()
        self.assertIsNone(reference())
        scheduler.flush()

    def test_concurrent_producers_are_coalesced(self):
        scheduler, events = Scheduler(), []
        pump = TransferProgressDelivery(scheduler.after, lambda *args: events.append(args))
        workers = [threading.Thread(target=lambda: [pump.progress('a', i, 9999, i, 9999) for i in range(1000)]) for _ in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        pump.progress('a', 9999, 9999, 9999, 9999)
        pump.finish(lambda: events.append('done'))
        self.assertEqual(scheduler.wakes, 1)
        scheduler.flush()
        self.assertEqual(events[0], ('a', 9999, 9999, 9999, 9999))
        self.assertEqual(events[-1], 'done')

    def test_failure_marks_the_actual_file_after_flushing_progress(self):
        scheduler, center = Scheduler(), Center()
        task = center.add_task('Upload', threading.Event(), ['a', 'b', 'c'])
        pump = TransferProgressDelivery(scheduler.after, task.update_progress, max_batch=1)
        pump.progress('a', 100, 100, 100, 300)
        pump.progress('b', 20, 100, 120, 300)
        pump.finish(task.fail, 'connection lost')
        scheduler.flush()
        self.assertEqual([row.state for row in task.rows], ['completed', 'failed', 'skipped'])

    def test_full_byte_count_is_not_success_when_publication_fails(self):
        scheduler, center = Scheduler(), Center()
        task = center.add_task('Upload', threading.Event(), ['a', 'b'])
        delivery = TransferProgressDelivery(scheduler.after, task.update_progress)
        delivery.progress('a', 100, 100, 100, 200)
        delivery.finish(task.fail, 'validation/publication failed')
        scheduler.flush()
        self.assertEqual([row.state for row in task.rows], ['failed', 'skipped'])

    def test_controller_upload_download_quick_and_clipboard_keep_failure_order(self):
        root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
        with tempfile.TemporaryDirectory(dir=root) as destination:
            for route in ('upload', 'download', 'quick', 'clipboard'):
                with self.subTest(route=route):
                    scheduler, center = Scheduler(), Center()
                    def io(*args, **kwargs):
                        callback = kwargs['progress']
                        callback('a', 100, 100, 100, 300)
                        callback('b', 20, 100, 120, 300)
                        raise OSError('simulated connection failure')
                    view = SimpleNamespace(after=scheduler.after, show_error=Mock(),
                                           show_transfer_progress=lambda op, event, items: center.add_task(op, event, items))
                    app = SimpleNamespace(view=view, _closing=False, _refresh_all=Mock(),
                                          _clipboard_generation=1, _connection_generation=1,
                                          _clipboard_item_names=lambda paths: [p.name for p in paths],
                                          _submit_transfer=lambda name, worker, **kwargs: worker(),
                                          server=SimpleNamespace(host='site', _port=22, username='user',
                                                                 upload=Mock(side_effect=io), download=Mock(side_effect=io)))
                    controller = TransferController(app)
                    local = SimpleNamespace(panel_id='local', current_path=Path(destination), status=Mock())
                    server = SimpleNamespace(panel_id='server', current_path='/dest', status=Mock())
                    if route == 'clipboard':
                        clipboard = ClipboardTransferController(app)
                        app._clipboard_transfer_failed = clipboard.failed
                        app._transfer_failed = controller.transfer_failed
                        clipboard.start(server, 'local', [Path('a'), Path('b'), Path('c')], False, True, 1)
                    elif route == 'quick':
                        controller.start_quick_transfer(local, server, [Path('a'), Path('b'), Path('c')], '/dest', '.inp', 'Upload')
                    else:
                        source, target = (server, local) if route == 'download' else (local, server)
                        controller.start_drop_transfer(source, target, [Path('a'), Path('b'), Path('c')], target.current_path, True)
                    task = center.tasks[0]
                    self.assertEqual(task.state, 'running')
                    scheduler.flush()
                    self.assertEqual([row.state for row in task.rows], ['completed', 'failed', 'skipped'])

    def test_indexed_lookup_handles_duplicate_leaf_names_and_placeholder(self):
        center = Center()
        task = center.add_task('Download', threading.Event(), ['/a/file.inp', '/b/file.inp'])
        task.update_progress('/a/file.inp', 100, 100, 100, 200)
        task.update_progress('/b/file.inp', 10, 100, 110, 200)
        self.assertEqual([row.state for row in task.rows], ['completed', 'running'])
        self.assertIs(task._active_row, task.rows[1])
        center.remove_task(task)
        self.assertFalse(task._rows_by_name)
        self.assertFalse(task._rows_by_leaf)
        task = center.add_task('Download', threading.Event())
        task.update_progress('named.odb', 1, 10, 1, 10)
        self.assertEqual(list(task._rows_by_name), ['named.odb'])

    def test_visible_recent_transfer_gets_fast_pacing_but_stall_does_not(self):
        now = [10.0]
        clock = AdaptiveFrameClock(clock=lambda: now[0])
        clock.last_input = -10
        clock.presented()
        clock.work()
        self.assertAlmostEqual(clock.delay(transferring=True), 1 / 60)
        self.assertAlmostEqual(clock.delay(), 1 / 30)
        self.assertAlmostEqual(clock.delay(transferring=True, foreground=False), 1 / 30)
        now[0] += 1
        clock.presented()
        self.assertAlmostEqual(clock.delay(transferring=True), .5)

    def test_unchanged_status_and_percentage_do_not_rebind_or_recenter(self):
        cls = TransferCenterDialog
        fake = SimpleNamespace(_infer_state=cls._infer_state, _text_theme_state=cls._text_theme_state,
                               _progress_theme_state=cls._progress_theme_state,
                               _schedule_progress_recenter=Mock())
        row = {'state': 'queued', 'status': '', 'status_text': 1, 'progress': 2, 'percentage': 3}
        fake.row_widgets = {7: row}
        adapter = Mock()
        with patch('WinUx.dialogs.transfer_center_form.QRetainedItem', return_value=adapter) as factory, \
                patch('WinUx.dialogs.transfer_center_form.transfer_status_text_theme'), \
                patch('WinUx.dialogs.transfer_center_form.progress_theme'):
            cls._set_row_status_visuals(fake, row, state='running', label='Running')
            initial = factory.call_count
            for _ in range(100):
                self.assertFalse(cls._set_row_status_visuals(fake, row, state='running', label='Running'))
            self.assertEqual(factory.call_count, initial)
            cls._set_progress_text(fake, 7, .1)
            cls._set_progress_text(fake, 7, .10001)
            self.assertEqual(fake._schedule_progress_recenter.call_count, 1)

    def test_bar_updates_frequently_but_speed_text_does_not_flicker_each_frame(self):
        center = Center()
        task = center.add_task('Upload', threading.Event(), ['a'])
        center.update_row = Mock()
        now = [0.0]
        with patch('WinUx.dialogs.logic.transfer.time.monotonic', side_effect=lambda: now[0]):
            for i in range(10):
                now[0] = i * .01
                task.update_progress('a', i, 100, i, 100)
            samples = [call.kwargs for call in center.update_row.call_args_list]
            self.assertEqual(len(samples), 10)
            self.assertEqual(sum('statistics' in sample for sample in samples), 1)
            now[0] = .21
            task.update_progress('a', 20, 100, 20, 100)
            self.assertIn('statistics', center.update_row.call_args.kwargs)
            now[0] = .22
            task.update_progress('a', 100, 100, 100, 100)
            self.assertIn('Finishing', center.update_row.call_args.kwargs['statistics'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
