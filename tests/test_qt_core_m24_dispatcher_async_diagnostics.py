import time

import DearUIQt
from DearUIQt.core import QEventDispatcher, QThreadPool
from DearUIQt.runtime import QGuiRuntime
from WinUx.runtime.ui_dispatcher import UiDispatcher


def test_priority_wait_diagnostics_exposes_low_priority_starvation():
    now = [0.0]
    dispatcher = QEventDispatcher(clock=lambda: now[0])

    def high_priority_work():
        now[0] += 0.100

    dispatcher.post(lambda: None, priority=-10)
    dispatcher.post(high_priority_work, priority=10)
    assert dispatcher.processEvents(None, None) == 2
    snap = dispatcher.priorityDiagnosticsSnapshot(
        window_seconds=1.0, starvation_threshold_ms=50.0)
    high = snap['priorities']['10']
    low = snap['priorities']['-10']
    assert high['queue_wait_ms_p95'] == 0.0
    assert low['queue_wait_ms_p95'] >= 100.0
    assert high['starved_samples'] == 0
    assert low['starved_samples'] == 1


def test_queue_wait_regression_uses_non_overlapping_baseline():
    now = [10.0]
    dispatcher = QEventDispatcher(clock=lambda: now[0])
    for _ in range(10):
        dispatcher.post(lambda: None)
        now[0] += 0.001
        dispatcher.processEvents(None, None)
        now[0] += 0.100

    now[0] = 29.0
    for _ in range(6):
        dispatcher.post(lambda: None)
        now[0] += 0.050
        dispatcher.processEvents(None, None)
        now[0] += 0.020

    comparison = dispatcher.queueWaitComparisonSnapshot(
        current_window_seconds=5.0,
        baseline_window_seconds=30.0,
        min_current_samples=5,
        min_baseline_samples=5)
    assert comparison['ready'] is True
    assert comparison['current']['queue_wait_ms_p95'] >= 49.0
    assert comparison['baseline']['queue_wait_ms_p95'] < 2.0
    assert comparison['queue_wait_p95_delta_ms'] > 40.0

    regression = dispatcher.queueWaitRegressionSnapshot(
        current_window_seconds=5.0,
        baseline_window_seconds=30.0,
        min_current_samples=5,
        min_baseline_samples=5,
        max_p95_ratio=2.0,
        max_p95_delta_ms=10.0)
    assert regression['threshold_breached'] is True
    assert regression['checks']['queue_wait_p95_delta_ms'] is True


def test_thread_pool_diagnostics_are_read_only_and_count_futures():
    pool = QThreadPool(maxThreadCount=1, name='m24-diagnostics')
    gate = __import__('threading').Event()
    future = pool.start(lambda: gate.wait(1.0))
    for _ in range(100):
        snap = pool.diagnosticsSnapshot()
        if snap['active_thread_count']:
            break
        time.sleep(0.005)
    assert snap['thread_count'] == 1
    assert snap['active_thread_count'] == 1
    assert snap['futures']['live'] >= 1
    assert snap['futures']['running'] >= 1
    gate.set()
    assert future.waitForFinished(2.0)
    done = pool.diagnosticsSnapshot()
    assert done['futures']['finished'] >= 1
    pool.close(wait=True)


def test_unified_runtime_report_contains_async_and_dispatcher_regression_data():
    class Backend:
        pass

    runtime = QGuiRuntime(Backend())
    dispatcher = QEventDispatcher()
    dispatcher.post(lambda: None)
    dispatcher.processEvents(None, None)
    report = runtime.performanceReportSnapshot(dispatcher)
    assert 'dispatcher_queue_wait_regression' in report
    assert 'dispatcher_priority_wait' in report
    assert 'async_runtime' in report
    assert 'qobject_live_count' in report['async_runtime']
    assert 'global_thread_pool' in report['async_runtime']


def test_ui_dispatcher_legacy_methods_live_in_explicit_compat_module():
    dispatcher = UiDispatcher()
    assert dispatcher.drain.__func__.__module__ == 'WinUx.runtime.ui_dispatcher_legacy'
    assert dispatcher.snapshot.__func__.__module__ == 'WinUx.runtime.ui_dispatcher_legacy'
    dispatcher.post(lambda: None)
    assert dispatcher.drain(max_callbacks=None, time_budget_ms=None) == 1
    assert dispatcher.snapshot()['pending_count'] == 0
    dispatcher.close()


def test_m24_version_floor():
    assert tuple(map(int, DearUIQt.__version__.split('.'))) >= (1, 148, 0)
