import gc
import weakref

from DearUIQt.core import QEventDispatcher, QThreadPool
from DearUIQt.runtime import QGuiRuntime


class Clock:
    def __init__(self):
        self.now = 0.0
    def __call__(self):
        return self.now
    def advance(self, seconds):
        self.now += float(seconds)


def _deliver(dispatcher, clock, priority, wait_ms, count):
    for _ in range(count):
        dispatcher.post(lambda: None, priority=priority)
        clock.advance(float(wait_ms) / 1000.0)
        dispatcher.processEvents(max_callbacks=None, time_budget_ms=None)


def test_priority_recent_vs_baseline_regression_is_non_overlapping():
    clock = Clock()
    dispatcher = QEventDispatcher(clock=clock)
    _deliver(dispatcher, clock, priority=-2, wait_ms=1.0, count=8)
    clock.advance(6.0)
    _deliver(dispatcher, clock, priority=-2, wait_ms=60.0, count=3)
    snap = dispatcher.priorityRegressionSnapshot(
        current_window_seconds=5.0, baseline_window_seconds=30.0,
        min_current_samples=3, min_baseline_samples=8,
        max_p95_ratio=2.0, max_p95_delta_ms=20.0)
    row = snap['comparison']['priorities']['-2']
    assert row['ready'] is True
    assert row['current_sample_count'] == 3
    assert row['baseline_sample_count'] == 8
    assert snap['threshold_breached'] is True
    assert snap['breached_priorities'] == [-2]


def test_long_queue_wait_callback_uses_safe_bounded_label():
    clock = Clock()
    dispatcher = QEventDispatcher(clock=clock)
    marker = object()
    def named_callback():
        return marker
    dispatcher.post(named_callback, priority=3)
    clock.advance(0.075)
    dispatcher.processEvents(max_callbacks=None, time_budget_ms=None)
    snap = dispatcher.longQueueWaitCallbacksSnapshot(threshold_ms=50.0)
    assert snap['count'] == 1
    row = snap['callbacks'][0]
    assert row['priority'] == 3
    assert 'named_callback' in row['label']
    assert '0x' not in row['label']
    assert len(row['label']) <= 160


def test_named_thread_pool_registry_is_weak_and_side_effect_free():
    pool = QThreadPool(maxThreadCount=1, name='m25-named-pool')
    ref = weakref.ref(pool)
    snap = QThreadPool.namedDiagnosticsSnapshot()
    assert any(row['name'] == 'm25-named-pool' for row in snap['pools'])
    pool.close(wait=True)
    del pool
    gc.collect()
    assert ref() is None
    snap2 = QThreadPool.namedDiagnosticsSnapshot()
    assert not any(row['name'] == 'm25-named-pool' for row in snap2['pools'])


def test_release_performance_acceptance_is_sample_gated():
    clock = Clock()
    dispatcher = QEventDispatcher(clock=clock)
    runtime = object.__new__(QGuiRuntime)
    runtime.framePerformanceSnapshot = lambda: {
        'render_rate_hz_5s': 0.5,
        'idle_fraction_5s': 0.95,
    }
    early = QGuiRuntime.performanceAcceptanceSnapshot(runtime, dispatcher, min_dispatcher_samples=3)
    assert early['ready'] is False
    assert early['accepted'] is False
    _deliver(dispatcher, clock, priority=0, wait_ms=1.0, count=3)
    ready = QGuiRuntime.performanceAcceptanceSnapshot(runtime, dispatcher, min_dispatcher_samples=3)
    assert ready['ready'] is True
    assert ready['accepted'] is True
